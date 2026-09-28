"""Verification suite for pymises.

Every case compares a pymises computation with an independent reference
(an exact analytic solution, a classical closed-form result, or a
conservation law) and returns a :class:`CaseResult` with the measured error
and the pass/fail tolerance.  The suite is used by the unit tests, by
``pymises verify`` and by the online dashboard.

Cases
-----
panel_manufactured       exact periodic potential flow (source/sink/vortex rows)
panel_isolated_joukowski isolated Joukowski aerofoil, exact conformal-map solution
panel_convergence        observed order of accuracy of the panel method
bl_blasius               laminar flat plate vs Blasius
bl_hiemenz               stagnation-point similarity vs Hiemenz
bl_turbulent_flatplate   turbulent skin friction vs Coles-Fernholz
bl_transition_michel     e^N flat-plate transition vs Michel's criterion
loss_mixing              mixed-out loss vs exact incompressible mixing (Lieblein)
loss_conservation        mixed-out state conserves fluxes; zero BL -> zero loss
euler_freestream         freestream preservation on a skewed periodic grid
euler_nozzle_shock       quasi-1-D Laval nozzle with a normal shock
euler_vs_panel           low-Mach Euler vs panel method on a compressor cascade
plus the observed-order and Joukowski checks of the panel method.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np
from scipy.integrate import solve_ivp

from . import gas
from .boundary_layer import (BLEnvironment, BoundaryLayerSolver, Surface, critical_re_theta,
                             station_vars)
from .geometry import Blade
from .losses import cascade_mixed_out_loss, lieblein_loss, mixed_out, fluxes_of_uniform
from .panel import CascadePanelMethod


@dataclass
class CaseResult:
    name: str
    description: str
    reference: str
    metric: str
    value: float
    tolerance: float
    passed: bool
    seconds: float = 0.0
    details: dict = field(default_factory=dict)
    plot: dict | None = None     # small series for the dashboard

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items()}


def _case(name, description, reference, metric, value, tol, t0, details=None, plot=None,
          larger_is_worse=True):
    passed = bool(value <= tol) if larger_is_worse else bool(value >= tol)
    return CaseResult(name, description, reference, metric, float(value), float(tol), passed,
                      time.time() - t0, details or {}, plot)


# ---------------------------------------------------------------------------
# manufactured periodic potential flow
# ---------------------------------------------------------------------------

class ManufacturedCascade:
    """Uniform stream + periodic rows of a source, a sink and a vortex.

    The closed dividing streamline through the two stagnation points is an
    exact cascade blade: the flow outside it is an exact solution of the
    cascade problem with the Kutta condition satisfied at the rear
    stagnation point.
    """

    def __init__(self, s=1.0, U=1.0, V=None, Q=0.6, gamma=-0.4, a=0.3, stagger_deg=30.0):
        self.s, self.U, self.Q, self.G = s, U, Q, gamma
        e = a * np.exp(1j * math.radians(stagger_deg))
        self.z1, self.z2, self.z3 = -e, e, 0.0 + 0.0j
        if V is None:
            V = self._closing_crossflow()
        self.V = V

    def _mismatch(self, V):
        self.V = V
        zf, zr = self.stagnation(-1), self.stagnation(+1)
        return float(self.psi(np.array([zf]))[0] - self.psi(np.array([zr]))[0])

    def _closing_crossflow(self):
        """Cross-flow V for which the front and rear stagnation points share a streamline."""
        from scipy.optimize import brentq
        lo, hi = -1.5, 1.5
        vs = np.linspace(lo, hi, 13)
        f = [self._mismatch(v) for v in vs]
        for i in range(len(vs) - 1):
            if f[i] == 0.0:
                return vs[i]
            if f[i] * f[i + 1] < 0:
                return brentq(self._mismatch, vs[i], vs[i + 1], xtol=1e-14)
        raise RuntimeError("no closed dividing streamline for these parameters")

    def W(self, z):
        s = self.s
        c = lambda a: 1.0 / np.tanh(np.pi * (z - a) / s)
        return (self.U - 1j * self.V + self.Q / (2 * s) * (c(self.z1) - c(self.z2))
                - 1j * self.G / (2 * s) * c(self.z3))

    def dW(self, z):
        s = self.s
        d = lambda a: -(np.pi / s) / np.sinh(np.pi * (z - a) / s) ** 2
        return self.Q / (2 * s) * (d(self.z1) - d(self.z2)) - 1j * self.G / (2 * s) * d(self.z3)

    def psi(self, z):
        s = self.s
        sh = lambda a: np.sinh(np.pi * (z - a) / s)
        return (self.U * z.imag - self.V * z.real
                + self.Q / (2 * np.pi) * np.angle(sh(self.z1) / sh(self.z2))
                - self.G / (2 * np.pi) * np.log(np.abs(sh(self.z3))))

    def stagnation(self, side):
        """Front (side=-1) or rear (side=+1) stagnation point: grid search, then Newton."""
        xs = np.linspace(-1.2, 1.2, 481)
        ys = np.linspace(-0.45 * self.s, 0.45 * self.s, 181)
        Z = xs[None, :] + 1j * ys[:, None]
        with np.errstate(all="ignore"):
            q = np.abs(self.W(Z))
        q[~np.isfinite(q)] = np.inf
        mask = (Z.real * side) > 0
        q = np.where(mask, q, np.inf)
        # exclude the singular points themselves
        for a in (self.z1, self.z2, self.z3):
            q = np.where(np.abs(Z - a) < 0.05, np.inf, q)
        j, i = np.unravel_index(np.argmin(q), q.shape)
        z = complex(Z[j, i])
        for _ in range(100):
            dz = -self.W(z) / self.dW(z)
            if abs(dz) > 0.05:
                dz = 0.05 * dz / abs(dz)
            z += dz
            if abs(dz) < 1e-14:
                break
        return z

    def inlet(self):
        v1 = self.V - self.G / (2 * self.s)
        return self.U, v1

    def exit(self):
        return self.U, self.V + self.G / (2 * self.s)

    def body(self, n_trace=4000):
        """Trace the dividing streamline; returns contour CCW from the rear stagnation point."""
        zf = self.stagnation(-1)
        zr = self.stagnation(+1)
        A = self.dW(zf)
        al = np.angle(A)
        dirs = [np.exp(1j * (-al / 2)), np.exp(1j * (-al / 2 + np.pi))]
        h = 5e-4
        psi_s = float(self.psi(np.array([zf]))[0])

        def direction(z):
            w = self.W(z)
            return np.conj(w) / abs(w)

        branches = []
        for d in dirs:
            z = zf + 2e-3 * d
            pts = [z]
            for _ in range(20000):
                k1 = direction(z)
                k2 = direction(z + 0.5 * h * k1)
                k3 = direction(z + 0.5 * h * k2)
                k4 = direction(z + h * k3)
                z = z + h * (k1 + 2 * k2 + 2 * k3 + k4) / 6.0
                pts.append(z)
                if abs(z - zr) < 3e-3:
                    break
            branches.append(np.array(pts))
        # identify upper branch (larger mean y)
        if branches[0].imag.mean() < branches[1].imag.mean():
            branches.reverse()
        # project onto psi = psi_s to remove integration drift
        out = []
        for br in branches:
            z = br.copy()
            for _ in range(4):
                w = self.W(z)
                gx, gy = w.imag, w.real          # grad psi = (-v, u) with v = -Im W
                g2 = gx * gx + gy * gy
                dp = self.psi(z) - psi_s
                ok = g2 > 1e-6
                z = z - np.where(ok, dp / np.where(ok, g2, 1.0), 0.0) * (gx + 1j * gy)
            out.append(z)
        up, lo = out
        zc = np.concatenate([[zr], up[::-1], [zf], lo, [zr]])
        keep = np.concatenate([[True], np.abs(np.diff(zc)) > 1e-9])
        zc = zc[keep]
        return zc.real, zc.imag, zf, zr


def verify_panel_manufactured(n_panels=240):
    """Panel method vs an exact periodic potential flow."""
    t0 = time.time()
    mc = ManufacturedCascade()
    x, y, zf, zr = mc.body()
    blade = Blade(x, y, mc.s, "manufactured")
    # repanel with the LE at the front stagnation point
    b = blade.repanel(n_panels, 0.7)
    pm = CascadePanelMethod(b)
    u1, v1 = mc.inlet()
    V1 = math.hypot(u1, v1)
    beta1 = math.degrees(math.atan2(v1, u1))
    sol = pm.solve(beta1)
    z = b.x + 1j * b.y
    w = mc.W(z)
    u, v = w.real, -w.imag
    _, sx, sy = b.spline()
    sarc = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(b.x), np.diff(b.y)))])
    tx = sx(sarc, 1)
    ty = sy(sarc, 1)
    tn = np.hypot(tx, ty)
    g_exact = (u * tx + v * ty) / tn / V1
    err = np.abs(sol.gamma - g_exact)
    u2, v2 = mc.exit()
    b2_exact = math.degrees(math.atan2(v2, u2))
    err_b2 = abs(sol.beta2 - b2_exact)
    circ_exact = mc.G / V1
    return _case("panel_manufactured",
                 "Cascade panel method against an exact periodic potential flow: uniform stream "
                 "plus periodic rows of a source, a sink and a point vortex; the blade is the "
                 "dividing streamline, so the exact surface speed and exit angle are known.",
                 "Analytic solution (method of manufactured solutions)",
                 "max |q - q_exact| / V1", float(err.max()), 5e-3, t0,
                 {"exit_angle_error_deg": err_b2, "beta1": beta1, "beta2_exact": b2_exact,
                  "beta2": sol.beta2, "circulation_error": abs(sol.circulation - circ_exact),
                  "n_panels": n_panels, "rms_error": float(np.sqrt(np.mean(err ** 2)))},
                 {"x": b.x.tolist(), "y": b.y.tolist(), "q": sol.gamma.tolist(),
                  "q_exact": g_exact.tolist()})


def _manufactured_error(n_panels):
    mc = ManufacturedCascade()
    x, y, _, _ = mc.body()
    b = Blade(x, y, mc.s, "manufactured").repanel(n_panels, 0.7)
    pm = CascadePanelMethod(b)
    u1, v1 = mc.inlet()
    V1 = math.hypot(u1, v1)
    sol = pm.solve(math.degrees(math.atan2(v1, u1)))
    w = mc.W(b.x + 1j * b.y)
    _, sx, sy = b.spline()
    sarc = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(b.x), np.diff(b.y)))])
    tx, ty = sx(sarc, 1), sy(sarc, 1)
    g_exact = (w.real * tx - w.imag * ty) / np.hypot(tx, ty) / V1
    u2, v2 = mc.exit()
    return (float(np.sqrt(np.mean((sol.gamma - g_exact) ** 2))),
            abs(sol.beta2 - math.degrees(math.atan2(v2, u2))))


def verify_panel_convergence(ns=(60, 120, 240)):
    """Observed order of accuracy of the panel method (RMS surface-speed error)."""
    t0 = time.time()
    errs = [_manufactured_error(n) for n in ns]
    e = np.array([x[0] for x in errs])
    orders = np.log(e[:-1] / e[1:]) / np.log(np.array(ns[1:]) / np.array(ns[:-1]))
    order = float(orders[-1])
    return _case("panel_convergence",
                 "Grid convergence of the panel method on the manufactured cascade: RMS error of "
                 "the surface speed for 60, 120 and 240 panels; a second-order method should show "
                 "an observed order close to 2.",
                 "Richardson analysis against the exact solution",
                 "observed order of accuracy", order, 1.5, t0,
                 {"n_panels": list(ns), "rms_errors": e.tolist(), "orders": orders.tolist(),
                  "exit_angle_errors_deg": [x[1] for x in errs]},
                 {"n": list(ns), "rms_error": e.tolist()}, larger_is_worse=False)


# ---------------------------------------------------------------------------
# isolated Joukowski aerofoil
# ---------------------------------------------------------------------------

def joukowski_exact(mu=complex(-0.1, 0.08), alpha_deg=5.0, n=3000):
    """Exact Joukowski aerofoil and surface velocity (unit free-stream speed)."""
    R = abs(1.0 - mu)
    beta = -math.atan2((1.0 - mu).imag, (1.0 - mu).real)
    al = math.radians(alpha_deg)
    G = 4.0 * math.pi * R * math.sin(al + beta)          # clockwise circulation
    th = -beta + np.linspace(0.0, 2.0 * np.pi, n + 1)
    xi = R * np.exp(1j * th)
    zeta = mu + xi
    z = zeta + 1.0 / zeta
    Wz_num = (np.exp(-1j * al) - R * R * np.exp(1j * al) / xi ** 2) - 1j * G / (2 * np.pi * xi) * -1
    Wz_num = np.exp(-1j * al) - R * R * np.exp(1j * al) / xi ** 2 + 1j * G / (2 * np.pi * xi)
    dz = 1.0 - 1.0 / zeta ** 2
    with np.errstate(all="ignore"):
        Wz = Wz_num / dz
    # tangent along the contour (increasing theta = counter-clockwise)
    dzdth = dz * 1j * xi
    with np.errstate(all="ignore"):
        t = dzdth / np.abs(dzdth)
    q = np.real(Wz * t)
    chord = float(np.max(z.real) - np.min(z.real))
    cl = 2.0 * G / chord
    return z, q, chord, cl


def verify_panel_joukowski(n_panels=240, alpha=5.0):
    """Isolated Joukowski aerofoil (pitch -> infinity) against the conformal-map solution."""
    t0 = time.time()
    z, q, chord, cl = joukowski_exact(alpha_deg=alpha)
    zc = z[:-1]
    # contour starts at the TE (cusp) going over the upper surface
    blade = Blade(np.concatenate([zc.real, [z[-1].real]]), np.concatenate([zc.imag, [z[-1].imag]]),
                  1.0e4 * chord, "Joukowski")
    b = blade.repanel(n_panels, 0.3)
    pm = CascadePanelMethod(b)
    sol = pm.solve(alpha)
    s_ex = np.concatenate([[0.0], np.cumsum(np.abs(np.diff(z)))])
    s_b = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(b.x), np.diff(b.y)))])
    s_b *= s_ex[-1] / s_b[-1]
    q_ex = np.interp(s_b, s_ex[1:-1], q[1:-1])
    inner = slice(3, -3)
    err = np.abs(sol.gamma - q_ex)[inner]
    cl_p = -2.0 * sol.circulation / chord
    return _case("panel_isolated_joukowski",
                 "Isolated cambered Joukowski aerofoil at 5 deg incidence (pitch = 10^4 chords) "
                 "against the exact conformal-mapping solution: surface speed and lift.",
                 "Exact Joukowski / Kutta-Joukowski solution",
                 "max |q - q_exact| / V (excluding the cusp)", float(err.max()), 0.02, t0,
                 {"cl_exact": cl, "cl_panel": cl_p, "cl_rel_error": abs(cl_p - cl) / cl,
                  "rms_error": float(np.sqrt(np.mean(err ** 2)))},
                 {"x": (b.x / chord).tolist(), "q": sol.gamma.tolist(), "q_exact": q_ex.tolist()})


# ---------------------------------------------------------------------------
# boundary layer
# ---------------------------------------------------------------------------

def verify_bl_blasius(re=1.0e6):
    t0 = time.time()
    env = BLEnvironment(reynolds=re, mach1=0.0, ncrit=100.0)
    n = 160
    xi = np.linspace(0.005, 1.0, n)
    srf = Surface("flat", np.arange(n), xi, xi, 0 * xi, xi, n)
    th0 = 0.664 * math.sqrt(xi[0] / re)
    A, th, m, ue, typ = BoundaryLayerSolver(env).march(srf, np.ones(n), init=(th0, 2.59 * th0))
    st = station_vars(A, th, m, ue, typ, env)
    th_ex = 0.664 * np.sqrt(xi / re)
    cf_ex = 0.664 / np.sqrt(xi * re)
    e_th = float(abs(th[-1] / th_ex[-1] - 1))
    e_cf = float(abs(st.cf[-1] / cf_ex[-1] - 1))
    e_h = float(abs(st.h[-1] / 2.591 - 1))
    err = max(e_th, e_cf, e_h)
    return _case("bl_blasius",
                 "Laminar flat-plate boundary layer at Re_x = 10^6 (transition suppressed): "
                 "momentum thickness, skin friction and shape factor against Blasius.",
                 "Blasius similarity solution (theta = 0.664 x/sqrt(Re_x), H = 2.591)",
                 "max relative error (theta, Cf, H)", err, 0.03, t0,
                 {"theta_ratio": float(th[-1] / th_ex[-1]), "cf_ratio": float(st.cf[-1] / cf_ex[-1]),
                  "H": float(st.h[-1])},
                 {"x": xi[::4].tolist(), "theta": th[::4].tolist(), "theta_exact": th_ex[::4].tolist()})


def verify_bl_hiemenz():
    """Stagnation-point similarity station vs the Hiemenz solution."""
    t0 = time.time()
    re = 1.0e6
    env = BLEnvironment(reynolds=re, mach1=0.0)
    n = 30
    xi = np.linspace(0.02, 0.2, n)          # Re_theta ~ 6-60 (above the Re_theta >= 1 clamp)
    srf = Surface("stag", np.arange(n), xi, xi, 0 * xi, xi, n)
    A, th, m, ue, typ = BoundaryLayerSolver(env).march(srf, 1.0 * xi)
    st = station_vars(A, th, m, ue, typ, env)
    # Hiemenz: theta sqrt(a/nu) = 0.2923, H = 2.216 with ue = a x, a = 1, nu = 1/Re
    th_ex = 0.2923 / math.sqrt(re)
    e_th = abs(th[0] / th_ex - 1)
    e_h = abs(st.h[0] / 2.216 - 1)
    return _case("bl_hiemenz",
                 "Stagnation-point (similarity) station for ue = a x against the Hiemenz "
                 "plane stagnation-point flow.",
                 "Hiemenz solution (theta sqrt(a/nu) = 0.2923, H = 2.216)",
                 "max relative error (theta, H)", float(max(e_th, e_h)), 0.05, t0,
                 {"theta_ratio": float(th[0] / th_ex), "H": float(st.h[0]),
                  "theta_constant_along_xi": float(np.ptp(th[:10]) / th[0])})


def coles_fernholz_cf(re_theta):
    return 2.0 / ((1.0 / 0.384) * np.log(re_theta) + 4.127) ** 2


def verify_bl_turbulent(re=1.0e7):
    """Turbulent flat plate (transition forced near the LE) vs Coles-Fernholz."""
    t0 = time.time()
    env = BLEnvironment(reynolds=re, mach1=0.0, ncrit=9.0)
    n = 200
    xi = np.geomspace(2e-3, 1.0, n)
    srf = Surface("flat", np.arange(n), xi, xi, 0 * xi, xi, 5)
    th0 = 0.664 * math.sqrt(xi[0] / re)
    A, th, m, ue, typ = BoundaryLayerSolver(env).march(srf, np.ones(n), init=(th0, 2.59 * th0))
    st = station_vars(A, th, m, ue, typ, env)
    sel = (xi > 0.1) & (typ == 2)
    ref = coles_fernholz_cf(st.rt[sel])
    err = np.abs(st.cf[sel] / ref - 1)
    return _case("bl_turbulent_flatplate",
                 "Turbulent flat-plate boundary layer (Re_L = 10^7, transition forced at the "
                 "leading edge): skin friction against the Coles-Fernholz correlation for "
                 "Re_theta between about 2000 and 13000, plus the equilibrium shape factor.",
                 "Coles-Fernholz: Cf = 2 / (ln(Re_theta)/0.384 + 4.127)^2",
                 "max relative error in Cf", float(err.max()), 0.08, t0,
                 {"re_theta_range": [float(st.rt[sel].min()), float(st.rt[sel].max())],
                  "H_end": float(st.h[-1])},
                 {"re_theta": st.rt[sel][::5].tolist(), "cf": st.cf[sel][::5].tolist(),
                  "cf_ref": ref[::5].tolist()})


def verify_bl_transition(re=5.0e6):
    """Free transition on a flat plate (N_crit = 9) vs Michel's empirical criterion."""
    t0 = time.time()
    env = BLEnvironment(reynolds=re, mach1=0.0, ncrit=9.0)
    n = 400
    xi = np.linspace(2e-3, 1.0, n)
    srf = Surface("flat", np.arange(n), xi, xi, 0 * xi, xi, n)
    th0 = 0.664 * math.sqrt(xi[0] / re)
    A, th, m, ue, typ = BoundaryLayerSolver(env).march(srf, np.ones(n), init=(th0, 2.59 * th0))
    k = int(np.argmax(typ == 2))
    rex = xi[k] * re
    rth = 0.664 * math.sqrt(rex)
    michel = 1.174 * (1.0 + 22400.0 / rex) * rex ** 0.46
    err = abs(rth / michel - 1.0)
    return _case("bl_transition_michel",
                 "Natural transition on a flat plate predicted by the e^N envelope method "
                 "(N_crit = 9) compared with Michel's empirical transition criterion (a "
                 "validation check: the two models are independent).",
                 "Michel (1951): Re_theta,tr = 1.174 (1 + 22400/Re_x) Re_x^0.46",
                 "relative difference in Re_theta at transition", float(err), 0.2, t0,
                 {"re_x_transition": float(rex), "re_theta_transition": float(rth),
                  "re_theta_michel": float(michel)})


# ---------------------------------------------------------------------------
# losses
# ---------------------------------------------------------------------------

def incompressible_mixed_out_loss(theta, dstar, pitch, beta1, beta2):
    """Exact incompressible constant-area mixing loss (closed form).

    Edge flow at angle beta2 with speed V_e outside wakes of displacement and
    momentum thickness dstar, theta (measured normal to the flow).  Returns
    omega = (p01 - p0_mixed) / (0.5 rho V1^2).
    """
    c, sn = math.cos(math.radians(beta2)), math.sin(math.radians(beta2))
    d, t = dstar / pitch, theta / pitch
    zeta = 2.0 * (-(c - d - t) * c + (c - d) ** 2 + 0.5 - 0.5 * (c - d) ** 2
                  - 0.5 * (c - d - t) ** 2 * sn ** 2 / (c - d) ** 2)
    ve_v1 = math.cos(math.radians(beta1)) / (c - d)
    return zeta * ve_v1 ** 2


def verify_loss_mixing():
    """Compressible mixed-out analysis (M1 -> 0) vs the exact incompressible closed form."""
    t0 = time.time()
    cases = [(0.002, 1.8, 1.1, 45.0, 20.0), (0.004, 2.0, 1.2, 50.0, 25.0),
             (0.003, 1.5, 1.0, 30.0, 10.0), (0.006, 2.5, 1.4, 55.0, 30.0)]
    errs, out = [], []
    for th, H, sig, b1, b2 in cases:
        s = 1.0 / sig
        lb = cascade_mixed_out_loss(0.01, b1, b2, s, H * th, th, 0.0)
        ref = incompressible_mixed_out_loss(th, H * th, s, b1, b2)
        lr = lieblein_loss(th, 1.0, sig, b1, b2)       # far-wake (H = 1) leading-order form
        errs.append(abs(lb.omega / ref - 1.0))
        out.append({"theta_c": th, "H": H, "solidity": sig, "beta1": b1, "beta2": b2,
                    "omega": lb.omega, "omega_exact_incompressible": ref,
                    "omega_lieblein_H1": lr})
    return _case("loss_mixing",
                 "Mixed-out loss of the compressible control-volume analysis in the "
                 "incompressible limit (M1 = 0.01) against the exact closed-form solution of "
                 "incompressible constant-area wake mixing (its first-order term is the "
                 "Lieblein & Roudebush expression 2 (theta/c) (sigma/cos b2) (cos b1/cos b2)^2).",
                 "Closed-form incompressible mixing analysis; Lieblein & Roudebush (1956)",
                 "max relative difference", float(max(errs)), 2e-3, t0, {"cases": out})


def verify_loss_conservation():
    t0 = time.time()
    g = 1.4
    mdot, fx, fy = fluxes_of_uniform(0.6, 30.0, 0.9, g)
    st = mixed_out(mdot, fx, fy, 1.0 / (g - 1.0), 0.9, g)
    e1 = abs(st.mach - 0.6) + abs(st.angle - 30.0) / 30.0 + abs(st.p0 * g - 1.0)
    lb = cascade_mixed_out_loss(0.5, 40.0, 20.0, 0.9, 0.0, 0.0, 0.0)
    e2 = abs(lb.omega)
    return _case("loss_conservation",
                 "Mixed-out state of an already uniform flow must reproduce it exactly, and a "
                 "cascade without boundary layers must have zero mixed-out loss.",
                 "Conservation of mass, momentum and energy",
                 "max error", float(max(e1, e2)), 1e-9, t0,
                 {"uniform_error": e1, "zero_bl_loss": e2})


# ---------------------------------------------------------------------------
# Euler solver
# ---------------------------------------------------------------------------

def verify_euler_freestream():
    from .euler import EulerOptions, EulerSolver, HGrid
    t0 = time.time()
    ni, nj, s = 60, 20, 1.0
    x = np.linspace(-1.0, 2.0, ni + 1)
    ylo = 0.3 * np.sin(2.0 * x) + 0.4 * x
    X = np.repeat(x[:, None], nj + 1, 1)
    Y = ylo[:, None] + s * np.linspace(0.0, 1.0, nj + 1)[None, :] ** 1.3
    grid = HGrid(X, Y, np.zeros(ni, bool), np.zeros(ni, bool), s, None, 0, ni, {})
    es = EulerSolver(grid, 30.0, 0.5, opts=EulerOptions(), p_exit=float(gas.p_ratio(0.5)) / 1.4)
    es.initialise(30.0)
    es.run(max_steps=50, tol=0.0)
    R = es.residual(es.U)
    err = float(np.abs(R).max())
    return _case("euler_freestream",
                 "Free-stream preservation of the finite-volume Euler scheme on a skewed, "
                 "non-uniform periodic grid (uniform flow must remain an exact steady state).",
                 "Discrete conservation / geometric conservation law",
                 "max residual after 50 steps", err, 1e-12, t0, {"grid": [ni, nj]})


def nozzle_area(x):
    return 1.0 + 2.2 * (x - 1.5) ** 2


def nozzle_shock_exact(p_exit_ratio, gamma=1.4):
    """Normal-shock position in the nozzle A = 1 + 2.2 (x - 1.5)^2 for p_exit/p0."""
    ae = nozzle_area(3.0)

    def pe_of(xs):
        m1 = gas.mach_from_area_ratio(nozzle_area(xs), gamma, supersonic=True)
        m2, _, p0r = gas.normal_shock(m1, gamma)
        me = gas.mach_from_area_ratio(ae * p0r, gamma, supersonic=False)
        return float(p0r * gas.p_ratio(me, gamma)), m1, float(p0r)

    lo, hi = 1.5 + 1e-6, 3.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        pe, _, _ = pe_of(mid)
        if pe > p_exit_ratio:
            lo = mid           # shock further downstream lowers exit pressure
        else:
            hi = mid
    xs = 0.5 * (lo + hi)
    _, m1, p0r = pe_of(xs)
    return xs, m1, p0r


def verify_euler_nozzle(p_exit_ratio=0.6784, ni=150):
    """Quasi-1-D Laval nozzle with a normal shock (streamtube-thickness formulation)."""
    from .euler import EulerOptions, EulerSolver, HGrid
    t0 = time.time()
    x = np.linspace(0.0, 3.0, ni + 1)
    grid = HGrid.channel(x, np.zeros_like(x), 0.3 * np.ones_like(x), 3, b_nodes=nozzle_area(x))
    opts = EulerOptions(cfl=1.0, irs=0.0, k2=0.8, shock_switch_mach=0.0, max_steps=8000,
                        tol=1e-5, mass_tol=1e-4)
    es = EulerSolver(grid, 0.0, 0.3, opts=opts, p_exit=p_exit_ratio / 1.4)
    # initial state: the exact flow structure but with the shock displaced 0.25 downstream;
    # the solver has to move the shock to the position set by the exit pressure
    xc = grid.xc[:, 0]
    xs_ex0, _, _ = nozzle_shock_exact(p_exit_ratio)
    xs0 = xs_ex0 + 0.25
    m_s = gas.mach_from_area_ratio(nozzle_area(xs0), supersonic=True)
    p0r0 = float(gas.normal_shock(m_s)[2])
    M0, P0 = [], []
    for xx in xc:
        if xx < xs0:
            M0.append(gas.mach_from_area_ratio(nozzle_area(xx), supersonic=xx > 1.5))
            P0.append(1.0)
        else:
            M0.append(gas.mach_from_area_ratio(nozzle_area(xx) * p0r0, supersonic=False))
            P0.append(p0r0)
    M0, P0 = np.array(M0), np.array(P0)
    T = gas.t_ratio(M0)
    p = P0 * gas.p_ratio(M0) / 1.4
    rho = 1.4 * p / T
    u = M0 * np.sqrt(T)
    U = np.zeros((4, grid.ni, grid.nj))
    U[0] = rho[:, None]
    U[1] = (rho * u)[:, None]
    U[3] = (p / 0.4 + 0.5 * rho * u * u)[:, None]
    es.U = U
    es.run()
    rho_n, u_n, v_n, p_n = es.primitives()
    pn = p_n[:, 1] * 1.4
    Mn = np.sqrt(u_n[:, 1] ** 2 + v_n[:, 1] ** 2) / np.sqrt(1.4 * p_n[:, 1] / rho_n[:, 1])
    xs_ex, m1_ex, p0r_ex = nozzle_shock_exact(p_exit_ratio)
    # numerical shock position: steepest pressure rise downstream of the throat
    dp = np.diff(pn)
    k = int(np.argmax(np.where(xc[:-1] > 1.6, dp, -np.inf)))
    xs_num = 0.5 * (xc[k] + xc[k + 1])
    p0_exit = float(pn[-3] * (1 + 0.2 * Mn[-3] ** 2) ** 3.5)
    e_pos = abs(xs_num - xs_ex) / 3.0
    e_p0 = abs(p0_exit - p0r_ex) / p0r_ex
    # exact pressure distribution for the plot
    pex = []
    for xx in xc:
        if xx < xs_ex:
            mm = gas.mach_from_area_ratio(nozzle_area(xx), supersonic=xx > 1.5)
            pex.append(float(gas.p_ratio(mm)))
        else:
            mm = gas.mach_from_area_ratio(nozzle_area(xx) * p0r_ex, supersonic=False)
            pex.append(float(p0r_ex * gas.p_ratio(mm)))
    return _case("euler_nozzle_shock",
                 "Quasi-one-dimensional Laval nozzle A(x) = 1 + 2.2 (x - 1.5)^2 with exit "
                 "pressure p_e/p0 = 0.6784, solved with the 2-D Euler code using the MISES "
                 "streamtube-thickness term; normal-shock position and total-pressure loss "
                 "against the exact quasi-1-D solution.",
                 "Exact quasi-1-D isentropic + Rankine-Hugoniot solution",
                 "max(shock position error / length, p0 error)", float(max(e_pos, e_p0)), 0.02, t0,
                 {"x_shock_exact": xs_ex, "x_shock_euler": float(xs_num), "M_preshock_exact": m1_ex,
                  "p0_ratio_exact": p0r_ex, "p0_ratio_euler": p0_exit,
                  "steps": es.last_run["steps"]},
                 {"x": xc.tolist(), "p": pn.tolist(), "p_exact": pex})


def verify_euler_vs_panel(mach=0.2):
    """Low-Mach Euler against the panel method on a compressor cascade (inviscid)."""
    from .euler import EulerOptions
    from .solver import CascadeSolver, FlowConditions, ViscousOptions
    t0 = time.time()
    b = Blade.from_parameters(45.0, 15.0, 0.08, pitch=0.9, thickness_form="c4")
    fl = FlowConditions(inlet_mach=mach, inlet_angle=43.0, reynolds=5e5)
    # tight convergence so the reported spurious loss is the scheme's, not the iteration's
    eo = EulerOptions(tol=1e-4, mass_tol=5e-5, max_steps=20000)
    re = CascadeSolver(b, fl, ViscousOptions(enabled=False), method="euler", euler=eo).solve()
    fl2 = FlowConditions(inlet_mach=re.performance["M1_actual"], inlet_angle=43.0, reynolds=5e5)
    rp = CascadeSolver(b, fl2, ViscousOptions(enabled=False), method="panel").solve()
    xs = np.linspace(0.05, 0.95, 19)
    d = []
    for se, sp in ((re.upper, rp.upper), (re.lower, rp.lower)):
        o1 = np.argsort(se.xc)
        o2 = np.argsort(sp.xc)
        d.append(np.interp(xs, se.xc[o1], se.mis[o1]) - np.interp(xs, sp.xc[o2], sp.mis[o2]))
    d = np.concatenate(d)
    mis_ref = float(np.mean(np.concatenate([rp.upper.mis, rp.lower.mis])))
    err_mis = float(np.sqrt(np.mean(d ** 2)) / mis_ref)
    err_b2 = abs(re.performance["beta2"] - rp.performance["beta2"])
    return _case("euler_vs_panel",
                 "Code-to-code comparison at low Mach number (M1 = 0.2, inviscid): the "
                 "finite-volume Euler solution against the independent panel method on the "
                 "C4 compressor cascade (surface isentropic Mach number and exit angle); also "
                 "reports the spurious (numerical) total-pressure loss of the Euler scheme.",
                 "Panel method (verified against exact solutions above)",
                 "RMS difference in Mis / mean Mis", err_mis, 0.03, t0,
                 {"exit_angle_difference_deg": err_b2, "euler_numerical_loss": re.performance["omega"],
                  "euler_steps": re.convergence["euler_steps"]},
                 {"xc_upper_euler": re.upper.xc.tolist(), "mis_upper_euler": re.upper.mis.tolist(),
                  "xc_lower_euler": re.lower.xc.tolist(), "mis_lower_euler": re.lower.mis.tolist(),
                  "xc_upper_panel": rp.upper.xc.tolist(), "mis_upper_panel": rp.upper.mis.tolist(),
                  "xc_lower_panel": rp.lower.xc.tolist(), "mis_lower_panel": rp.lower.mis.tolist()})


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

QUICK_CASES = [verify_panel_manufactured, verify_panel_convergence, verify_panel_joukowski,
               verify_bl_blasius, verify_bl_hiemenz, verify_bl_turbulent, verify_bl_transition,
               verify_loss_mixing, verify_loss_conservation, verify_euler_freestream]
SLOW_CASES = [verify_euler_nozzle, verify_euler_vs_panel]


def run_all(quick=False, progress=None):
    cases = QUICK_CASES + ([] if quick else SLOW_CASES)
    out = []
    for fn in cases:
        try:
            res = fn()
        except Exception as exc:  # report failures instead of aborting the suite
            res = CaseResult(fn.__name__.replace("verify_", ""), fn.__doc__ or "", "", "error",
                             float("nan"), 0.0, False, 0.0, {"error": repr(exc)})
        out.append(res)
        if progress:
            progress(res)
    return out


def write_report(results, directory):
    import json
    from pathlib import Path
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    js = d / "verification.json"
    js.write_text(json.dumps([_clean(r.to_dict()) for r in results], indent=1))
    lines = ["# pymises verification report", "",
             f"{sum(r.passed for r in results)} of {len(results)} cases passed.", "",
             "| case | metric | value | tolerance | result |", "|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r.name} | {r.metric} | {r.value:.3e} | {r.tolerance:.1e} | "
                     f"{'pass' if r.passed else 'FAIL'} |")
    lines.append("")
    for r in results:
        lines += [f"## {r.name}", "", r.description, "", f"Reference: {r.reference}", ""]
        for k, v in r.details.items():
            lines.append(f"- {k}: {v}")
        lines.append("")
    md = d / "verification.md"
    md.write_text("\n".join(lines))
    return [js, md]


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return o
