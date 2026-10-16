"""Coupled solution: lifting line, load-adapted wake and compressible swept-row sections.

Unknowns are the bound circulations Gamma_j of N spanwise panels.  At the control point of
panel j the induced velocity is linear in Gamma (influence matrices of the vortex system),
the local thermodynamic state follows from rothalpy conservation in the rotating frame,

    h = h0_inf - (W^2 - (Omega r)^2)/2,

and the blade element returns Gamma_sec = W c CL / 2 * (t_r / cos Lambda).  The residual
Gamma - Gamma_sec(u(Gamma)) is driven to zero by Newton's method with a Jacobian
I - diag(dG/du_a) A_a - diag(dG/du_t) A_t (finite differences on the local section function,
frozen row lattice), wrapped in a fixed-point loop on the wake geometry.  A secant iteration
on the collective pitch gives a prescribed power or thrust coefficient.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np

from .gas import CP_AIR, GAMMA, R_AIR, Atmosphere, sutherland
from .geometry import Propeller
from .nacelle import NacelleFlow
from .section import SectionModel, SectionOptions, kuchemann_factor, normal_plane
from .wake import VortexSystem, WakeSettings, cyl_to_cart, local_frames, polyline_influence, rotate_x


@dataclass
class OperatingPoint:
    """Flight condition and shaft speed.  Give one of ``rpm``, ``tip_speed`` or ``J``."""

    mach: float
    altitude: float = 0.0
    atmosphere: Atmosphere | None = None
    rpm: float | None = None
    tip_speed: float | None = None
    J: float | None = None
    dbeta: float = 0.0                 # collective pitch change from the reference blade [deg]

    def resolve(self, diameter):
        atm = self.atmosphere or Atmosphere.isa(self.altitude)
        V = self.mach * atm.a
        if self.rpm is not None:
            n = self.rpm / 60.0
        elif self.tip_speed is not None:
            n = self.tip_speed / (math.pi * diameter)
        elif self.J is not None:
            n = V / (self.J * diameter)
        else:
            raise ValueError("give rpm, tip_speed or J")
        return atm, V, n


@dataclass
class Result:
    op: dict
    CT: float
    CP: float
    CQ: float
    eta: float
    J: float
    thrust: float
    power: float
    torque: float
    dbeta: float
    beta_ref: float
    losses: dict
    radial: dict
    converged: bool
    iterations: dict
    warnings: list = field(default_factory=list)

    def summary(self):
        o = self.op
        lines = [
            f"M = {o['mach']:.3f}  J = {self.J:.4f}  tip speed = {o['tip_speed']:.1f} m/s  "
            f"helical tip Mach = {o['helical_tip_mach']:.3f}",
            f"beta(ref) = {self.beta_ref:.3f} deg (dbeta {self.dbeta:+.3f})",
            f"CT = {self.CT:.5f}  CP = {self.CP:.5f}  CQ = {self.CQ:.5f}  eta = {self.eta:.4f}",
            f"T = {self.thrust:.2f} N  P = {self.power / 1e3:.3f} kW",
            "losses (fraction of shaft power): " + ", ".join(f"{k} {v:.4f}" for k, v in self.losses.items()),
        ]
        lines += [f"warning: {w}" for w in self.warnings]
        return "\n".join(lines)

    def to_dict(self):
        def conv(v):
            if isinstance(v, np.ndarray):
                return v.tolist()
            if isinstance(v, dict):
                return {k: conv(x) for k, x in v.items()}
            if isinstance(v, (np.floating, np.integer)):
                return v.item()
            return v
        return conv(dict(op=self.op, CT=self.CT, CP=self.CP, CQ=self.CQ, eta=self.eta, J=self.J,
                         thrust=self.thrust, power=self.power, torque=self.torque, dbeta=self.dbeta,
                         beta_ref=self.beta_ref, losses=self.losses, radial=self.radial,
                         converged=self.converged, iterations=self.iterations, warnings=self.warnings))


@dataclass
class SolverSettings:
    n_panels: int = 28
    newton_tol: float = 2e-6
    newton_max: int = 40
    wake_tol: float = 2e-4
    wake_max: int = 12
    wake_relax: float = 0.7
    nacelle: bool = True
    kuchemann: bool = True
    relief_3d: bool = True           # spanwise-wavenumber (3-D transonic) relief of the normal Mach number
    relief_scale: float = 1.0        # chordwise half wave (1) .. full wave (0.5) of the disturbance
    max_dalpha_deg: float = 6.0      # Newton trust region on the change of incidence
    choke_spill: bool = True         # choke-limited inflow with radial spillage
    spill_smoothing: float = 0.01    # smoothing of the choke complementarity condition
    spill_max: float = 0.6           # largest spilled fraction of the free-stream velocity


class PropellerSolver:
    def __init__(self, prop: Propeller, section: SectionOptions | None = None,
                 wake: WakeSettings | None = None, settings: SolverSettings | None = None):
        self.prop = prop
        self.st = settings or SolverSettings()
        self.wake_settings = wake or WakeSettings()
        self.section_options = section or SectionOptions()
        N = self.st.n_panels
        h = prop.blade.hub_ratio
        t = 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, N + 1)))
        self.rR_edge = h + (1.0 - h) * t
        self.rR_ctrl = 0.5 * (self.rR_edge[1:] + self.rR_edge[:-1])
        self.N = N
        S = N
        self.section = SectionModel([prop.blade.thickness_form] * S, [prop.blade.mean_line] * S,
                                    self.section_options)
        self.vs = VortexSystem(prop.blades, prop.radius, self.wake_settings)
        self._nacelle_cache = {}

    # ------------------------------------------------------------------ geometry
    def _geometry(self, dbeta):
        p = self.prop
        R = p.radius
        ctrl = p.section_frame(self.rR_ctrl, dbeta)
        edge = p.section_frame(self.rR_edge, dbeta)

        def chord_point(sec, frac):
            # point on the section at chord fraction frac from the mid-chord (+ towards TE)
            s = frac * sec["chord"]
            x = sec["x_mid"] + s * np.sin(sec["beta"])
            th = sec["theta_mid"] - s * np.cos(sec["beta"]) / sec["r"]
            return x, th

        xq_e, thq_e = chord_point(edge, -0.25)
        Pq_e = cyl_to_cart(xq_e, edge["r"], thq_e)                 # quarter-chord edge points
        Pq_c = 0.5 * (Pq_e[1:] + Pq_e[:-1])                        # bound-vortex midpoints
        Pc = Pq_c                                                  # control points (vector mean)
        ec = np.stack([np.sin(ctrl["beta"]), -np.cos(ctrl["beta"]), np.zeros_like(ctrl["r"])], axis=1)
        chord_ratio = np.sqrt(np.maximum(1.0 - np.einsum("si,si->s", ec, ctrl["t_hat"]) ** 2, 1e-6))
        # chordwise legs of the trailing filaments: quarter chord -> trailing edge
        nc = self.wake_settings.chord_points
        fr = np.linspace(-0.25, 0.5, nc)
        legs = np.stack([cyl_to_cart(*_swap(chord_point(edge, f), edge["r"])) for f in fr], axis=1)
        xte, thte = chord_point(edge, 0.5)
        sigma = p.solidity(self.rR_ctrl)
        geo = dict(ctrl=ctrl, edge=edge, Pq_e=Pq_e, Pc=Pc, Pq_c=Pq_c, legs=legs,
                   te=np.stack([xte, edge["r"], thte], axis=1), sigma=sigma,
                   r=ctrl["r"], dr=np.diff(edge["r"]), x_ctrl=Pq_c[:, 0],
                   chord_n=ctrl["chord"] * chord_ratio)
        # distance from the tip along the span, in local chords (Kuchemann)
        geo["tip_distance"] = (R - ctrl["r"]) / np.maximum(ctrl["chord"], 1e-9)
        return geo

    def _nacelle(self, mach, D):
        key = round(float(mach), 6)
        if key not in self._nacelle_cache:
            if self.prop.nacelle is None or not self.st.nacelle:
                self._nacelle_cache[key] = None
            else:
                self._nacelle_cache[key] = NacelleFlow(self.prop.nacelle, D, mach)
        return self._nacelle_cache[key]

    # ------------------------------------------------------------------ influence
    def _influence(self, geo, gamma, V, Omega, mach, nacflow):
        """Axial and tangential induced velocity at the control points per unit Gamma_j."""
        B = self.prop.blades
        R = self.prop.radius
        r_e = geo["edge"]["r"]
        rc = geo["r"]
        # mean induced velocities at the edges for the wake shape (normal to W_m)
        g_e = np.interp(r_e, rc, gamma)
        ut0 = B * g_e / (4.0 * np.pi * r_e)
        ut0 = np.minimum(ut0, 0.45 * Omega * r_e)
        disc = V * V + 4.0 * ut0 * (Omega * r_e - ut0)
        ua0 = 0.5 * (-V + np.sqrt(np.maximum(disc, 0.0)))
        hub_fn = self._hub_radius_fn()
        nac_u = (lambda x, r: nacflow.axial(x, r)) if nacflow is not None else None
        wake_pts, (wx, wr, wth) = self.vs.filaments(geo["te"], ua0, ut0, V, Omega, mach, hub_fn, nac_u)
        # full filament polylines: quarter-chord leg + helix (blade 0)
        fil0 = np.concatenate([geo["legs"][:, :-1, :], wake_pts], axis=1)
        Pc = geo["Pc"]
        core = self.wake_settings.core_R * R
        # chord-scaled cores on the trailing filaments: the vorticity shed by a section is spread
        # over its chord, and a swept lifting line evaluated with thin filaments carries a
        # spurious, panel-width-dependent near-field term proportional to dGamma/dr
        core_f = np.maximum(self.wake_settings.core_chord * geo["edge"]["chord"], core)
        F = fil0.shape[0]
        Ufil = np.zeros((Pc.shape[0], F, 3))
        for k in range(B):
            ang = 2.0 * np.pi * k / B
            fk = rotate_x(fil0, ang)
            Ufil += polyline_influence(Pc, fk, core_f)
            if self.wake_settings.hub_images:
                xh = wx
                rh = hub_fn(xh)
                on_hub = rh > 1e-6
                rim = np.where(on_hub, rh ** 2 / np.maximum(wr, 1e-9), 0.0)
                img = cyl_to_cart(xh, rim, wth + ang)
                # keep only the part of each image filament that lies along the nacelle
                Ufil -= polyline_influence(Pc, np.where(on_hub[..., None], img, img[:, :1, :]), core_f)
        # bound vortices: own blade (outer edge -> inner edge), optionally other blades
        Pq = geo["Pq_e"]
        Ubnd = np.zeros((Pc.shape[0], self.N, 3))
        blades_b = range(B) if self.wake_settings.other_bound else range(1)
        for k in blades_b:
            pk = rotate_x(Pq, 2.0 * np.pi * k / B)
            segs = np.stack([pk[1:], pk[:-1]], axis=1)            # (N, 2, 3) outer -> inner
            Ubnd += polyline_influence(Pc, segs, core)
        # horseshoe j: filament j (out of the blade) - filament j+1 + bound j
        U = Ufil[:, :-1, :] - Ufil[:, 1:, :] + Ubnd
        ex, et, er = local_frames(Pc)
        Aa = np.einsum("cjk,ck->cj", U, ex)
        At = np.einsum("cjk,ck->cj", U, et)
        Ar = np.einsum("cjk,ck->cj", U, er)

        return Aa, At, Ar, dict(ua0=ua0, ut0=ut0, wake_x=wx, wake_r=wr)

    def _hub_radius_fn(self):
        nac = self.prop.nacelle
        D = self.prop.diameter
        rh = self.prop.hub_radius
        if nac is None:
            return lambda x: np.full_like(np.asarray(x, dtype=float), rh)
        return lambda x: np.asarray(nac.radius(np.asarray(x) / D)) * D

    # ------------------------------------------------------------------ section function
    def _sections(self, geo, ua, ut, V, Omega, atm, u_nac, spill=None, reuse=False):
        """Section circulation for given induced velocities and spilled inflow.

        ``spill`` is the axial velocity removed ahead of each strip by choke, as a fraction of
        V (see ``_newton``); the strip then sees V (1 + u_nac) + u_a - V spill.
        """
        u_spill = np.zeros_like(ua) if spill is None else -V * np.asarray(spill)
        G, st = self._sections_once(geo, ua + u_spill, ut, V, Omega, atm, u_nac, reuse)
        st["u_spill"] = u_spill
        return G, st

    def _normal_plane(self, geo, phi, blade_angle=None):
        """Sweep-normal-plane data of the control sections for relative-flow angles phi, with
        Kuchemann's unsweeping of the isobars near the tip."""
        ctrl = geo["ctrl"]
        beta = ctrl["beta"] if blade_angle is None else blade_angle
        scale = None
        if self.st.kuchemann and self.section_options.kuchemann:
            npl0 = normal_plane(phi, beta, ctrl["t_hat"], geo["sigma"], ctrl["t_c"],
                                ctrl["cl_design"], use_sweep=self.section_options.sweep)
            scale = kuchemann_factor(geo["tip_distance"], npl0.sweep)
        return normal_plane(phi, beta, ctrl["t_hat"], geo["sigma"], ctrl["t_c"], ctrl["cl_design"],
                            sweep_scale=scale, use_sweep=self.section_options.sweep)

    def _relief_wavenumber(self, geo, npl):
        """Spanwise-to-chordwise wavenumber ratio kappa of the perturbation field of each strip.

        A linear disturbance exp(i(k_x x + k_z z)) on a planar sheet decays away from it with
        k_y^2 = (1 - M^2) k_x^2 + k_z^2: it behaves as a 2-D disturbance at the effective Mach
        number M_eff^2 = M^2 - (k_z/k_x)^2.  The blade's sources and vortices end at the free
        tip (the hub is a reflection plane), so a strip a span distance d from the tip carries a
        quarter-wave spanwise mode, k_z = pi / (2 (d + c_n/2)), against the chordwise half wave
        k_x = pi / c_n:  kappa = c_n / (2 d + c_n).  Strip theory takes kappa = 0, which makes
        2-D compressibility singular at M_n = 1; the relief bounds it near a tip and recovers
        the compressible finite-wing lift slope in the lifting line.
        """
        ctrl = geo["ctrl"]
        c_n = ctrl["chord"] * npl.chord_ratio
        d = (self.prop.radius - ctrl["r"]) / np.maximum(npl.t_r, 0.2)
        return self.st.relief_scale * c_n / (2.0 * d + c_n)

    def _sections_once(self, geo, ua, ut, V, Omega, atm, u_nac, reuse=False):
        ctrl = geo["ctrl"]
        r = ctrl["r"]
        T0 = atm.T + V * V / (2.0 * CP_AIR)
        Vx = V * (1.0 + u_nac) + ua
        Vt = Omega * r - ut
        W = np.sqrt(Vx * Vx + Vt * Vt)
        phi = np.arctan2(Vx, Vt)
        T = T0 - (W * W - (Omega * r) ** 2) / (2.0 * CP_AIR)
        T = np.maximum(T, 0.2 * atm.T)
        a = np.sqrt(GAMMA * R_AIR * T)
        M = W / a
        rho = atm.rho * (T / atm.T) ** (1.0 / (GAMMA - 1.0))
        Re = rho * W * ctrl["chord"] / sutherland(T)
        npl = self._normal_plane(geo, phi)
        kappa = self._relief_wavenumber(geo, npl) if self.st.relief_3d else None
        res = self.section.evaluate(npl, M, Re, chord_over_r=ctrl["chord"] / r, reuse_lattice=reuse,
                                    kappa=kappa)
        G = 0.5 * W * ctrl["chord"] * res.cl * npl.gamma_factor
        state = dict(W=W, phi=phi, M=M, rho=rho, Re=Re, T=T, Vx=Vx, Vt=Vt, npl=npl, sec=res)
        return G, state

    # ------------------------------------------------------------------ solve
    def solve(self, op: OperatingPoint, gamma0=None, verbose=False, spill0=None) -> Result:
        t_start = time.time()
        p = self.prop
        D = p.diameter
        atm, V, n = op.resolve(D)
        Omega = 2.0 * np.pi * n
        geo = self._geometry(op.dbeta)
        nacflow = self._nacelle(op.mach, D)
        if nacflow is not None:
            # the section sees the body's velocity field averaged over its chord
            ctrl = geo["ctrl"]
            fr = np.linspace(-0.45, 0.45, 7)
            xs = ctrl["x_mid"][None, :] + fr[:, None] * ctrl["chord"][None, :] * np.sin(ctrl["beta"])[None, :]
            u_nac = nacflow.axial(xs, np.broadcast_to(geo["r"], xs.shape)).mean(axis=0)
        else:
            u_nac = np.zeros(self.N)
        warnings = []
        spill = np.zeros(self.N) if spill0 is None else np.clip(np.asarray(spill0, dtype=float), 0.0, None)
        # initial circulation: section response to the undisturbed inflow, halved
        if gamma0 is None:
            g_free, _ = self._sections(geo, np.zeros(self.N), np.zeros(self.N), V, Omega, atm, u_nac)
            gamma = 0.5 * g_free
        else:
            gamma = np.array(gamma0, dtype=float)
        n_newton_total = 0
        converged = False
        wake_hist = []
        if gamma0 is None:
            # homotopy: converge with attached flow everywhere first, so that the full model
            # starts next to the physical branch instead of wandering into shock stall
            Aa, At, Ar, winfo = self._influence(geo, gamma, V, Omega, op.mach, nacflow)
            self.section.attached_only = True
            try:
                gamma, spill, ok0, nit0 = self._newton(geo, gamma, spill, Aa, At, V, Omega, atm, u_nac)
            finally:
                self.section.attached_only = False
            n_newton_total += nit0
        for it_w in range(self.st.wake_max):
            Aa, At, Ar, winfo = self._influence(geo, gamma, V, Omega, op.mach, nacflow)
            gamma, spill, ok, nit = self._newton(geo, gamma, spill, Aa, At, V, Omega, atm, u_nac)
            n_newton_total += nit
            if not ok:
                warnings.append(f"Newton iteration did not converge in wake pass {it_w}")
            if wake_hist:
                g_prev, s_prev = wake_hist[-1]
                change = max(np.max(np.abs(gamma - g_prev)) / max(np.max(np.abs(gamma)), 1e-12),
                             np.max(np.abs(spill - s_prev)))
            else:
                change = np.inf
            wake_hist.append((gamma.copy(), spill.copy()))
            if verbose:
                print(f"wake pass {it_w}: newton {nit} its, change {change:.2e}, max spill {np.max(spill):.4f}")
            if change < self.st.wake_tol:
                converged = ok
                break
            if it_w > 0:
                w = self.st.wake_relax
                gamma = w * gamma + (1.0 - w) * wake_hist[-2][0]
                spill = w * spill + (1.0 - w) * wake_hist[-2][1]
        else:
            warnings.append("wake geometry iteration did not converge")
        ua = Aa @ gamma
        ut = At @ gamma
        G, s = self._sections(geo, ua, ut, V, Omega, atm, u_nac, spill)
        res = self._assemble(op, geo, gamma, ua, ut, Ar @ gamma, s, atm, V, n, Omega, u_nac, winfo)
        res.converged = converged
        res.iterations = dict(newton=n_newton_total, wake=len(wake_hist), seconds=time.time() - t_start)
        res.warnings = warnings + res.warnings
        return res

    def _newton(self, geo, gamma, spill, Aa, At, V, Omega, atm, u_nac):
        """Newton's method with a backtracking line search for the circulation and the
        choke spillage together.

        Unknowns: the circulation Gamma_i and the spilled inflow s_i (fraction of V) of every
        strip.  Residuals

            R_G = Gamma - G(u_a(Gamma) - V s, u_t(Gamma))
            R_s = phi(s, 1 - chi(u_a(Gamma) - V s, u_t(Gamma)))

        where chi is the passage choke ratio of the strip (inlet mass flux over sonic-throat
        flux) and phi(a, b) = a + b - sqrt(a^2 + b^2 + 2 eps^2) the smoothed Fischer-Burmeister
        function, whose root is a > 0, b > 0, a b = eps^2: a strip either passes all of its
        inflow (s ~ 0, chi < 1) or spills just as much as keeps its throat sonic (chi = 1,
        s > 0), the excess flow going round it.  This complementarity form of the choke limit
        keeps the problem smooth, so Newton converges through the onset of choke.

        The lifting-line operator is stiff (the trailing vortices make the induced velocity a
        hypersingular function of dGamma/dr, and compressible sections have large lift
        slopes), so a plain fixed-point iteration diverges; Newton with the exact Jacobian
        converges quadratically.  The section derivatives are local (diagonal), so the
        Jacobian costs two extra section sweeps.
        """
        N = self.N
        ctrl = geo["ctrl"]
        use_spill = self.st.choke_spill
        eps = self.st.spill_smoothing
        I = np.eye(N)

        def fb(a, b):
            q = np.sqrt(a * a + b * b + 2.0 * eps * eps)
            return a + b - q, 1.0 - a / q, 1.0 - b / q

        def resid(g, sp):
            G, s = self._sections(geo, Aa @ g, At @ g, V, Omega, atm, u_nac, sp)
            Rs = fb(sp, 1.0 - s["sec"].choke_ratio)[0] if use_spill else np.zeros(N)
            return g - G, Rs, G, s

        def norm(Rg, Rs, gscale):
            return float(np.sqrt(np.sum((Rg / gscale) ** 2) + np.sum(Rs ** 2)))

        spill = np.zeros(N) if not use_spill else np.array(spill, dtype=float)
        Rg, Rs, G, s = resid(gamma, spill)
        gscale = max(np.max(np.abs(G)), 1e-9)
        r0 = norm(Rg, Rs, gscale)
        for it in range(self.st.newton_max):
            gscale = max(np.max(np.abs(G)), 1e-9)
            if np.max(np.abs(Rg)) < self.st.newton_tol * gscale and np.max(np.abs(Rs)) < 10.0 * self.st.newton_tol:
                return gamma, spill, True, it
            ua = Aa @ gamma
            ut = At @ gamma
            h = 1e-5 * Omega * ctrl["r"]
            Ga, sa = self._sections(geo, ua + h, ut, V, Omega, atm, u_nac, spill)
            Gt, st_ = self._sections(geo, ua, ut + h, V, Omega, atm, u_nac, spill)
            dGa = (Ga - G) / h
            dGt = (Gt - G) / h
            J11 = I - dGa[:, None] * Aa - dGt[:, None] * At
            if use_spill:
                chi = s["sec"].choke_ratio
                dXa = (sa["sec"].choke_ratio - chi) / h
                dXt = (st_["sec"].choke_ratio - chi) / h
                _, fa, fbb = fb(spill, 1.0 - chi)
                J12 = np.diag(V * dGa)
                J21 = -(fbb * dXa)[:, None] * Aa - (fbb * dXt)[:, None] * At
                J22 = np.diag(fa + fbb * dXa * V)
                Jm = np.block([[J11, J12], [J21, J22]])
                rhs = np.concatenate([Rg, Rs])
            else:
                Jm, rhs = J11, Rg
            try:
                d = -np.linalg.solve(Jm, rhs)
            except np.linalg.LinAlgError:
                d = -rhs
            dg = d[:N]
            ds = d[N:] if use_spill else np.zeros(N)
            # trust region: no angle of attack moves by more than max_dalpha in one step
            W = s["W"]
            dux = Aa @ dg - V * ds
            dalpha = np.abs((dux * np.cos(s["phi"]) + (At @ dg) * np.sin(s["phi"])) / W)
            lim = min(1.0, np.radians(self.st.max_dalpha_deg) / max(np.max(dalpha), 1e-12))
            if use_spill:
                lim = min(lim, 0.1 / max(np.max(np.abs(ds)), 1e-12))
            dg, ds = dg * lim, ds * lim
            # backtracking line search on |R|; if no step decreases it, keep the best one
            best = None
            for step in (1.0, 0.5, 0.25, 0.125, 0.0625, 0.03):
                g_try = gamma + step * dg
                s_try = np.clip(spill + step * ds, -0.02, self.st.spill_max) if use_spill else spill
                R2g, R2s, G2, s2 = resid(g_try, s_try)
                n2 = norm(R2g, R2s, gscale)
                if best is None or n2 < best[0]:
                    best = (n2, g_try, s_try, R2g, R2s, G2, s2)
                if n2 < (1.0 - 1e-4 * step) * r0:
                    break
            r0, gamma, spill, Rg, Rs, G, s = best
        gscale = max(np.max(np.abs(G)), 1e-9)
        ok = bool(np.max(np.abs(Rg)) < 1e-3 * gscale and np.max(np.abs(Rs)) < 1e-3)
        return gamma, spill, ok, self.st.newton_max

    # ------------------------------------------------------------------ results
    def _assemble(self, op, geo, gamma, ua, ut, ur, s, atm, V, n, Omega, u_nac, winfo):
        p = self.prop
        B = p.blades
        D = p.diameter
        ctrl = geo["ctrl"]
        r = ctrl["r"]
        c = ctrl["chord"]
        dr = geo["dr"]
        sec = s["sec"]
        W, phi, rho = s["W"], s["phi"], s["rho"]
        q = 0.5 * rho * W * W * c
        L = q * sec.cl
        Dg = q * sec.cd
        cphi, sphi = np.cos(phi), np.sin(phi)
        dT = B * (L * cphi - Dg * sphi)
        dQ = B * (L * sphi + Dg * cphi) * r
        T = float(np.sum(dT * dr))
        Q = float(np.sum(dQ * dr))
        P = Omega * Q
        rho_inf = atm.rho
        CT = T / (rho_inf * n ** 2 * D ** 4)
        CQ = Q / (rho_inf * n ** 2 * D ** 5)
        CP = P / (rho_inf * n ** 3 * D ** 5)
        J = V / (n * D)
        eta_blade = T * V / P if P > 0 else float("nan")
        # loss decomposition (exact identity: P - T V = sum of the terms)
        lever = (Omega * r * cphi + V * sphi)
        l_ax = B * L * (Omega * r * ua) / W
        l_sw = B * L * (V * ut) / W
        l_nac = B * L * (Omega * r * V * u_nac) / W
        u_sp = s.get("u_spill", np.zeros_like(r))
        l_spill = B * L * (Omega * r * u_sp) / W           # interaction with the spilled inflow (<= 0)
        def dloss(cd):
            return B * q * cd * lever
        parts = {
            "induced_axial": l_ax, "induced_swirl": l_sw, "nacelle_interaction": l_nac,
            "spill_interaction": l_spill,
            "profile": dloss(sec.cd_profile), "wave": dloss(sec.cd_wave),
            "separation_le": dloss(sec.cd_sep), "choke": dloss(sec.cd_choke),
        }
        losses = {k: float(np.sum(v * dr) / P) if P > 0 else float("nan") for k, v in parts.items()}
        # the blockage that spills the flow raises the pressure on the forebody: charge the
        # interaction gain back as spillage drag, so a choked root earns nothing from it
        D_spill = -float(np.sum(l_spill * dr)) / max(V, 1e-9)
        losses["spill_drag"] = D_spill * V / P if P > 0 else float("nan")
        # the potential flow of the body does no net work: the work the blades do against the
        # body's velocity field returns as the pressure force the propeller field exerts on the
        # body (thrust on the nose for an accelerating spinner, drag on an area-ruled waist).
        # Net (system) thrust counts it, so only the real benefit of a spinner remains - its
        # effect on the blade-root Mach number and loading.
        T_body = float(np.sum(l_nac * dr)) / max(V, 1e-9)
        losses["nacelle_reaction"] = -T_body * V / P if P > 0 else float("nan")
        losses["total"] = float(sum(losses.values()))
        tip_speed = Omega * p.radius
        npl = s["npl"]
        radial = dict(
            r_R=r / p.radius, gamma=gamma, chord=c, dT_dr=dT, dQ_dr=dQ, ua=ua, ut=ut, ur=ur,
            u_nacelle=u_nac, W=W, phi_deg=np.degrees(phi), alpha_deg=np.degrees(ctrl["beta"] - phi),
            alpha_n_deg=np.degrees(npl.alpha_n), mach=s["M"], mach_n=sec.mach_n, reynolds=s["Re"],
            sweep_deg=np.degrees(npl.sweep), sigma=geo["sigma"], sigma_n=npl.sigma_n,
            xi_n_deg=np.degrees(npl.xi_n), k_lattice=sec.k_lattice, cl=sec.cl, cd=sec.cd,
            cl_n=sec.cl_n, cd_profile=sec.cd_profile, cd_wave=sec.cd_wave, cd_sep=sec.cd_sep,
            cd_choke=sec.cd_choke, mach_peak_upper=sec.mach_peak_upper, mach_peak_lower=sec.mach_peak_lower,
            choke_ratio=sec.choke_ratio, f_attached=sec.f_attached, x_tr_upper=sec.x_tr[:, 0],
            x_tr_lower=sec.x_tr[:, 1], beta_deg=np.degrees(ctrl["beta"]), t_c=ctrl["t_c"],
            ua0_wake=winfo["ua0"], ut0_wake=winfo["ut0"], u_spill=u_sp,
            le_singularity=sec.extras["A0"], le_suction_ratio=sec.extras["eta_le"],
            cd_le=sec.extras["cd_le"])
        T_blade = T
        T = T - D_spill + T_body            # net thrust: blades, spillage drag, body reaction
        CT = T / (rho_inf * n ** 2 * D ** 4)
        eta = T * V / P if P > 0 else float("nan")
        warnings = []
        if np.any(u_sp < -1e-2 * V):
            warnings.append(f"choked strips spill flow at r/R = {np.round(r[u_sp < -1e-2 * V] / p.radius, 3).tolist()}")
        if np.any(sec.choke_ratio > 1.0):
            warnings.append(f"passage choke at r/R = {np.round(r[sec.choke_ratio > 1.0] / p.radius, 3).tolist()}")
        if np.any(sec.f_attached < 0.7):
            warnings.append(f"separated sections at r/R = {np.round(r[sec.f_attached < 0.7] / p.radius, 3).tolist()}")
        if np.any(sec.extras["mach_n_eff"] > self.section_options.mach_a):
            warnings.append("normal Mach number above the subsonic model range at some stations")
        op_d = dict(mach=op.mach, altitude=op.altitude, V=V, rpm=60.0 * n, tip_speed=tip_speed,
                    thrust_blade=T_blade, eta_blade=eta_blade, thrust_body=T_body, drag_spill=D_spill,
                    helical_tip_mach=math.hypot(V, tip_speed) / atm.a, T=atm.T, p=atm.p, rho=atm.rho,
                    a=atm.a, dbeta=op.dbeta)
        return Result(op=op_d, CT=CT, CP=CP, CQ=CQ, eta=eta, J=J, thrust=T, power=P, torque=Q,
                      dbeta=op.dbeta, beta_ref=p.beta_ref(op.dbeta), losses=losses, radial=radial,
                      converged=False, iterations={}, warnings=warnings)

    # ------------------------------------------------------------------ prescribed power
    def _pitch_estimate(self, op, CP=None, CT=None, alpha75_deg=3.0):
        """Starting collective pitch: actuator-disk inflow at the target loading (efficiency 0.8
        assumed for a power target) and a moderate incidence at 0.75 R - on the attached side."""
        D = self.prop.diameter
        atm, V, n = op.resolve(D)
        J = V / (n * D)
        ct = CT if CT is not None else 0.8 * CP / max(J, 1e-3)
        a = 0.5 * (np.sqrt(1.0 + 8.0 * max(ct, 0.0) / (np.pi * max(J, 1e-3) ** 2)) - 1.0)
        phi75 = np.degrees(np.arctan(J * (1.0 + a) / (0.75 * np.pi)))
        return float(phi75 + alpha75_deg - self.prop.beta_ref(0.0))

    def solve_for(self, op: OperatingPoint, CP=None, CT=None, dbeta0=None, tol=1e-5, max_iter=30,
                  verbose=False) -> Result:
        """Adjust the collective pitch to reach a power (or thrust) coefficient.

        Near stall the propeller has two solutions at one power: attached, and stalled at a
        higher pitch (the drag absorbs the power).  The pitch is therefore approached from
        the attached side, as a governor does: first a pitch below the target on the attached
        branch is found (lowering the pitch from ``dbeta0``), then the target is bracketed
        and found by Illinois regula falsi, each solution continued from the attached end of
        the bracket.
        """
        if (CP is None) == (CT is None):
            raise ValueError("give exactly one of CP or CT")
        target = CP if CP is not None else CT
        key = "CP" if CP is not None else "CT"
        x0 = self._pitch_estimate(op, CP, CT) if dbeta0 is None else dbeta0
        n_eval = [0]

        def run(db, prev=None):
            n_eval[0] += 1
            o = OperatingPoint(**{**op.__dict__, "dbeta": db})
            if prev is None:
                r = self.solve(o)
            else:
                r = self.solve(o, gamma0=prev.radial["gamma"], spill0=-prev.radial["u_spill"] / prev.op["V"])
            if verbose:
                print(f"pitch {db:+.4f}: {key} {getattr(r, key):.5f}  stalled {_stalled(r)}")
            return r

        def val(r):
            return getattr(r, key) - target

        # 1. a pitch below the target, on the attached branch
        x, r = x0, run(x0)
        lo = hi = None
        for _ in range(12):
            if val(r) < 0.0 and not _stalled(r):
                lo = (x, val(r), r)
                break
            if val(r) > 0.0 and (hi is None or x < hi[0]):
                hi = (x, val(r), r)
            x -= 3.0
            r = run(x)
        if lo is None:
            r.warnings.append(f"pitch iteration for {key}: no attached solution below the target")
            return r
        # 2. a pitch above the target
        if hi is None:
            x, prev = lo[0], lo[2]
            for _ in range(15):
                x += 2.0
                r = run(x, prev)
                if val(r) > 0.0:
                    hi = (x, val(r), r)
                    break
                lo, prev = (x, val(r), r), r
            if hi is None:
                r.warnings.append(f"pitch iteration for {key}: target not reached")
                return r
        # 3. Illinois regula falsi inside the bracket
        best = lo if abs(lo[1]) < abs(hi[1]) else hi
        side = 0
        for _ in range(max_iter):
            if abs(best[1]) < tol * max(abs(target), 1e-3):
                return best[2]
            (xa, fa, ra), (xb, fb, rb) = lo, hi
            xm = (xa * fb - xb * fa) / (fb - fa)
            xm = min(max(xm, xa + 1e-3 * (xb - xa)), xb - 1e-3 * (xb - xa))
            rm = run(xm, ra)
            fm = val(rm)
            if abs(fm) < abs(best[1]):
                best = (xm, fm, rm)
            if fm < 0.0:
                lo = (xm, fm, rm)
                if side == -1:
                    hi = (hi[0], 0.5 * hi[1], hi[2])
                side = -1
            else:
                hi = (xm, fm, rm)
                if side == 1:
                    lo = (lo[0], 0.5 * lo[1], lo[2])
                side = 1
            if abs(hi[0] - lo[0]) < 1e-7:
                break
        best[2].warnings.append(f"pitch iteration for {key} did not converge")
        return best[2]


def _stalled(r, limit=0.3):
    """True when more than ``limit`` of the blade (by |thrust|) is separated (f < 0.5)."""
    f = r.radial["f_attached"]
    w = np.abs(r.radial["dT_dr"]) * r.radial["chord"]
    return bool(np.sum(w * (f < 0.5)) > limit * max(np.sum(w), 1e-12))


def _swap(xt, r):
    x, th = xt
    return x, r, th
