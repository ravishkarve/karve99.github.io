"""Inflow turbulence models for leading-edge (rotor-wake interaction) noise.

Two-wavenumber upwash spectra Phi_ww(k1, k2) of isotropic turbulence
(normalised so that the double integral over all k1, k2 equals w_rms^2):

* von Karman:
    Phi = 4/(9 pi) w^2/ke^2 (k1h^2 + k2h^2) / (1 + k1h^2 + k2h^2)^(7/3),
    kih = ki/ke,  ke = sqrt(pi)/Lambda * Gamma(5/6)/Gamma(1/3)
* Liepmann:
    Phi = 3 w^2 Lambda^2/(4 pi) Lambda^2 (k1^2+k2^2) / (1 + Lambda^2 (k1^2+k2^2))^(5/2)

Rotor-wake turbulence (front rotor of a contra-rotating open rotor, CROR).
The rear-rotor blades see turbulence confined to the front-rotor wakes.  With
a Gaussian profile of turbulence intensity across each wake,

    w_rms^2(xi) = w_c^2 exp(-ln2 (xi/Lw)^2),   Lw = wake semi-width (half width at half maximum)

periodically repeated with the front-rotor blade pitch s1 = 2 pi r / B1, the
turbulent field is a stationary field w_s modulated by a periodic envelope
e(xi):  w = e(xi) w_s.  Both are frozen in the fluid, so the wavenumber
spectrum of the modulated field is

    Phi(k1, k2) = sum_m |E_m|^2 Phi_s(k1 - m k_w, k2),
    |E_m|^2 = w_c^2 (pi/a) / s1^2 exp(-2 pi^2 m^2 / (a s1^2)),  a = ln2/(2 Lw^2)

and k_w U = m B1 (Omega1 + Omega2) (the wake-passing frequency seen by a
rear blade).  Summing |E_m|^2 over m gives the passage-averaged mean square
w_c^2 (Lw/s1) sqrt(pi/ln2), which is the "averaged" (homogeneous) model.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import gamma

__all__ = ["VonKarman", "Liepmann", "make_spectrum", "WakeTurbulence", "HomogeneousTurbulence"]

LN2 = np.log(2.0)


@dataclass
class VonKarman:
    """Isotropic von Karman spectrum (w_rms [m/s], integral length scale Lambda [m])."""
    w_rms: float
    Lambda: float
    name: str = "von Karman"

    @property
    def ke(self):
        return np.sqrt(np.pi) / self.Lambda * gamma(5.0 / 6.0) / gamma(1.0 / 3.0)

    def phi_ww(self, k1, k2):
        ke = self.ke
        a = (np.asarray(k1) / ke) ** 2 + (np.asarray(k2) / ke) ** 2
        return 4.0 / (9.0 * np.pi) * self.w_rms ** 2 / ke ** 2 * a / (1.0 + a) ** (7.0 / 3.0)

    def phi_1d(self, k1):
        """One-dimensional upwash spectrum Theta_ww(k1) = int Phi_ww(k1, k2) dk2."""
        return _phi_1d(self, k1)


@dataclass
class Liepmann:
    """Isotropic Liepmann spectrum (w_rms [m/s], integral length scale Lambda [m])."""
    w_rms: float
    Lambda: float
    name: str = "Liepmann"

    def phi_ww(self, k1, k2):
        L = self.Lambda
        a = L * L * (np.asarray(k1) ** 2 + np.asarray(k2) ** 2)
        return 3.0 * self.w_rms ** 2 * L * L / (4.0 * np.pi) * a / (1.0 + a) ** 2.5

    def phi_1d(self, k1):
        """One-dimensional upwash spectrum Theta_ww(k1) = int Phi_ww(k1, k2) dk2."""
        return _phi_1d(self, k1)


def _phi_1d(spec, k1):
    k1 = np.atleast_1d(np.asarray(k1, float))
    t = np.sinh(np.linspace(-12.0, 12.0, 3001)) / spec.Lambda
    return np.trapezoid(spec.phi_ww(k1[:, None], t[None, :]), t, axis=1)


def make_spectrum(kind, w_rms, Lambda):
    """Factory: kind in {'vonkarman', 'von karman', 'vk', 'liepmann', 'lp'}."""
    k = str(kind).lower().replace("_", "").replace("-", "").replace(" ", "")
    if k in ("vonkarman", "vk", "karman", "vonkármán"):
        return VonKarman(w_rms, Lambda)
    if k in ("liepmann", "lp", "liepman"):
        return Liepmann(w_rms, Lambda)
    raise ValueError(f"unknown turbulence spectrum {kind!r} (use 'vonkarman' or 'liepmann')")


@dataclass
class HomogeneousTurbulence:
    """Homogeneous isotropic inflow turbulence (e.g. grid or atmospheric turbulence)."""
    spectrum: str = "vonkarman"
    intensity: float = 0.05      # w_rms / U_ref
    Lambda: float = 0.03
    U_ref: float | None = None   # reference speed for the intensity; default: blade relative speed

    def phi(self, K1, k2, U_local, radius=None, omega_s=None):
        w = self.intensity * (self.U_ref if self.U_ref else U_local)
        return make_spectrum(self.spectrum, w, self.Lambda).phi_ww(K1, k2)


@dataclass
class WakeTurbulence:
    """Turbulence in the periodic wakes of a front rotor (CROR rotor-wake interaction).

    Parameters are defined at each rear-rotor strip (scalars or callables of
    the radius r):

    B1           front-rotor blade number
    Omega_rel    Omega1 + Omega2 [rad/s] (relative angular speed of the rotors)
    w_c          centreline turbulence rms velocity [m/s] or intensity * U_ref
    Lw_over_s    wake semi-width (half-width at half-maximum of w_rms^2) / front pitch
    Lambda       integral length scale inside the wake [m] (or Lambda_over_Lw)
    model        'periodic' (spectral humps at wake-passing harmonics, cyclostationary
                 envelope) or 'averaged' (passage-averaged homogeneous turbulence)
    """
    B1: int
    Omega_rel: float
    w_c: object = 1.0
    Lw_over_s: object = 0.1
    Lambda: object = None
    Lambda_over_Lw: float = 0.42
    spectrum: str = "vonkarman"
    model: str = "periodic"
    m_max: int = 60

    @staticmethod
    def _val(v, r):
        return v(r) if callable(v) else v

    def wake_params(self, r):
        s1 = 2.0 * np.pi * r / self.B1
        Lw = self._val(self.Lw_over_s, r) * s1
        Lam = self._val(self.Lambda, r) if self.Lambda is not None else self.Lambda_over_Lw * Lw
        wc = self._val(self.w_c, r)
        return s1, Lw, Lam, wc

    def mean_square(self, r):
        """Passage-averaged mean square upwash  w_c^2 (Lw/s1) sqrt(pi/ln2)."""
        s1, Lw, _, wc = self.wake_params(r)
        return wc ** 2 * (Lw / s1) * np.sqrt(np.pi / LN2)

    def envelope_coefficients(self, r):
        """|E_m|^2 for m = -m_max..m_max (sums to the passage-averaged mean square)."""
        s1, Lw, _, wc = self.wake_params(r)
        a = LN2 / (2.0 * Lw ** 2)
        m = np.arange(-self.m_max, self.m_max + 1)
        Em2 = wc ** 2 * (np.pi / a) / s1 ** 2 * np.exp(-2.0 * np.pi ** 2 * m ** 2 / (a * s1 ** 2))
        return m, Em2

    def phi(self, K1, k2, U_local, radius, omega_s=None):
        """Upwash spectrum at chordwise wavenumber K1 = omega_s/U for a strip at ``radius``."""
        s1, Lw, Lam, wc = self.wake_params(radius)
        if self.model == "averaged":
            spec = make_spectrum(self.spectrum, np.sqrt(self.mean_square(radius)), Lam)
            return spec.phi_ww(K1, k2)
        spec = make_spectrum(self.spectrum, 1.0, Lam)
        m, Em2 = self.envelope_coefficients(radius)
        keep = Em2 > Em2.max() * 1e-12
        m, Em2 = m[keep], Em2[keep]
        kw = self.B1 * self.Omega_rel / U_local      # wake-passing wavenumber along the chord
        K1 = np.asarray(K1, float)
        k2 = np.asarray(k2, float)
        out = np.zeros(np.broadcast(K1, k2).shape)
        for mm, e2 in zip(m, Em2):
            out = out + e2 * spec.phi_ww(K1 - mm * kw, k2)
        return out
