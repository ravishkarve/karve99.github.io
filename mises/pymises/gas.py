"""Perfect-gas relations used throughout pymises.

All functions are vectorised with NumPy and work on scalars or arrays.
Non-dimensionalisation convention used by the solvers:

* stagnation density ``rho0 = 1`` and stagnation speed of sound ``a0 = 1``
* hence stagnation pressure ``p0 = 1/gamma`` and stagnation enthalpy
  ``h0 = 1/(gamma-1)``.
"""
from __future__ import annotations

import numpy as np

GAMMA_AIR = 1.4


def t_ratio(mach, gamma=GAMMA_AIR):
    """Static-to-stagnation temperature ratio T/T0."""
    return 1.0 / (1.0 + 0.5 * (gamma - 1.0) * np.asarray(mach) ** 2)


def p_ratio(mach, gamma=GAMMA_AIR):
    """Static-to-stagnation pressure ratio p/p0 (isentropic)."""
    return t_ratio(mach, gamma) ** (gamma / (gamma - 1.0))


def rho_ratio(mach, gamma=GAMMA_AIR):
    """Static-to-stagnation density ratio rho/rho0 (isentropic)."""
    return t_ratio(mach, gamma) ** (1.0 / (gamma - 1.0))


def mach_from_p_ratio(p_over_p0, gamma=GAMMA_AIR):
    """Isentropic Mach number from p/p0 (clipped to non-negative)."""
    pr = np.clip(np.asarray(p_over_p0, dtype=float), 1e-12, 1.0)
    arg = pr ** (-(gamma - 1.0) / gamma) - 1.0
    return np.sqrt(np.maximum(2.0 / (gamma - 1.0) * arg, 0.0))


def speed_over_a0(mach, gamma=GAMMA_AIR):
    """Flow speed divided by stagnation speed of sound, q/a0."""
    m = np.asarray(mach)
    return m * np.sqrt(t_ratio(m, gamma))


def mach_from_speed(q_over_a0, gamma=GAMMA_AIR):
    """Mach number from q/a0 (inverse of :func:`speed_over_a0`)."""
    q2 = np.asarray(q_over_a0, dtype=float) ** 2
    denom = np.maximum(1.0 - 0.5 * (gamma - 1.0) * q2, 1e-12)
    return np.sqrt(q2 / denom)


def mass_flow_function(mach, gamma=GAMMA_AIR):
    """Non-dimensional mass flow  mdot*a0/(A*p0) = gamma*M*(T/T0)^((g+1)/(2(g-1)))."""
    m = np.asarray(mach)
    return gamma * m * t_ratio(m, gamma) ** ((gamma + 1.0) / (2.0 * (gamma - 1.0)))


def mach_from_mass_flow_function(value, gamma=GAMMA_AIR, supersonic=False):
    """Invert :func:`mass_flow_function` by bisection.

    Returns ``nan`` when ``value`` exceeds the choking limit.
    """
    fmax = float(mass_flow_function(1.0, gamma))
    if value > fmax * (1.0 + 1e-12):
        return float("nan")
    lo, hi = (1.0, 50.0) if supersonic else (0.0, 1.0)
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        f = float(mass_flow_function(mid, gamma))
        if (f < value) != supersonic:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def karman_tsien_cp(cp_incompressible, mach_ref):
    """Karman-Tsien compressibility correction of a pressure coefficient."""
    beta = np.sqrt(1.0 - mach_ref ** 2)
    cpi = np.asarray(cp_incompressible)
    return cpi / (beta + mach_ref ** 2 / (1.0 + beta) * 0.5 * cpi)


def sutherland_ratio(t_over_tref, tref=288.15, s=110.4):
    """Sutherland viscosity ratio mu/mu_ref for T/T_ref."""
    tr = np.asarray(t_over_tref)
    return tr ** 1.5 * (tref + s) / (tr * tref + s)


def normal_shock(mach1, gamma=GAMMA_AIR):
    """Rankine-Hugoniot normal shock: returns (M2, p2/p1, p02/p01)."""
    m1 = np.asarray(mach1, dtype=float)
    g = gamma
    m2 = np.sqrt((1 + 0.5 * (g - 1) * m1 ** 2) / (g * m1 ** 2 - 0.5 * (g - 1)))
    p21 = 1 + 2 * g / (g + 1) * (m1 ** 2 - 1)
    p0ratio = (((g + 1) * m1 ** 2 / ((g - 1) * m1 ** 2 + 2)) ** (g / (g - 1))
               * ((g + 1) / (2 * g * m1 ** 2 - (g - 1))) ** (1 / (g - 1)))
    return m2, p21, p0ratio


def area_ratio(mach, gamma=GAMMA_AIR):
    """Isentropic area ratio A/A* for a given Mach number."""
    m = np.asarray(mach, dtype=float)
    g = gamma
    return (1.0 / m) * ((2.0 / (g + 1)) * (1 + 0.5 * (g - 1) * m ** 2)) ** ((g + 1) / (2 * (g - 1)))


def mach_from_area_ratio(ar, gamma=GAMMA_AIR, supersonic=False):
    """Invert :func:`area_ratio` by bisection."""
    if ar < 1.0:
        return float("nan")
    lo, hi = (1.0, 20.0) if supersonic else (1e-6, 1.0)
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        f = float(area_ratio(mid, gamma))
        if supersonic:
            lo, hi = (mid, hi) if f < ar else (lo, mid)
        else:
            lo, hi = (lo, mid) if f < ar else (mid, hi)
    return 0.5 * (lo + hi)
