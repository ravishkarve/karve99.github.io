"""Inverse design: Betz minimum-induced-loss loading carried at ideal incidence.

Given a planform (chord, thickness, sweep) and a design point, the blade is designed the way
high-speed propellers are designed:

1. **Loading.**  The circulation is the Betz optimum - the wake sheet moves aft rigidly at
   w - in the closed form of Betz and Prandtl (as in Adkins & Liebeck's design method):
       B Gamma = 2 pi r F w sin(phi) cos(phi),   tan phi = (V + w/2)/(Omega r),
   with Prandtl's tip function F standing for Goldstein's; the spinner continues the wake
   sheet (hub images), so there is no hub loss.  (Inverting the lifting-line influence
   matrices for the Betz velocities instead is ill-posed for a finite number of blades: it
   returns a wavy circulation.)
2. **Camber and twist.**  Every section carries its design lift at ideal incidence (zero
   leading-edge singularity in the compressible, swept row), which fixes both the design
   lift coefficient (camber) and the angle of attack; the blade angle is phi + alpha, with
   phi from the lifting-line analysis of the designed loading.
3. **Trim.**  w is adjusted so that the analysed propeller absorbs the design power
   coefficient with no collective offset.
"""
from __future__ import annotations

import numpy as np

from .geometry import Propeller
from .solver import OperatingPoint, PropellerSolver


def betz_circulation(sv: PropellerSolver, geo, V, Omega, w):
    """Betz-Prandtl optimum circulation  B Gamma = 2 pi r F w sin(phi) cos(phi)  (free-stream
    helicoid: the potential-flow interaction with the spinner does no net work on the system,
    so it does not enter the optimum)."""
    r = geo["r"]
    R = sv.prop.radius
    B = sv.prop.blades
    phi = np.arctan2(V + 0.5 * w, Omega * r)
    phi_t = np.arctan2(V + 0.5 * w, Omega * R)
    f = 0.5 * B * (R - r) / (R * np.sin(phi_t))
    F = 2.0 / np.pi * np.arccos(np.exp(-np.maximum(f, 0.0)))
    return 2.0 * np.pi * r * F * w * np.sin(phi) * np.cos(phi) / B


def _ideal_section(sv, geo, ctrl_phi, M, beta_guess):
    """Normal-plane row data and the ideal-incidence relations at the control points, with
    the same effective (Kuchemann) sweep as the analysis."""
    npl = sv._normal_plane(geo, ctrl_phi, beta_guess)
    Mn = M * np.cos(npl.sweep)
    if sv.st.relief_3d:
        Mn = np.sqrt(np.maximum(Mn * Mn - sv._relief_wavenumber(geo, npl) ** 2, 0.0) + 1e-6)
    beta_n = np.sqrt(1.0 - np.minimum(Mn, sv.section_options.mach_a) ** 2)
    sol = sv.section.lattice(npl.sigma_n, npl.xi_n, beta_n)
    return npl, beta_n, sol


def design(prop: Propeller, op: OperatingPoint, CP, viscous_factor=0.93, iterations=4, verbose=False,
           solver_kw=None, tip_relief=0.0, relief_width=0.1):
    """Design camber and twist of ``prop`` in place for power coefficient ``CP`` at ``op``.

    ``tip_relief`` unloads the tip (fraction of the Betz circulation removed at r = R,
    decaying over ``relief_width`` R inboard), trading a little induced loss for lower
    compressibility losses on the outer sections, as propfan designs do.
    """
    solver_kw = solver_kw or {}
    bl = prop.blade
    D = prop.diameter
    w_lo = None
    w = None
    history = []
    for it in range(iterations + 4):
        sv = PropellerSolver(prop, **solver_kw)
        atm, V, n = op.resolve(D)
        Omega = 2.0 * np.pi * n
        geo = sv._geometry(0.0)
        nacflow = sv._nacelle(op.mach, D)
        ctrl = geo["ctrl"]
        if nacflow is not None:
            fr = np.linspace(-0.45, 0.45, 7)
            xs = ctrl["x_mid"][None, :] + fr[:, None] * ctrl["chord"][None, :] * np.sin(ctrl["beta"])[None, :]
            u_nac = nacflow.axial(xs, np.broadcast_to(geo["r"], xs.shape)).mean(axis=0)
        else:
            u_nac = np.zeros(sv.N)
        if w is None:
            # actuator-disk estimate of the wake displacement velocity from CP (eta ~ 0.8)
            T = 0.8 * CP * atm.rho * n ** 3 * D ** 5 / max(V, 1e-6)
            A_disk = np.pi * (0.25 * D * D) * (1 - bl.hub_ratio ** 2)
            w = 2.0 * (-V + np.sqrt(V * V + 2.0 * T / (atm.rho * A_disk))) / 2.0
        gamma = betz_circulation(sv, geo, V, Omega, w)
        xr = geo["r"] / prop.radius
        gamma = gamma * (1.0 - tip_relief * np.exp(-(1.0 - xr) / relief_width))
        Aa, At, _, _ = sv._influence(geo, gamma, V, Omega, op.mach, nacflow)
        ua, ut = Aa @ gamma, At @ gamma
        G, s = sv._sections(geo, ua, ut, V, Omega, atm, u_nac)
        phi, W, M = s["phi"], s["W"], s["M"]
        npl, beta_n, sol = _ideal_section(sv, geo, phi, M, phi)
        # required normal-plane lift: Gamma = 0.5 W_n c_n CL_n
        cl_n_req = 2.0 * gamma / (W * np.cos(npl.sweep) * ctrl["chord"] * npl.chord_ratio) / viscous_factor
        A0 = sol.A[:, 0, :]
        cu = sol.cl_unit
        # ideal incidence: alpha = -(A0_c cld + A0_t tau)/A0_a ; lift linear in cld
        a_c = -A0[:, 1] / A0[:, 0]
        a_t = -A0[:, 2] / A0[:, 0]
        lift_per_cld = (cu[:, 0] * a_c + cu[:, 1]) / beta_n
        lift_tau = (cu[:, 0] * a_t + cu[:, 2]) * npl.tau_n / beta_n
        cld_n = (cl_n_req - lift_tau) / lift_per_cld
        alpha_n = a_c * cld_n + a_t * npl.tau_n
        alpha = np.arctan(np.tan(alpha_n) * np.cos(npl.sweep))
        beta = phi + alpha
        cld = cld_n * npl.chord_ratio
        x = geo["r"] / prop.radius
        bl.beta_deg = _extrap(bl.r_R, x, np.degrees(beta))
        bl.cl_design = np.maximum(_extrap(bl.r_R, x, cld), 0.0)
        res = sv.__class__(prop, **solver_kw).solve(op)
        history.append((w, res.CP, res.eta))
        if verbose:
            print(f"design {it}: w/V {w / V:.4f}  CP {res.CP:.4f}  eta {res.eta:.4f}  "
                  f"CLi {bl.integrated_design_cl():.4f}  beta75 {prop.beta_ref():.2f}")
        if abs(res.CP / CP - 1.0) < 2e-3:
            break
        # secant on w for the power coefficient
        if len(history) >= 2:
            (w0, c0, _), (w1, c1, _) = history[-2], history[-1]
            w = w1 + (CP - c1) * (w1 - w0) / (c1 - c0) if c1 != c0 else w1 * CP / c1
        else:
            w = w * (CP / res.CP) ** 0.8
    return prop, res


def _extrap(xq, x, y):
    """Interpolate y(x) at xq with linear extrapolation beyond the ends."""
    out = np.interp(xq, x, y)
    lo = xq < x[0]
    hi = xq > x[-1]
    if lo.any():
        out[lo] = y[0] + (y[1] - y[0]) / (x[1] - x[0]) * (xq[lo] - x[0])
    if hi.any():
        out[hi] = y[-1] + (y[-1] - y[-2]) / (x[-1] - x[-2]) * (xq[hi] - x[-1])
    return out
