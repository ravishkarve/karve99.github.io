"""Blade-element aerodynamics: the compressible, swept, high-solidity blade row.

A blade element at radius r is treated as one blade of an infinite row (the B blades cut by
the cylinder r = const), seen in the plane normal to its sweep, at the local relative Mach
number.  All quantities are arrays over the radial stations.

Chain of models
---------------
1. **Independence principle.**  The span direction t of the mid-chord line and the local
   relative velocity W give the sweep, sin(Lambda) = t.W/|W|.  The flow normal to t is a
   two-dimensional row with Mach number M cos(Lambda), thicker and more cambered sections
   (t/c and cl_d divided by c_n/c) and a solidity and stagger obtained by projecting the
   chord and the pitch vector on the normal plane.  Kuchemann's effective sweep removes the
   sweep near the tip, where the isobars unsweep.
2. **Compressible row** (:mod:`hsprop.cascade`): exact linear row theory in the
   Prandtl-Glauert-mapped lattice; lift on the vector-mean velocity.
3. **Surface Mach numbers**: Lighthill's leading-edge factor and the Karman-Tsien rule on the
   mapped-lattice pressure coefficient; the peak Mach number on each surface.
4. **Boundary layer** (:mod:`hsprop.boundary_layer`) on the streamwise edge speed
   sqrt(cos^2 L q_n^2 + sin^2 L): profile drag (Squire-Young), a displacement lift loss and
   the turbulent separation point.
5. **Shock losses**: the entropy rise of the weak shock that ends a supersonic region grows
   as (M - 1)^3 and the mass flow through it as the size of the region, so the wave drag is
   charged as cd_w = K_w int (M_loc - 1)^3 dx over the supersonic part of each surface.  As
   the free-stream Mach number passes the (computed, not correlated) critical value both the
   strength and the extent grow linearly, which reproduces Lock's fourth-power law; a thin
   leading-edge spike, on the other hand, costs little.  Above the normal Mach number M_a
   the subsonic model is frozen and blended into Ackeret's supersonic theory by M_b.
6. **Passage choke** for dense rows: the throat between the suction surface of one blade and
   the pressure surface of the next is found geometrically; when the inlet mass flux exceeds
   the sonic throat flux, the total-pressure loss that passes the flow is charged as drag.
7. **Separation**: Kirchhoff's lift law with the attached fraction f from the boundary layer,
   reduced further by shock-induced separation when the peak Mach exceeds M_ss.

Lift and drag coefficients returned are on the local relative dynamic pressure and the
cylindrical (streamwise) chord, per unit radius, ready for the blade-element sums.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import airfoil
from .boundary_layer import march
from .cascade import ThinCascade, get_table, solve_tabulated
from .gas import (GAMMA, PHI_STAR, cp_from_speed_ratio, mach_from_cp, mass_flux_function,
                  normal_shock_p0_ratio, speed_ratio_from_cp)

M_CAP = 1.75     # bound on local Mach numbers from linear theory + Karman-Tsien


@dataclass
class SectionOptions:
    """Switches and constants of the blade-element model."""

    cascade: bool = True            # blade-to-blade interference (False: isolated aerofoils)
    lattice_map: bool = True        # Prandtl-Glauert map of the lattice (False: physical lattice / beta)
    sweep: bool = True              # independence principle (False: cylindrical sections)
    kuchemann: bool = True          # tip unsweeping of the isobars
    karman_tsien: bool = True       # non-linear compressibility of surface speeds and lift
    viscous: bool = True            # boundary layer, profile drag and viscous lift loss
    transonic: bool = True          # shock losses and shock-induced separation
    choke: bool = True              # passage choke of dense rows
    xtr_upper: float = 0.05         # forced transition x/c; the default trips the layer near the
    xtr_lower: float = 0.05         # leading edge, as on swept rotating blades (1 = free, Michel)
    k_visc: float = 8.0             # lift loss per unit trailing-edge displacement thickness
    k_wave: float = 6.0             # shock-loss constant in cd_w = K int ln(p01/p02)(M) dx per surface
    mach_shock_sep: float = 1.30    # shock Mach number at which shock-induced separation starts
    dmach_shock_sep: float = 0.35   # ... and the range over which the attached fraction falls to 0
    pocket_ref: float = 0.2         # chord length that turns int (M-1)^3 dx into a shock Mach number
    f_shock_min: float = 0.4        # attached fraction left by fully developed shock-induced separation
    le_suction: bool = True         # attainable leading-edge suction (bubble / shock at the nose)
    mach_lim: float = 1.45          # largest local Mach number a nose can sustain
    cp_lim0: float = -7.0           # most negative nose pressure coefficient at low speed
    eta_burst: float = 0.25         # attainable/theoretical suction at which the bubble bursts
    eta_width: float = 0.25         # ... range of the leading-edge stall
    f_le_min: float = 0.0           # attached fraction left by leading-edge stall (thick sections)
    tc_thin: float = 0.06           # normal-plane t/c below which a burst bubble becomes a long
    tc_thick: float = 0.09          # bubble (thin-aerofoil stall), above which it stalls the nose
    a0_long_bubble: float = 0.085   # leading-edge loading A0/beta at which a thin section's long
    da0_long_bubble: float = 0.20   # bubble starts to decamber it, and the range to full stall
    f_thin_stall_min: float = 0.10  # attached fraction left after thin-aerofoil stall
    vortex_sweep: tuple = (10.0, 40.0)  # sweep [deg] over which a stable leading-edge vortex forms
    a0_vortex_burst: float = 0.25   # leading-edge loading at which the swept-edge vortex bursts
    vortex_lift: bool = True        # Polhamus suction analogy on swept edges
    mach_a: float = 0.90            # subsonic model frozen above this normal Mach number
    mach_b: float = 1.15            # supersonic linear theory from this normal Mach number
    choke_relief: float = 0.0       # fractional 3-D relief of the passage throat
    h_sep: float = 2.6              # turbulent separation shape factor
    stall_delay: bool = False       # rotational augmentation (Snel) of separated lift
    tabulated: bool = True         # interpolate a precomputed lattice table (fast) or solve directly
    n_modes: int = 16
    n_quad: int = 64
    n_surface: int = 81


@dataclass
class NormalPlane:
    """Blade element seen in the plane normal to its (effective) sweep."""

    sweep: np.ndarray         # effective sweep Lambda [rad]
    alpha_n: np.ndarray       # angle of attack in the normal plane [rad]
    sigma_n: np.ndarray       # solidity c_n / s_n
    xi_n: np.ndarray          # stagger of linear theory [rad]
    tau_n: np.ndarray         # thickness ratio
    cld_n: np.ndarray         # design lift coefficient (camber)
    chord_ratio: np.ndarray   # c_n / c
    area_factor: np.ndarray   # (c_n / c) / t_r  (blade area per unit radius over c)
    gamma_factor: np.ndarray  # Gamma = 0.5 W c CL * gamma_factor
    t_r: np.ndarray           # radial component of the span tangent

    @classmethod
    def plain(cls, alpha, sigma, xi, tau, cld, sweep=0.0):
        """A row given directly in its normal plane (for section-level studies)."""
        b = np.broadcast_arrays(*[np.atleast_1d(np.asarray(v, dtype=float))
                                  for v in (alpha, sigma, xi, tau, cld, sweep)])
        one = np.ones_like(b[0])
        cs = np.cos(b[5])
        return cls(sweep=b[5], alpha_n=b[0], sigma_n=b[1], xi_n=b[2], tau_n=b[3], cld_n=b[4],
                   chord_ratio=one, area_factor=one / np.maximum(cs, 1e-3) * cs,
                   gamma_factor=one, t_r=one)


def kuchemann_factor(distance_in_chords, sweep):
    """Fraction of the geometric sweep felt by the isobars at a given distance (in local
    chords) from a free tip or a kink: 1 - [sqrt(1 + (2 pi d / L)^2) - 2 pi d / L]."""
    L = np.maximum(np.abs(np.asarray(sweep, dtype=float)), 1e-3)
    z = 2.0 * np.pi * np.maximum(np.asarray(distance_in_chords, dtype=float), 0.0) / L
    return 1.0 - (np.sqrt(1.0 + z * z) - z)


def normal_plane(phi, blade_angle, t_hat, sigma, tc, cld, sweep_scale=None, use_sweep=True):
    """Map cylindrical blade elements to the sweep-normal plane.

    phi, blade_angle : relative-flow and chord angles from the plane of rotation [rad]
    t_hat            : (S, 3) unit span tangent in local (axial, tangential, radial) components,
                       tangential positive in the direction of rotation
    sigma            : cylindrical solidity B c / (2 pi r)
    sweep_scale      : optional factor (0..1) on sin(Lambda), e.g. Kuchemann's
    """
    phi = np.asarray(phi, dtype=float)
    S = phi.size
    ew = np.stack([np.sin(phi), -np.cos(phi), np.zeros(S)], axis=1)
    ec = np.stack([np.sin(blade_angle), -np.cos(blade_angle), np.zeros(S)], axis=1)
    et = np.array([0.0, 1.0, 0.0])
    t = np.asarray(t_hat, dtype=float).reshape(S, 3)
    if not use_sweep:
        t = np.tile([0.0, 0.0, 1.0], (S, 1))
    sl = np.einsum("si,si->s", t, ew)
    if sweep_scale is not None:
        t = t - ((1.0 - np.asarray(sweep_scale)) * sl)[:, None] * ew
        t = t / np.linalg.norm(t, axis=1)[:, None]
        sl = np.einsum("si,si->s", t, ew)
    sl = np.clip(sl, -0.999, 0.999)
    cl_ = np.sqrt(1.0 - sl * sl)
    wn = (ew - sl[:, None] * t) / cl_[:, None]
    ln = np.cross(wn, t)                                    # lift-positive normal
    cvec = ec - np.einsum("si,si->s", ec, t)[:, None] * t
    cn = np.linalg.norm(cvec, axis=1)
    chat = cvec / cn[:, None]
    p = et[None, :] - t[:, 1:2] * t
    pn = np.linalg.norm(p, axis=1)
    a = np.einsum("si,si->s", p, wn)
    b = np.einsum("si,si->s", p, ln)
    flip = b < 0.0
    a = np.where(flip, -a, a)
    b = np.where(flip, -b, b)
    xi_n = np.arctan2(a, b)
    alpha_n = np.arctan2(np.einsum("si,si->s", np.cross(wn, chat), t), np.einsum("si,si->s", wn, chat))
    t_r = np.maximum(t[:, 2], 1e-3)
    return NormalPlane(sweep=np.arcsin(sl), alpha_n=alpha_n, sigma_n=np.asarray(sigma) * cn / pn,
                       xi_n=xi_n, tau_n=np.asarray(tc) / cn, cld_n=np.asarray(cld) / cn,
                       chord_ratio=cn, area_factor=cn / t_r, gamma_factor=t_r / cl_, t_r=t_r)


@dataclass
class SectionResult:
    cl: np.ndarray            # lift coefficient (local W, cylindrical chord, per unit radius)
    cd: np.ndarray            # drag coefficient, total
    cd_profile: np.ndarray    # boundary-layer (Squire-Young) part
    cd_wave: np.ndarray       # shock part
    cd_choke: np.ndarray      # passage-choke part
    cd_sep: np.ndarray        # separation (lost suction) part
    cl_n: np.ndarray          # normal-plane lift coefficient
    cl_inviscid_n: np.ndarray
    mach_n: np.ndarray
    mach_peak_upper: np.ndarray
    mach_peak_lower: np.ndarray
    choke_ratio: np.ndarray   # inlet mass flux / sonic throat flux (>1: choked)
    k_lattice: np.ndarray     # lift-slope factor of the row relative to the isolated aerofoil
    x_tr: np.ndarray          # (S, 2) transition upper/lower
    x_sep: np.ndarray         # (S, 2) separation upper/lower
    f_attached: np.ndarray
    extras: dict = field(default_factory=dict)


def _cap_mach(m):
    """Identity below 1.25, smooth saturation towards M_CAP above."""
    knee = 1.25
    span = M_CAP - knee
    return np.where(m <= knee, m, knee + span * np.tanh((m - knee) / span))


def cp_from_mach(m_local, mach, gamma=GAMMA):
    """Isentropic pressure coefficient for a local Mach number."""
    mach = np.maximum(np.asarray(mach, dtype=float), 1e-6)
    t_inf = 1.0 + 0.5 * (gamma - 1.0) * mach ** 2
    t_loc = 1.0 + 0.5 * (gamma - 1.0) * np.asarray(m_local, dtype=float) ** 2
    p_ratio = (t_inf / t_loc) ** (gamma / (gamma - 1.0))
    return (p_ratio - 1.0) / (0.5 * gamma * mach ** 2)


def _smax(a, b, eps):
    """Smooth maximum of a and b (width eps)."""
    d = a - b
    return b + 0.5 * (d + np.sqrt(d * d + eps * eps))


def _smin(a, b, eps):
    """Smooth minimum of a and b (width eps)."""
    d = a - b
    return b + 0.5 * (d - np.sqrt(d * d + eps * eps))


def _smoothstep(z):
    z = np.clip(z, 0.0, 1.0)
    return z * z * (3.0 - 2.0 * z)


class SectionModel:
    """Vectorised blade-element model for a fixed set of section shapes."""

    def __init__(self, thickness_forms, mean_lines, options: SectionOptions | None = None):
        self.opt = options or SectionOptions()
        o = self.opt
        self.cascade = ThinCascade(o.n_modes, o.n_quad, o.n_surface)
        self.shapes = self.cascade.shape_terms(thickness_forms, mean_lines)
        self.forms = list(thickness_forms)
        self.means = list(mean_lines)
        self._keys = list(zip(self.forms, self.means))
        self.S = len(self.forms)
        xe = self.cascade.xe
        self.x_bl = np.concatenate([[0.0], xe])
        # Ackeret integrals of the squared slopes (thickness from the nose radius onwards)
        xs = np.linspace(0.0, 1.0, 2001)[1:-1]
        self._int_eta2 = np.array([np.trapezoid(airfoil.mean_line_slope(xs, m) ** 2, xs) for m in self.means])
        self._int_yt2 = []
        for f in self.forms:
            yt_s = airfoil.half_thickness_slope_times_sqrt(xs, f) / np.sqrt(xs)
            self._int_yt2.append(np.trapezoid(np.where(xs > 2e-3, yt_s ** 2, 0.0), xs))
        self._int_yt2 = np.array(self._int_yt2)
        self._lattice_cache = None
        self.attached_only = False      # homotopy start of the propeller solver

    # ------------------------------------------------------------------
    def lattice(self, sigma_n, xi_n, beta, reuse=False):
        """Linear row solution (optionally reusing the last one, for Jacobians)."""
        if reuse and self._lattice_cache is not None:
            return self._lattice_cache
        o = self.opt
        sig = np.asarray(sigma_n, dtype=float) if o.cascade else np.zeros(self.S)
        beta_map = beta if o.lattice_map else np.ones(self.S)
        if o.tabulated:
            tables = {k: get_table(self.cascade, *k) for k in set(self._keys)}
            sol = solve_tabulated(tables, self._keys, sig, xi_n, beta_map)
        else:
            sol = self.cascade.solve(sig, xi_n, beta_map, self.shapes)
        self._lattice_cache = sol
        return sol

    # ------------------------------------------------------------------
    def evaluate(self, npl: NormalPlane, mach, reynolds, chord_over_r=None, reuse_lattice=False,
                 kappa=None):
        """Lift and drag of all stations.

        mach      : relative Mach number of the vector-mean velocity
        reynolds  : Reynolds number on W and the cylindrical chord
        kappa     : optional spanwise-to-chordwise wavenumber ratio of the chord-scale
                    perturbation field (3-D transonic relief): chord-scale disturbances behave as
                    in a 2-D flow at the effective normal Mach number sqrt(M_n^2 - kappa^2),
                    while the leading-edge region (disturbance scale ~ x) keeps the actual one
        """
        o = self.opt
        S = self.S
        mach = np.asarray(mach, dtype=float)
        sweep = npl.sweep
        cL, sL = np.cos(sweep), np.sin(sweep)
        Mn_act = mach * cL
        M_act = _smin(Mn_act, o.mach_a, 0.01)               # actual normal Mach number
        beta_act = np.sqrt(1.0 - M_act ** 2)
        if kappa is not None:
            kappa = np.asarray(kappa, dtype=float)
            Mn = np.sqrt(np.maximum(Mn_act * Mn_act - kappa ** 2, 0.0) + 1e-6)
        else:
            kappa = np.zeros(S)
            Mn = Mn_act
        M_sub = _smin(Mn, o.mach_a, 0.01)                   # effective (relieved) Mach number
        beta = np.sqrt(1.0 - M_sub ** 2)
        sol = self.lattice(npl.sigma_n, npl.xi_n, beta, reuse=reuse_lattice)
        comps = np.stack([npl.alpha_n, npl.cld_n, npl.tau_n], axis=1)          # (S, 3)
        cl_inc = np.einsum("sc,sc->s", sol.cl_unit, comps)
        cl_pg = cl_inc / beta
        k_lat = sol.cl_unit[:, 0] / (2.0 * np.pi)

        # ---------------- surface speeds and Mach numbers (normal plane)
        sh = self.shapes
        xe = self.cascade.xe
        du_sym = npl.tau_n[:, None] * sh.u_thick_e + np.einsum("sec,sc->se", sol.u_img_e, comps)
        hg = np.einsum("sec,sc->se", sol.halfgam_e, comps)
        rle = sh.rle * npl.tau_n ** 2
        fle = np.sqrt(xe[None, :] / (xe[None, :] + 0.5 * rle[:, None]))
        q0u = (1.0 + du_sym + hg) * fle
        q0l = (1.0 + du_sym - hg) * fle
        cp0u, cp0l = 1.0 - q0u ** 2, 1.0 - q0l ** 2
        # local compressibility factor along the chord: a disturbance of chordwise scale l
        # is relieved by kappa (c/l)... the chord-scale field by the full kappa, the leading-edge
        # region (scale ~ 2x) hardly at all
        kx = kappa[:, None] * np.minimum(2.0 * xe[None, :], 1.0)
        b = np.minimum(np.sqrt(beta_act[:, None] ** 2 + kx ** 2), np.maximum(beta[:, None], beta_act[:, None]))
        m2 = 1.0 - b * b
        if o.karman_tsien:
            def kt(cp0):
                den = b + m2 / (1.0 + b) * 0.5 * cp0
                return cp0 / _smax(den, 0.2 * b, 0.02)
            cpu_th, cpl_th = kt(cp0u), kt(cp0l)
        else:
            cpu_th, cpl_th = cp0u / b, cp0l / b

        # ---------------- attainable leading-edge suction
        # The suction the nose can carry is limited (a bubble at low speed, a shock above
        # M_lim); the theoretical LE thrust 2 pi A0^2 / beta is then only partly realised and
        # the rest appears as drag (Polhamus/Carlson).  A bubble that must recover too much
        # bursts: leading-edge stall.
        cp_lim = np.maximum(cp_from_mach(o.mach_lim, M_act), o.cp_lim0)
        # theoretical nose suction from linear (Prandtl-Glauert) theory, as in Carlson's method;
        # the nose is a local feature and keeps the actual compressibility
        cpk_u = cp0u.min(axis=1) / beta_act
        cpk_l = cp0l.min(axis=1) / beta_act
        eta_u = np.where(cpk_u < cp_lim, cp_lim / np.minimum(cpk_u, -1e-9), 1.0)
        eta_l = np.where(cpk_l < cp_lim, cp_lim / np.minimum(cpk_l, -1e-9), 1.0)
        A0 = np.einsum("sc,sc->s", sol.A[:, 0, :], comps)
        spike_upper = A0 >= 0.0
        eta_spike = np.where(spike_upper, eta_u, eta_l)
        cs_th = 2.0 * np.pi * A0 ** 2 / beta_act
        cd_le = (1.0 - eta_spike) * cs_th if o.le_suction else np.zeros(S)
        # bubble bursting is a low-speed mechanism: it is judged against the bubble limit
        # cp_lim0 only; at high subsonic speed the suction deficit is a shock loss, and
        # shock-induced separation is judged from the shock strength below
        cpk_spike = np.where(spike_upper, cpk_u, cpk_l)
        eta_bubble = np.where(cpk_spike < o.cp_lim0, o.cp_lim0 / np.minimum(cpk_spike, -1e-9), 1.0)
        cpu = _smax(cpu_th, cp_lim[:, None], 0.05)
        cpl = _smax(cpl_th, cp_lim[:, None], 0.05)
        mloc_u = mach_from_cp(cpu, M_act[:, None])
        mloc_l = mach_from_cp(cpl, M_act[:, None])
        away = (xe > 0.03)[None, :]
        dcl_kt = np.trapezoid(np.where(away, (cpl - cpu) - (cp0l - cp0u) / b, 0.0), xe, axis=1)
        cap = 0.35 * np.sqrt(cl_pg ** 2 + 1e-4) + 0.02
        dcl_kt = cap * np.tanh(dcl_kt / cap)
        mpk_u = mloc_u.max(axis=1)
        mpk_l = mloc_l.max(axis=1)
        # shock-loss measure: integral of (M - 1)^3 over each supersonic region, and the
        # equivalent shock Mach number of the region (a thin spike counts for little)
        sup3_u = np.trapezoid(np.maximum(mloc_u - 1.0, 0.0) ** 3, xe, axis=1)
        sup3_l = np.trapezoid(np.maximum(mloc_l - 1.0, 0.0) ** 3, xe, axis=1)
        # entropy rise of a normal shock at the local Mach number, ln(p01/p02); it equals
        # (M - 1)^3 near M = 1.15 and grows more slowly for strong shocks
        sloss_u = np.trapezoid(-np.log(normal_shock_p0_ratio(mloc_u)), xe, axis=1)
        sloss_l = np.trapezoid(-np.log(normal_shock_p0_ratio(mloc_l)), xe, axis=1)
        meff_u = 1.0 + np.cbrt(sup3_u / o.pocket_ref)
        meff_l = 1.0 + np.cbrt(sup3_l / o.pocket_ref)
        cl_inv = cl_pg + dcl_kt

        # ---------------- boundary layer
        if o.viscous:
            # signed edge speeds: off the ideal incidence the stagnation point sits on one
            # surface just behind the nose, and the stretch between the nose and it belongs to
            # the other surface; a soft floor at zero starts the layer at the stagnation point
            def soft_on(q0):
                return 0.5 * (1.0 + np.tanh(q0 / 0.02))
            qn_u = speed_ratio_from_cp(cpu, M_act[:, None]) * soft_on(q0u)
            qn_l = speed_ratio_from_cp(cpl, M_act[:, None]) * soft_on(q0l)
            te0, te1 = 0.92, 0.85
            i0 = int(np.searchsorted(xe, te0))
            i1 = int(np.searchsorted(xe, te1))

            def stream(qn):
                # linear theory has a log singularity at a trailing edge of finite angle; the
                # viscous flow does not see it, so the edge speed is extrapolated linearly
                # over the last 8 % of chord (as in pymises)
                qn = qn.copy()
                slope = (qn[:, i0] - qn[:, i1]) / (xe[i0] - xe[i1])
                qn[:, i0:] = qn[:, i0:i0 + 1] + slope[:, None] * (xe[None, i0:] - xe[i0])
                qs = np.sqrt((cL[:, None] * qn) ** 2 + (sL[:, None]) ** 2)
                return np.concatenate([np.maximum(np.abs(sL), 1e-4)[:, None], qs], axis=1)
            ue = np.concatenate([stream(qn_u), stream(qn_l)], axis=0)
            me = np.concatenate([mach[:, None] * ue[:S], mach[:, None] * ue[S:]], axis=0)
            Re2 = np.concatenate([reynolds, reynolds])
            xtr = np.concatenate([np.full(S, o.xtr_upper), np.full(S, o.xtr_lower)])
            self._last_bl = (self.x_bl, ue, Re2, me, xtr)
            bl = march(self.x_bl, ue, Re2, me, xtr_forced=xtr, h_sep=o.h_sep)
            cd_prof = bl.cd[:S] + bl.cd[S:]
            dstar = bl.dstar_te[:S] + bl.dstar_te[S:]
            x_tr = np.stack([bl.x_tr[:S], bl.x_tr[S:]], axis=1)
            x_sep = np.stack([bl.x_sep[:S], bl.x_sep[S:]], axis=1)
            visc = np.clip(1.0 - o.k_visc * dstar, 0.5, 1.0)
            cf_share = np.where(cd_prof > 0, (bl.cf_mean[:S] + bl.cf_mean[S:]) / np.maximum(cd_prof, 1e-9), 0.0)
        else:
            cd_prof = np.zeros(S)
            dstar = np.zeros(S)
            x_tr = np.ones((S, 2))
            x_sep = np.ones((S, 2))
            visc = np.ones(S)
            cf_share = np.zeros(S)

        # ---------------- separation (Kirchhoff): trailing-edge, shock-induced, leading-edge
        suction_upper = cl_inv >= 0.0
        f_bl = np.where(suction_upper, x_sep[:, 0], x_sep[:, 1])
        meff_s = np.where(suction_upper, meff_u, meff_l)
        if o.transonic:
            # shock-induced separation runs from the shock to the trailing edge, so the part of
            # the chord ahead of the shock stays attached: f falls from 1 to f_shock_min
            z = _smoothstep((meff_s - o.mach_shock_sep) / o.dmach_shock_sep)
            f_sh = 1.0 - (1.0 - o.f_shock_min) * z
        else:
            f_sh = np.ones(S)
        if o.le_suction:
            # McCullough & Gault: when the short leading-edge bubble bursts, a thick section
            # stalls at the nose, but on a thin one the shear layer reattaches as a long bubble
            # that keeps the normal force and only gives up the suction (charged in cd_le);
            # thin-aerofoil stall follows when the long bubble reaches the trailing edge, which
            # is reached at a leading-edge loading A0 / beta that hardly depends on thickness
            f_burst = o.f_le_min + (1.0 - o.f_le_min) * _smoothstep((eta_bubble - o.eta_burst) / o.eta_width)
            # unswept thin section: the long bubble grows over the chord and decambers it
            # (NACA 64A006: lift below potential from about 5 deg, maximum 0.8 near 9.5 deg)
            a0b = np.abs(A0) / beta_act
            f_thin = 1.0 - (1.0 - o.f_thin_stall_min) * _smoothstep((a0b - o.a0_long_bubble) / o.da0_long_bubble)
            # swept edge: the separated shear layer rolls up into a leading-edge vortex that is
            # convected along the edge (Polhamus); it holds the normal force until it bursts
            sw_lo, sw_hi = np.radians(o.vortex_sweep[0]), np.radians(o.vortex_sweep[1])
            k_v = _smoothstep((np.abs(npl.sweep) - sw_lo) / (sw_hi - sw_lo))
            f_vortex = 1.0 - (1.0 - o.f_thin_stall_min) * _smoothstep((a0b - o.a0_vortex_burst) / 0.15)
            f_thin = k_v * f_vortex + (1.0 - k_v) * f_thin
            w_thick = _smoothstep((npl.tau_n - o.tc_thin) / (o.tc_thick - o.tc_thin))
            f_le = w_thick * f_burst + (1.0 - w_thick) * f_thin
        else:
            f_le = np.ones(S)
            k_v = np.zeros(S)
        f = f_bl * f_sh * f_le
        if self.attached_only:
            f = np.ones(S)
        kirch = (0.5 * (1.0 + np.sqrt(f))) ** 2
        if o.stall_delay and chord_over_r is not None:
            # Snel: separated lift partially recovered on rotating blades, 3 (c/r)^2
            fs = np.clip(3.0 * np.asarray(chord_over_r) ** 2, 0.0, 1.0)
            kirch = kirch + fs * (1.0 - kirch)
        cl_sub = cl_inv * visc * kirch
        lift_slope = 2.0 * np.pi * np.maximum(k_lat, 0.05) / beta
        a_eff = cl_inv / lift_slope
        cd_sep = lift_slope * a_eff ** 2 * (0.5 * (1.0 - np.sqrt(f))) ** 2
        # with separation the leading-edge suction scales with sqrt(f) (Beddoes-Leishman chord
        # force), so the lost suction does too; cd_sep is the rest of the Kirchhoff pressure drag
        cd_le = cd_le * np.sqrt(f)
        # Polhamus' suction analogy: on a swept edge the suction the nose cannot carry is the
        # force that holds the leading-edge vortex, turned normal to the chord (vortex lift),
        # on the side of the spike
        if o.vortex_lift and o.le_suction:
            dcn_v = np.sign(A0) * k_v * cd_le
            cl_sub = cl_sub + dcn_v * np.cos(npl.alpha_n)
            cd_vortex = np.abs(dcn_v * np.sin(npl.alpha_n))
        else:
            cd_vortex = np.zeros(S)

        # ---------------- supersonic (Ackeret) section, frozen at mach_b below it
        bs = np.sqrt(np.maximum(np.maximum(Mn, o.mach_b) ** 2 - 1.0, 1e-6))
        cl_sup = 4.0 * npl.alpha_n / bs * visc
        cd_sup = 4.0 / bs * (npl.alpha_n ** 2 + (npl.cld_n ** 2) * self._int_eta2 + (npl.tau_n ** 2) * self._int_yt2)

        # ---------------- shock losses
        if o.transonic:
            cd_w_sub = o.k_wave * (sloss_u + sloss_l)
            # as the normal Mach number nears 1 the pocket reaches the trailing edge and its
            # terminal shock turns into the oblique trailing-edge shocks of supersonic flow; the
            # wave drag then cannot exceed that of the low-supersonic section (soft minimum)
            cd_w_sub = (np.maximum(cd_w_sub, 1e-30) ** -4 + np.maximum(cd_sup, 1e-9) ** -4) ** -0.25
        else:
            cd_w_sub = np.zeros(S)

        # ---------------- passage choke (dense rows)
        gam = 0.5 * cl_inv                                     # circulation, chord 1, W_n 1
        s_n = 1.0 / np.maximum(npl.sigma_n, 1e-6)
        sx, cx = np.sin(npl.xi_n), np.cos(npl.xi_n)
        w1x = 1.0 + gam * sx / (2.0 * s_n)
        w1y = gam * cx / (2.0 * s_n)
        d1 = np.arctan2(w1y, w1x)
        m1 = M_act * np.hypot(w1x, w1y)
        a1 = s_n * np.cos(npl.xi_n + d1)                       # inlet streamtube per passage
        throat = self._throat(npl, s_n) - 0.5 * dstar
        throat = throat * (1.0 + o.choke_relief)
        chi = mass_flux_function(m1) * np.maximum(a1, 0.0) / (PHI_STAR * np.maximum(throat, 1e-4))
        chi = np.where(npl.sigma_n > 1e-6, chi, 0.0)
        if o.choke and o.cascade:
            xc = 1.0 - 1.0 / np.maximum(chi, 1e-9)
            dp0 = 0.5 * (xc + np.sqrt(xc * xc + 1e-5))                     # smooth max(xc, 0)
            p01_p1 = (1.0 + 0.5 * (GAMMA - 1.0) * m1 ** 2) ** (GAMMA / (GAMMA - 1.0))
            q_over_p = 0.5 * GAMMA * M_act ** 2
            cd_choke_n = dp0 * p01_p1 / np.maximum(q_over_p, 1e-6) * np.maximum(a1, 0.0)
        else:
            cd_choke_n = np.zeros(S)

        # ---------------- supersonic normal Mach number: blend into Ackeret theory
        w = _smoothstep((Mn - o.mach_a) / (o.mach_b - o.mach_a))
        cl_n = (1.0 - w) * cl_sub + w * cl_sup
        cd_wave_n = (1.0 - w) * cd_w_sub + w * cd_sup

        # ---------------- back to the cylindrical element, per unit radius
        kA = npl.area_factor
        cl = cl_n * cL ** 2 * kA
        cd_wave = cd_wave_n * cL ** 3 * kA
        # separation, lost leading-edge suction and passage choke belong to the subsonic
        # branch; the supersonic (Ackeret) drag already holds the whole drag due to lift
        cd_choke = (1.0 - w) * cd_choke_n * cL ** 3 * kA
        cd_sep_s = (1.0 - w) * (cd_sep + cd_le + cd_vortex) * cL ** 3 * kA
        cd_profile = cd_prof * kA
        cd = cd_profile + cd_wave + cd_choke + cd_sep_s
        return SectionResult(cl=cl, cd=cd, cd_profile=cd_profile, cd_wave=cd_wave, cd_choke=cd_choke,
                             cd_sep=cd_sep_s, cl_n=cl_n, cl_inviscid_n=cl_inv, mach_n=Mn_act,
                             mach_peak_upper=mpk_u, mach_peak_lower=mpk_l, choke_ratio=chi,
                             k_lattice=k_lat, x_tr=x_tr, x_sep=x_sep, f_attached=f,
                             extras={"cf_share": cf_share, "dstar_te": dstar, "beta": beta,
                                     "mach_n_eff": Mn,
                                     "cd_le": (1.0 - w) * cd_le * cL ** 3 * kA, "eta_le": eta_spike, "A0": A0,
                                     "eta_bubble": eta_bubble,
                                     "mach_shock": np.maximum(meff_u, meff_l),
                                     "sigma_mapped": sol.sigma_m, "xi_mapped": sol.xi_m,
                                     "cp_upper": cpu, "cp_lower": cpl, "x": xe})

    # ------------------------------------------------------------------
    def _throat(self, npl: NormalPlane, s_n):
        """Minimum distance between the suction surface of a blade and the pressure surface of
        its neighbour (normal plane, chord 1)."""
        sh = self.shapes
        xe = self.cascade.xe
        base = npl.cld_n[:, None] * sh.eta_e - npl.alpha_n[:, None] * xe[None, :]
        yu = base + npl.tau_n[:, None] * sh.yt_e
        yl = base - npl.tau_n[:, None] * sh.yt_e
        px = (s_n * np.sin(npl.xi_n))[:, None]
        py = (s_n * np.cos(npl.xi_n))[:, None]
        sub = slice(None, None, 3)
        xu, yu_ = xe[None, sub], yu[:, sub]
        xl, yl_ = xe[None, sub] + px, yl[:, sub] + py
        dx = xu[:, :, None] - xl[:, None, :]
        dy = yu_[:, :, None] - yl_[:, None, :]
        return np.sqrt(dx * dx + dy * dy).min(axis=(1, 2))
