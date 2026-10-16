"""Perfect-gas relations and the ISA standard atmosphere.

All functions are vectorised with NumPy and accept scalars or arrays.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

GAMMA = 1.4
R_AIR = 287.05287                  # J/(kg K)
CP_AIR = GAMMA * R_AIR / (GAMMA - 1.0)
G0 = 9.80665


def sutherland(T):
    """Dynamic viscosity of air [Pa s] (Sutherland's law)."""
    T = np.asarray(T, dtype=float)
    return 1.458e-6 * T ** 1.5 / (T + 110.4)


@dataclass(frozen=True)
class Atmosphere:
    """Static state of the undisturbed air."""

    T: float        # K
    p: float        # Pa
    rho: float      # kg/m^3
    a: float        # m/s
    mu: float       # Pa s

    @classmethod
    def isa(cls, altitude=0.0, dT=0.0):
        """ISA (1976) to 32 km, with an optional temperature offset dT [K]."""
        h = float(altitude)
        if h < 0.0 or h > 32000.0:
            raise ValueError("altitude must be within 0 .. 32000 m")
        if h <= 11000.0:
            T_std = 288.15 - 0.0065 * h
            p = 101325.0 * (T_std / 288.15) ** (G0 / (0.0065 * R_AIR))
        elif h <= 20000.0:
            T_std = 216.65
            p = 22632.06 * np.exp(-G0 * (h - 11000.0) / (R_AIR * T_std))
        else:
            T_std = 216.65 + 0.001 * (h - 20000.0)
            p = 5474.889 * (T_std / 216.65) ** (-G0 / (0.001 * R_AIR))
        T = T_std + dT
        rho = p / (R_AIR * T)
        return cls(T=T, p=float(p), rho=float(rho), a=float(np.sqrt(GAMMA * R_AIR * T)),
                   mu=float(sutherland(T)))

    @classmethod
    def from_state(cls, T, p):
        rho = p / (R_AIR * T)
        return cls(T=float(T), p=float(p), rho=float(rho), a=float(np.sqrt(GAMMA * R_AIR * T)),
                   mu=float(sutherland(T)))

    @classmethod
    def from_total(cls, T0, p0, mach):
        """Static state of a stream of Mach number ``mach`` with total conditions T0, p0
        (a wind tunnel)."""
        tr = 1.0 + 0.5 * (GAMMA - 1.0) * mach ** 2
        T = T0 / tr
        p = p0 * tr ** (-GAMMA / (GAMMA - 1.0))
        return cls.from_state(T, p)


def mass_flux_function(M, gamma=GAMMA):
    """Phi(M) = M (1 + (g-1)/2 M^2)^(-(g+1)/(2(g-1))): mass flux per unit area, in units of
    p0 sqrt(gamma/(R T0)).  Phi has its maximum (choking) at M = 1."""
    M = np.asarray(M, dtype=float)
    return M * (1.0 + 0.5 * (gamma - 1.0) * M * M) ** (-(gamma + 1.0) / (2.0 * (gamma - 1.0)))


PHI_STAR = float(mass_flux_function(1.0))


def mach_from_cp(cp, mach, gamma=GAMMA):
    """Local isentropic Mach number from the pressure coefficient (free-stream Mach ``mach``)."""
    cp = np.asarray(cp, dtype=float)
    mach = np.asarray(mach, dtype=float)
    p_ratio = np.maximum(1.0 + 0.5 * gamma * mach ** 2 * cp, 1e-6)              # p / p_inf
    p0_ratio = (1.0 + 0.5 * (gamma - 1.0) * mach ** 2) ** (gamma / (gamma - 1.0))   # p0 / p_inf
    arg = (p0_ratio / p_ratio) ** ((gamma - 1.0) / gamma) - 1.0
    return np.sqrt(np.maximum(2.0 / (gamma - 1.0) * arg, 0.0))


def speed_ratio_from_cp(cp, mach, gamma=GAMMA):
    """Local speed / free-stream speed from the pressure coefficient (isentropic)."""
    cp = np.asarray(cp, dtype=float)
    mach = np.maximum(np.asarray(mach, dtype=float), 1e-6)
    p_ratio = np.maximum(1.0 + 0.5 * gamma * mach ** 2 * cp, 1e-6)
    t_ratio = p_ratio ** ((gamma - 1.0) / gamma)
    q2 = 1.0 + 2.0 / ((gamma - 1.0) * mach ** 2) * (1.0 - t_ratio)
    return np.sqrt(np.maximum(q2, 0.0))


def cp_from_speed_ratio(q, mach, gamma=GAMMA):
    """Isentropic pressure coefficient for a local speed ratio q = V/V_inf."""
    q = np.asarray(q, dtype=float)
    mach = np.maximum(np.asarray(mach, dtype=float), 1e-6)
    t_ratio = np.maximum(1.0 - 0.5 * (gamma - 1.0) * mach ** 2 * (q * q - 1.0), 1e-6)
    p_ratio = t_ratio ** (gamma / (gamma - 1.0))
    return (p_ratio - 1.0) / (0.5 * gamma * mach ** 2)


def cp_sonic(mach, gamma=GAMMA):
    """Critical pressure coefficient (local Mach number one)."""
    m2 = np.maximum(np.asarray(mach, dtype=float) ** 2, 1e-12)
    return 2.0 / (gamma * m2) * (((2.0 + (gamma - 1.0) * m2) / (gamma + 1.0)) ** (gamma / (gamma - 1.0)) - 1.0)


def normal_shock_p0_ratio(M1, gamma=GAMMA):
    """Total pressure ratio p02/p01 across a normal shock (1 for M1 <= 1)."""
    M1 = np.maximum(np.asarray(M1, dtype=float), 1.0)
    g = gamma
    a = ((g + 1.0) * M1 ** 2 / ((g - 1.0) * M1 ** 2 + 2.0)) ** (g / (g - 1.0))
    b = ((g + 1.0) / (2.0 * g * M1 ** 2 - (g - 1.0))) ** (1.0 / (g - 1.0))
    return a * b
