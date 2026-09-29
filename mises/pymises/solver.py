"""High-level cascade analysis: the pythonic equivalent of running MISES.

Typical use::

    from pymises import Blade, FlowConditions, ViscousOptions, CascadeSolver

    blade = Blade.from_parameters(inlet_metal_angle=45, exit_metal_angle=15,
                                  max_thickness=0.08, pitch=0.9)
    flow = FlowConditions(inlet_mach=0.5, inlet_angle=47.0, reynolds=5e5)
    result = CascadeSolver(blade, flow).solve()
    print(result.summary())

Two inviscid models are available:

``method="panel"``
    Periodic linear-vorticity panel method with Karman-Tsien
    compressibility (fast; subsonic flows).  Viscous coupling is a full
    simultaneous Newton solution with the exact panel interaction matrix.
``method="euler"``
    Finite-volume Euler solution on an H-grid (captures shocks, streamtube
    thickness / AVDR).  Viscous coupling uses wall transpiration with a
    quasi-Newton update whose interaction matrix comes from the panel method.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from . import gas
from .boundary_layer import (BLEnvironment, BoundaryLayerSolver, SurfaceBL, build_surfaces)
from .euler import EulerOptions, EulerSolver, HGrid

EULER_TE_SHARPEN = 0.04      # must match Blade.axial_surfaces(sharpen_te=...) used by HGrid
from .geometry import Blade
from .losses import (LossBreakdown, cascade_force_coefficients, cascade_mixed_out_loss,
                     mixed_out, uniform_state)
from .panel import CascadePanelMethod


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------

@dataclass
class FlowConditions:
    """Operating point (MISES ises.xxx equivalents in brackets).

    inlet_mach  : inlet Mach number M1                          [MINLin]
    inlet_angle : inlet flow angle from axial, degrees          [SINLin = tan]
    reynolds    : Reynolds number rho1 V1 c / mu1               [REYNin]
    gamma       : ratio of specific heats
    t01         : inlet total temperature in K (Sutherland law)
    avdr        : axial-velocity-density ratio (Euler only)      [streamtube b]
    """

    inlet_mach: float = 0.5
    inlet_angle: float = 45.0
    reynolds: float = 5.0e5
    gamma: float = gas.GAMMA_AIR
    t01: float = 288.15
    avdr: float = 1.0

    def validate(self):
        if not (0.0 <= self.inlet_mach < 0.99):
            raise ValueError("inlet_mach must be in [0, 0.99)")
        if not (-85.0 < self.inlet_angle < 85.0):
            raise ValueError("inlet_angle must be within +-85 degrees")
        if self.reynolds <= 1e3:
            raise ValueError("reynolds must be > 1e3")
        if not (1.0 < self.gamma < 2.0):
            raise ValueError("gamma must be in (1, 2)")
        if self.avdr <= 0:
            raise ValueError("avdr must be positive")


@dataclass
class ViscousOptions:
    """Boundary-layer options (MISES ises.xxx: NCRIT, XTRS)."""

    enabled: bool = True
    ncrit: float = 9.0
    xtr_upper: float = 1.0          # forced transition x/c on the upper (suction) side
    xtr_lower: float = 1.0          # forced transition x/c on the lower (pressure) side
    max_iterations: int = 80
    tolerance: float = 1e-6


@dataclass
class PanelOptions:
    n_panels: int = 180
    cosine_fraction: float = 0.3


# ---------------------------------------------------------------------------
# result
# ---------------------------------------------------------------------------

@dataclass
class SurfaceData:
    name: str
    x: np.ndarray
    y: np.ndarray
    xc: np.ndarray          # chordwise fraction from the LE
    s: np.ndarray           # arclength from the stagnation point
    mis: np.ndarray         # isentropic Mach number
    cp: np.ndarray          # (p - p1)/(p01 - p1)
    q: np.ndarray           # edge speed / V1

    def to_dict(self):
        return {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in self.__dict__.items()}


@dataclass
class CascadeResult:
    method: str
    blade: dict
    flow: dict
    viscous: dict
    performance: dict
    upper: SurfaceData
    lower: SurfaceData
    bl_upper: SurfaceBL | None = None
    bl_lower: SurfaceBL | None = None
    convergence: dict = field(default_factory=dict)
    field_data: dict | None = None
    warnings: list = field(default_factory=list)

    # convenience accessors
    @property
    def loss(self):
        return self.performance["omega"]

    @property
    def exit_angle(self):
        return self.performance["beta2"]

    def summary(self) -> str:
        p = self.performance
        f = self.flow
        lines = [
            f"pymises cascade analysis ({self.method})",
            f"  blade         : {self.blade['name']}",
            f"  s/c, stagger  : {self.blade['pitch'] / self.blade['chord']:.4f}, "
            f"{self.blade['stagger_deg']:.2f} deg",
            f"  M1, beta1     : {f['inlet_mach']:.4f}, {f['inlet_angle']:.3f} deg",
            f"  Re            : {f['reynolds']:.4g}",
            f"  incidence     : {p['incidence']:.3f} deg",
            f"  M2, beta2     : {p['M2']:.4f}, {p['beta2']:.3f} deg (mixed-out)",
            f"  beta2 inviscid: {p['beta2_inviscid']:.3f} deg",
            f"  deviation     : {p['deviation']:.3f} deg",
            f"  turning       : {p['turning']:.3f} deg",
            f"  p2/p1         : {p['p2_p1']:.4f}",
            f"  loss omega    : {p['omega']:.5f}  (inviscid part {p['omega_inviscid']:.5f})",
            f"  DF (Lieblein) : {p['diffusion_factor']:.4f}",
            f"  CL, CD        : {p['cl']:.4f}, {p['cd']:.5f}  (vector-mean angle {p['beta_m']:.2f} deg)",
        ]
        if self.bl_upper is not None:
            for bl in (self.bl_upper, self.bl_lower):
                tr = "forced" if bl.forced else "free"
                sep = ", ".join(f"{a:.3f}-{b:.3f}" for a, b in bl.separated) or "none"
                lines.append(f"  {bl.name:5s} side  : x_tr/c {bl.xtr_c:.4f} ({tr}), "
                             f"theta_TE {bl.theta[-1]:.3e}, H_TE {bl.H[-1]:.3f}, sep {sep}")
        for w in self.warnings:
            lines.append(f"  warning: {w}")
        return "\n".join(lines)

    def to_dict(self):
        d = {
            "method": self.method,
            "blade": self.blade,
            "flow": self.flow,
            "viscous": self.viscous,
            "performance": self.performance,
            "upper": self.upper.to_dict(),
            "lower": self.lower.to_dict(),
            "bl_upper": self.bl_upper.to_dict() if self.bl_upper else None,
            "bl_lower": self.bl_lower.to_dict() if self.bl_lower else None,
            "convergence": self.convergence,
            "field": self.field_data,
            "warnings": self.warnings,
        }
        return _jsonable(d)

    def to_json(self, indent=None):
        return json.dumps(self.to_dict(), indent=indent)

    def save(self, directory, stem="result", plots=True):
        """Write JSON, CSV surface/BL tables and (if matplotlib is present) plots."""
        from .io import save_result
        return save_result(self, directory, stem=stem, plots=plots)


def _jsonable(o):
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return _jsonable(o.tolist())
    if isinstance(o, (np.floating,)):
        o = float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return o


# ---------------------------------------------------------------------------
# solver
# ---------------------------------------------------------------------------

class CascadeSolver:
    """Coupled inviscid / boundary-layer analysis of a linear cascade."""

    def __init__(self, blade: Blade, flow: FlowConditions, viscous: ViscousOptions | None = None,
                 method: str = "panel", panel: PanelOptions | None = None,
                 euler: EulerOptions | None = None, verbose: bool = False, progress=None):
        self.blade = blade
        self.flow = flow
        self.viscous = viscous or ViscousOptions()
        self.method = method.lower()
        if self.method not in ("panel", "euler"):
            raise ValueError("method must be 'panel' or 'euler'")
        self.panel_opts = panel or PanelOptions()
        self.euler_opts = euler or EulerOptions()
        self.verbose = verbose
        self.progress = progress        # optional callable(message) for UIs
        flow.validate()

    # ------------------------------------------------------------------
    def solve(self) -> CascadeResult:
        t0 = time.time()
        if self.method == "panel":
            res = self._solve_panel()
        else:
            res = self._solve_euler()
        res.convergence["seconds"] = time.time() - t0
        return res

    # ------------------------------------------------------------ helpers
    def _compressibility_map(self):
        """Karman-Tsien velocity correction (hodograph form).

        q_c / V1 = q_i (1 - lam) / (1 - lam q_i^2),  lam = M1^2 / (1 + sqrt(1 - M1^2))^2,
        with q_i the incompressible panel speed / V1.  The map is smooth,
        monotone and exact at stagnation and at the inlet condition.
        Returns ``speed(qi) -> (q_c/V1, Mach)`` and ``F(qi) -> (q_c/V1, dq_c/dq_i)``.
        """
        f = self.flow
        g = f.gamma
        m1 = f.inlet_mach
        lam = m1 * m1 / (1.0 + math.sqrt(1.0 - m1 * m1)) ** 2
        q1 = float(gas.speed_over_a0(max(m1, 1e-8), g))
        qmax = math.sqrt(0.9 / lam) if lam > 0 else np.inf

        def speed(qi):
            qi = np.minimum(np.abs(np.asarray(qi, float)), qmax)
            qc = qi * (1.0 - lam) / (1.0 - lam * qi * qi)
            M = gas.mach_from_speed(np.minimum(qc * q1, 0.999 * math.sqrt(2.0 / (g - 1.0))), g)
            return qc, M

        def F(qi):
            qi = np.minimum(np.abs(np.asarray(qi, float)), qmax)
            den = 1.0 - lam * qi * qi
            qc = qi * (1.0 - lam) / den
            dq = (1.0 - lam) * (1.0 + lam * qi * qi) / den ** 2
            return qc, dq

        return speed, F

    def _env(self, mach1=None, reynolds=None):
        f = self.flow
        v = self.viscous
        return BLEnvironment(reynolds=reynolds or f.reynolds,
                             mach1=f.inlet_mach if mach1 is None else mach1, gamma=f.gamma,
                             chord=self.blade.chord, t01=f.t01, ncrit=v.ncrit)

    def _chord_frame(self, blade):
        le = blade.le_point
        te = blade.te_point
        cd = np.array([te[0] - le[0], te[1] - le[1]])
        c = float(np.hypot(*cd))
        return le, cd / c, c

    def _surface_data(self, x, y, ue_signed, mis, cp, q, stag_panel, stag_frac, le, cdir, c):
        """Split node data into upper/lower surfaces ordered LE -> TE."""
        N = x.size
        L = np.hypot(np.diff(x), np.diff(y))
        k, f = stag_panel, stag_frac
        up = np.arange(k, -1, -1)
        lo = np.arange(k + 1, N)
        su = f * L[k] + np.concatenate([[0.0], np.cumsum(L[:k][::-1])])
        sl = (1 - f) * L[k] + np.concatenate([[0.0], np.cumsum(L[k + 1:])])
        out = []
        for name, idx, s in (("upper", up, su), ("lower", lo, sl)):
            xc = ((x[idx] - le[0]) * cdir[0] + (y[idx] - le[1]) * cdir[1]) / c
            out.append(SurfaceData(name, x[idx], y[idx], xc, s, mis[idx], cp[idx], q[idx]))
        return out

    def _performance(self, blade, beta1, beta2_inv, loss, bl_u, bl_l, mach1_used, inlet=None):
        f = self.flow
        g = f.gamma
        chi1, chi2 = blade.estimated_metal_angles()
        ex = loss.exit
        p1 = loss.inlet_p
        beta2 = ex.angle
        m2 = ex.mach
        V1 = mach1_used * math.sqrt(float(gas.t_ratio(mach1_used, g)))
        vr = math.hypot(ex.u, ex.v) / V1
        sigma = blade.solidity
        dvt = abs(math.sin(math.radians(beta1)) - vr * math.sin(math.radians(beta2)))
        df = 1.0 - vr + dvt / (2.0 * sigma)
        cx = blade.axial_chord
        zw = 2.0 * (blade.pitch / cx) * math.cos(math.radians(beta2)) ** 2 * abs(
            math.tan(math.radians(beta1)) - math.tan(math.radians(beta2)))
        perf = {
            "omega": loss.omega,
            "omega_inviscid": loss.omega_inviscid,
            "omega_viscous": loss.omega_viscous,
            "beta1": beta1,
            "beta2": beta2,
            "beta2_inviscid": beta2_inv,
            "M1": f.inlet_mach,
            "M2": m2,
            "p2_p1": ex.p / p1,
            "p02_p01": ex.p0 * g,
            "incidence": beta1 - chi1,
            "deviation": beta2 - chi2,
            "turning": beta1 - beta2,
            "inlet_metal_angle": chi1,
            "exit_metal_angle": chi2,
            "velocity_ratio": vr,
            "diffusion_factor": df,
            "zweifel": zw,
            "choked": bool(ex.choked),
            "omega_exit": (1.0 / g - ex.p0) / max(1.0 / g - ex.p, 1e-12),
        }
        # inlet stagnation pressure consistent with omega (the Euler loss is referred to
        # the mass-averaged inlet-plane value)
        p01_eff = ex.p0 + loss.omega * (loss.inlet_p0 - loss.inlet_p)
        if inlet is None:
            rho1, V1u, p1u, _ = uniform_state(mach1_used, beta1, g)
            b1r = math.radians(beta1)
            fc = cascade_force_coefficients(rho1, V1u * math.cos(b1r), V1u * math.sin(b1r), p1u, ex,
                                            blade.pitch, blade.chord, p01=p01_eff)
        else:
            # Euler: the inlet side of the control volume is the computed inlet plane
            fc = cascade_force_coefficients(inlet.rho, inlet.u, inlet.v, inlet.p, ex,
                                            blade.pitch, blade.chord, p01=p01_eff)
        perf.update({"cl": fc["cl"], "cd": fc["cd"], "cd_momentum": fc["cd_momentum"],
                     "beta_m": fc["beta_m"],
                     "lift_drag": fc["cl"] / fc["cd"] if fc["cd"] > 1e-12 else None})
        if bl_u is not None:
            perf.update({
                "xtr_upper": bl_u.xtr_c, "xtr_lower": bl_l.xtr_c,
                "theta_te": float(bl_u.theta[-1] + bl_l.theta[-1]),
                "dstar_te": float(bl_u.dstar[-1] + bl_l.dstar[-1]),
                "H_te_upper": float(bl_u.H[-1]), "H_te_lower": float(bl_l.H[-1]),
                "sep_upper": bl_u.separated, "sep_lower": bl_l.separated,
            })
        return perf

    def _blade_info(self, blade):
        d = blade.to_dict()
        d.pop("x"), d.pop("y")
        d["x"] = blade.x.tolist()
        d["y"] = blade.y.tolist()
        return d

    # ------------------------------------------------------------ panel
    def _solve_panel(self) -> CascadeResult:
        f = self.flow
        v = self.viscous
        g = f.gamma
        blade = self.blade.closed_te().repanel(self.panel_opts.n_panels, self.panel_opts.cosine_fraction)
        pm = CascadePanelMethod(blade)
        inv = pm.solve(f.inlet_angle)
        speed, F = self._compressibility_map()
        le, cdir, c = self._chord_frame(blade)
        warnings = []
        conv = {"panels": pm.N - 1}
        bl_u = bl_l = None
        sol = inv
        if v.enabled:
            env = self._env()
            bls = BoundaryLayerSolver(env)
            su, sl = build_surfaces(blade.x, blade.y, inv.stag_panel, inv.stag_frac,
                                    v.xtr_upper, v.xtr_lower, le=le, chord_dir=cdir, chord=c)
            D = pm.ue_sensitivity(su.stag_panel)
            if pm.closed_te:
                su, sl, D = _close_te_bl(su, sl, D)
            ue0 = inv.ue
            out = bls.solve_coupled([su, sl], ue0, D, F=F, max_iter=v.max_iterations,
                                    tol=v.tolerance, verbose=self.verbose)
            conv.update({"bl_converged": out["converged"], "bl_iterations": out["iterations"],
                         "bl_history": out["history"]})
            if not out["converged"]:
                warnings.append("boundary-layer Newton iteration did not fully converge")
            X, typs = out["X"], out["typs"]
            bl_u = bls.package(su, X[0], out["ue"][su.nodes], typs[0])
            bl_l = bls.package(sl, X[1], out["ue"][sl.nodes], typs[1])
            m_c = out["m"].copy()
            if pm.closed_te:
                m_c[0], m_c[-1] = m_c[1], m_c[-2]
            # displacement-corrected inviscid solution (m in incompressible units)
            ue_c = np.maximum(out["ue"], 1e-9)
            ulin = ue0 + D @ m_c
            m_inc = m_c * ulin / ue_c
            sol = pm.solve_with_mass_defect(f.inlet_angle, m_inc, su.stag_panel)
            dstar = bl_u.dstar[-1] + bl_l.dstar[-1]
            theta = bl_u.theta[-1] + bl_l.theta[-1]
        else:
            dstar = theta = 0.0
        # surface Mach numbers from the (displacement-corrected) edge speeds
        qi = np.abs(sol.gamma)
        qc, mis = speed(qi)
        p1_p01 = float(gas.p_ratio(f.inlet_mach, g))
        pr = np.asarray(gas.p_ratio(mis, g))
        cp = (pr - p1_p01) / (1.0 - p1_p01) if f.inlet_mach > 1e-6 else 1.0 - qi ** 2
        k, fr = pm.stagnation(sol.gamma)
        upper, lower = self._surface_data(blade.x, blade.y, sol.gamma, mis, cp, qc, k, fr,
                                          le, cdir, c)
        t_te = self.blade.te_gap
        loss = cascade_mixed_out_loss(f.inlet_mach if f.inlet_mach > 1e-6 else 1e-4,
                                      f.inlet_angle, sol.beta2, blade.pitch, dstar, theta, t_te, g)
        if loss.exit.choked:
            warnings.append("mixed-out exit state is choked")
        if np.max(mis) > 1.0:
            warnings.append(f"peak isentropic Mach {np.max(mis):.3f} > 1: the Karman-Tsien "
                            "panel model is outside its range, use method='euler'")
        perf = self._performance(blade, f.inlet_angle, inv.beta2, loss, bl_u, bl_l,
                                 max(f.inlet_mach, 1e-4))
        perf["beta2_panel_viscous"] = sol.beta2
        perf["circulation"] = sol.circulation
        return CascadeResult("panel", self._blade_info(blade), _flow_dict(f), asdict(v), perf,
                             upper, lower, bl_u, bl_l, conv, None, warnings)

    # ------------------------------------------------------------ euler
    def _solve_euler(self) -> CascadeResult:
        f = self.flow
        v = self.viscous
        g = f.gamma
        o = self.euler_opts
        p01 = 1.0 / g
        warnings = []
        # panel solution: wake-line direction and initial exit angle
        bp = self.blade.closed_te().repanel(self.panel_opts.n_panels,
                                            self.panel_opts.cosine_fraction)
        beta2_guess = CascadePanelMethod(bp).solve(f.inlet_angle).beta2
        grid = HGrid.for_blade(self.blade, o, f.inlet_angle, beta2_guess, f.avdr)
        es = EulerSolver(grid, f.inlet_angle, f.inlet_mach, g, o)
        m2_guess = gas.mach_from_mass_flow_function(
            float(gas.mass_flow_function(f.inlet_mach, g)) * math.cos(math.radians(f.inlet_angle))
            / max(math.cos(math.radians(beta2_guess)) * f.avdr, 1e-6), g)
        es.initialise(beta2_guess, None if not np.isfinite(m2_guess) else m2_guess)
        progress = self.progress

        def cb(n, r, stage="Euler"):
            if progress is not None:
                progress(f"{stage}: step {n}, residual {r:.2e}")

        run = es.run(verbose=self.verbose, callback=cb)
        conv = {"euler_steps": run["steps"], "euler_converged": run["converged"],
                "euler_history": run["history"][::10], "grid": [grid.ni, grid.nj]}
        if run.get("choked"):
            raise RuntimeError(f"cascade choked: inlet Mach {f.inlet_mach:g} cannot be reached "
                               f"at inlet angle {f.inlet_angle:g} deg (maximum about "
                               f"{es.inlet_state()[1]:.3f}); lower the inlet Mach number")
        if not run["converged"]:
            warnings.append("Euler solution did not reach the residual tolerance")
        xc_, yc_ = grid.contour()
        cblade = Blade(xc_, yc_, grid.pitch, self.blade.name + " (Euler wall)")
        le, cdir, c = self._chord_frame(self.blade)
        bl_u = bl_l = None
        deficits = None
        if v.enabled:
            pmE = CascadePanelMethod(cblade)
            bls = BoundaryLayerSolver(self._env())
            m_used = np.zeros(cblade.n_points)
            X = typs = None
            prev_key = None
            cycles = []
            out = None
            for cyc in range(o.coupling_cycles):
                wd = es.wall_data()
                _, M1a = es.inlet_state()
                V1 = M1a * math.sqrt(float(gas.t_ratio(M1a, g)))
                qn = wd["q_is"] / V1
                k, fr = pmE.stagnation(qn)
                su, sl = build_surfaces(cblade.x, cblade.y, k, fr, v.xtr_upper, v.xtr_lower,
                                        le=le, chord_dir=cdir, chord=c)
                D = pmE.ue_sensitivity(su.stag_panel)
                su, sl, D = _close_te_bl(su, sl, D)
                bls.env = self._env(mach1=M1a)
                key = (su.stag_panel, su.stag_node)
                if key != prev_key:
                    X = typs = None
                ue_in = _without_te_sharpening(np.abs(qn), (su, sl))
                out = bls.solve_coupled([su, sl], np.maximum(ue_in, 1e-6), D, m_ref=m_used,
                                        X0=X, typs=typs, max_iter=v.max_iterations,
                                        tol=v.tolerance, fix_transition=(cyc >= 2 and X is not None))
                X, typs, prev_key = out["X"], out["typs"], key
                m_new = out["m"].copy()
                m_new[0], m_new[-1] = m_new[1], m_new[-2]
                dm = float(np.max(np.abs(m_new - m_used)) / max(np.max(np.abs(m_new)), 1e-12))
                cycles.append({"cycle": cyc, "dm": dm, "bl_iterations": out["iterations"],
                               "bl_converged": out["converged"], "euler_steps": es.last_run["steps"]})
                if self.verbose:
                    jmax = int(np.argmax(np.abs(m_new - m_used)))
                    print(f" coupling cycle {cyc}: dm {dm:.3e} at node {jmax} key {key} "
                          f"itr {[int(np.argmax(t == 2)) for t in typs]} bl_it {out['iterations']} "
                          f"conv {out['converged']} rms {np.sqrt(np.mean((m_new - m_used) ** 2)) / max(np.sqrt(np.mean(m_new ** 2)), 1e-12):.2e}")
                if progress is not None:
                    progress(f"viscous coupling cycle {cyc + 1}: change {dm:.2e}")
                m_used = m_used + o.coupling_relax * (m_new - m_used)
                # transpiration mass flux per contour panel (Euler units: rho a0 * chord)
                mE = wd["rho_is"] * V1 * m_used
                G = pmE.mass_defect_operator(su.stag_panel)
                es.set_transpiration((G @ mE) * pmE.L)
                # stop only on a converged boundary layer: a stalled Newton iteration
                # returns an unchanged mass defect, which is not convergence
                if dm < 3e-3 and cyc > 0 and out["converged"]:
                    break
                es.run(max_steps=o.coupling_steps, tol=o.tol,
                       callback=lambda n, r, c=cyc: cb(n, r, f"coupling cycle {c + 1}"))
            conv["coupling"] = cycles
            # converge the inviscid solution with the final displacement effect
            fin = es.run(tol=o.tol, callback=lambda n, r: cb(n, r, "final Euler"))
            conv["euler_final_steps"] = fin["steps"]
            conv["euler_final_converged"] = fin["converged"]
            if not fin["converged"]:
                warnings.append("final Euler pass (with displacement effect) did not reach the "
                                "convergence criteria")
            if not out["converged"]:
                warnings.append("boundary-layer Newton iteration did not fully converge")
            if cycles and cycles[-1]["dm"] > 3e-2:
                warnings.append("viscous-inviscid coupling not fully converged")
            bl_u = bls.package(su, X[0], out["ue"][su.nodes], typs[0])
            bl_l = bls.package(sl, X[1], out["ue"][sl.nodes], typs[1])
            wd = es.wall_data()
            _, M1a = es.inlet_state()
            V1 = M1a * math.sqrt(float(gas.t_ratio(M1a, g)))
            iu, il = su.nodes[-1], sl.nodes[-1]
            # edge state at the trailing edge from the boundary layer's own (corrected)
            # edge speed: the raw Euler wall speed there carries the sharpening artifact
            V_e = 0.5 * (out["ue"][iu] + out["ue"][il]) * V1
            rho_e = (1.0 - 0.5 * (g - 1.0) * V_e * V_e) ** (1.0 / (g - 1.0))
            deficits = (bl_u.dstar[-1] + bl_l.dstar[-1], bl_u.theta[-1] + bl_l.theta[-1],
                        rho_e, V_e)
        # ---- post-processing ---------------------------------------------
        wd = es.wall_data()
        _, M1a = es.inlet_state()
        rho1, V1, p1, _ = uniform_state(M1a, f.inlet_angle, g)
        mis = gas.mach_from_p_ratio(np.clip(wd["p"] / p01, 1e-6, 1.0), g)
        cp = (wd["p"] - p1) / (p01 - p1)
        qn = wd["q_is"] / V1
        k, fr = CascadePanelMethod.stagnation_static(qn, wd["i_le"])
        upper, lower = self._surface_data(wd["x"], wd["y"], qn, mis, cp, np.abs(qn), k, fr,
                                          le, cdir, c)
        i_exit = grid.ni - 2
        mdot, fx, fy, fe, _ = es.plane_fluxes(i_exit)
        b_e = grid.b_nodes[i_exit]
        h0 = fe / mdot
        core_fl = (mdot / b_e, fx / b_e, fy / b_e)
        core = mixed_out(*core_fl, h0, grid.pitch, g)
        mdot_in, fx_in, fy_in, fe_in, _ = es.plane_fluxes(1)
        b_in = grid.b_nodes[1]
        inlet_mixed = mixed_out(mdot_in / b_in, fx_in / b_in, fy_in / b_in, fe_in / mdot_in,
                                grid.pitch, g)
        m_wall = es.transpiration_mass()
        conv["mass_imbalance"] = (mdot - mdot_in - m_wall) / mdot_in
        conv["transpiration_mass"] = m_wall / mdot_in
        q = p01 - p1
        # loss generated inside the domain (shocks + numerical): inlet-plane minus
        # exit-plane mass-averaged stagnation pressure
        p0_in = es.mass_averaged_p0(1)
        p0_out = es.mass_averaged_p0(i_exit)
        omega_inv = (p0_in - p0_out) / q
        t_te = self.blade.te_gap
        if deficits is not None:
            # real exit flow = displacement-body (transpiration) core minus the
            # boundary-layer deficits at the trailing edge, then mixed out
            ds_, th_, rho_e, V_e = deficits
            lv = cascade_mixed_out_loss(M1a, f.inlet_angle, core.angle, grid.pitch, ds_, th_,
                                        t_te, g, core_fluxes=core_fl, edge=(rho_e, V_e),
                                        p0_core=core.p0)
            exit_state = lv.exit
        else:
            exit_state = core
        # the mixing and viscous increment is measured from the exit-plane mass-averaged
        # p0 to the mixed-out state of the real flow (never from a mixed-out core that
        # still contains the transpiration mass)
        omega_tot = (p0_in - exit_state.p0) / q
        conv.update({"p0_in_avg": p0_in, "p0_out_avg": p0_out, "p0_core_mixed": core.p0,
                     "p0_mixed": exit_state.p0, "q1": q})
        if deficits is not None:
            conv.update({"edge_rho": deficits[2], "edge_V": deficits[3], "core_V": math.hypot(core.u, core.v),
                         "core_rho": core.rho, "core_p": core.p, "mix_p": exit_state.p})
        loss = LossBreakdown(omega_tot, omega_inv, omega_tot - omega_inv, exit_state, p1, p01)
        perf = self._performance(self.blade, f.inlet_angle, core.angle, loss, bl_u, bl_l, M1a,
                                 inlet=inlet_mixed)
        perf["M1_actual"] = M1a
        perf["beta1_inlet_plane"] = inlet_mixed.angle
        perf["p_exit_p01"] = es.p_exit / p01
        perf["peak_mis"] = float(np.max(mis))
        rho, u, vv, pp = es.primitives()
        Mf = np.hypot(u, vv) / np.sqrt(g * pp / rho)
        field_data = {"x": grid.X.tolist(), "y": grid.Y.tolist(), "mach": Mf.tolist(),
                      "pitch": grid.pitch}
        return CascadeResult("euler", self._blade_info(self.blade), _flow_dict(f), asdict(v),
                             perf, upper, lower, bl_u, bl_l, conv, field_data, warnings)


def _inlet_uv(beta1, V):
    b = math.radians(beta1)
    return V * math.cos(b), V * math.sin(b)


def _flow_dict(f: FlowConditions):
    return asdict(f)


def _without_te_sharpening(ue, surfaces, x_start=1.0 - 1.75 * EULER_TE_SHARPEN, width=0.08):
    """Edge speed for the boundary layer, free of the H-grid trailing-edge artifact.

    The Euler walls sharpen the trailing edge over the last ``EULER_TE_SHARPEN``
    of axial chord (``Blade.axial_surfaces``).  This puts a spurious local
    acceleration followed by a deceleration into the wall speed, starting about
    3 % of chord before the sharpened part.  Fed to the boundary layer it causes
    separation and stops the Newton iteration converging, so from ``x_start``
    onwards the edge speed is replaced by a straight-line extrapolation (in
    arclength) of the preceding ``width`` of chord.
    """
    ue = np.array(ue, float)
    for s in surfaces:
        u = ue[s.nodes]
        rep = s.xc > x_start
        fit = (s.xc > x_start - width) & (s.xc <= x_start)
        if rep.any() and fit.sum() >= 2:
            a, b = np.polyfit(s.xi[fit], u[fit], 1)
            u[rep] = np.maximum(a * s.xi[rep] + b, 1e-3)
            ue[s.nodes] = u
    return ue


def _close_te_bl(su, sl, D):
    """Remove the trailing-edge nodes of a closed TE from the BL unknowns.

    Their mass defect is tied to the neighbouring node (no source on the last
    panel), which is expressed by folding the TE columns of the interaction
    matrix into the neighbouring columns.
    """
    su2, sl2 = su.drop_last(), sl.drop_last()
    D = D.copy()
    for te, nb in ((su.nodes[-1], su.nodes[-2]), (sl.nodes[-1], sl.nodes[-2])):
        D[:, nb] += D[:, te]
        D[:, te] = 0.0
    return su2, sl2, D
