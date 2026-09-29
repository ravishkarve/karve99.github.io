"""Blade-element noise sources feeding the rotor radiation formulations.

A source provides the effective force PSD S_F(omega_s, qbar, ky) of one blade
element (see :mod:`bbnoise.airfoil`) and the factor that converts the model's
native spectral convention to a one-sided PSD per hertz:

* LE / rotor-wake interaction: the upwash spectra are two-sided in wavenumber,
  so S_pp is two-sided per rad/s -> G(f) = 4 pi S_pp.
* TE / self noise: the wall-pressure models are one-sided per rad/s
  -> G(f) = 2 pi S_pp.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .airfoil import le_force_spectrum, te_force_spectrum
from .wallpressure import BoundaryLayer, corcos_ly, wps

__all__ = ["LESource", "TESource"]


@dataclass
class LESource:
    """Turbulence-interaction (leading-edge) noise of a blade element.

    ``turbulence`` exposes phi(K1, k2, U_local, radius) (see
    :class:`~bbnoise.turbulence.WakeTurbulence` and
    :class:`~bbnoise.turbulence.HomogeneousTurbulence`).
    """
    turbulence: object
    method: str = "auto"
    second_order: bool = True
    name: str = "rotor-wake interaction (LE)"
    spectral_factor: float = 4.0 * np.pi

    def force_spectrum(self, strip, omega_s, qbar, ky):
        phi = self.turbulence.phi(omega_s / strip.U, ky, strip.U, strip.r, omega_s)
        return le_force_spectrum(omega_s, strip.U, strip.chord, strip.dr, strip.M, qbar, ky, phi,
                                 strip.rho, self.method, self.second_order)


@dataclass
class TESource:
    """Trailing-edge (turbulent boundary layer) self noise of a blade element.

    ``boundary_layers(strip)`` must return {'suction': BoundaryLayer, 'pressure': BoundaryLayer}.
    Both sides radiate independently and their PSDs are summed.

    ``k_min``: Amiet's trailing-edge response grows as 1/K for K = omega b/U -> 0,
    outside the validity of the theory (real trailing-edge noise vanishes in the
    compact limit).  Source frequencies with K < k_min contribute nothing.  This
    matters only for the azimuthal modes of the full formulation whose source
    frequency omega + n Omega falls close to zero; without it the full spectrum
    shows spikes near multiples of the shaft frequency.
    """
    boundary_layers: object
    model: str = "goody"
    Uc_over_Ue: float = 0.7
    b_c: float = 1.47
    backscatter: bool = True
    sides: tuple = ("suction", "pressure")
    k_min: float = 0.05
    name: str = "trailing-edge self noise"
    spectral_factor: float = 2.0 * np.pi
    _cache: dict = field(default_factory=dict, repr=False)

    def bls(self, strip):
        key = (strip.index, round(strip.r, 9), round(strip.U, 6), round(strip.chord, 9))
        if key not in self._cache:
            self._cache[key] = self.boundary_layers(strip)
        return self._cache[key]

    def force_spectrum(self, strip, omega_s, qbar, ky):
        out = np.zeros(np.shape(omega_s))
        bls = self.bls(strip)
        for side in self.sides:
            bl: BoundaryLayer = bls[side]
            Uc = self.Uc_over_Ue * bl.Ue
            phi = wps(self.model, omega_s, bl)
            ly = corcos_ly(omega_s, Uc, self.b_c)
            out = out + te_force_spectrum(omega_s, strip.U, Uc, strip.chord, strip.dr, strip.M, qbar,
                                          ky, phi, ly, self.backscatter)
        if self.k_min > 0:
            out = np.where(np.abs(omega_s) * 0.5 * strip.chord / strip.U < self.k_min, 0.0, out)
        return out
