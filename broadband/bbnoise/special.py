"""Special functions used by Amiet's airfoil response theory.

Conventions follow Amiet (1975, 1976) and Roger & Moreau (2005):

    E*(x) = int_0^x exp(-i t) / sqrt(2 pi t) dt = C2(x) - i S2(x)
    E (x) = conj(E*(x))                           (x real)

Several of Amiet's closed forms contain E*(2z)/sqrt(z).  That combination is
an entire function of z (it is (2/sqrt(pi)) int_0^1 exp(-2 i z u^2) du), so it
is evaluated here through the complex error function.  This makes the
response functions valid for any real or complex argument, including negative
chordwise wavenumbers that occur in the rotating-blade (full) formulation.
"""
from __future__ import annotations

import numpy as np
from scipy import special as sp

__all__ = ["Estar", "E", "Estar_over_sqrt", "sears", "theodorsen"]


def Estar_over_sqrt(z):
    """Return E*(2 z) / sqrt(z) for real or complex ``z`` (entire function).

    Substituting t = 2 z u^2 gives E*(2z)/sqrt(z) = (2/sqrt(pi)) int_0^1
    exp(-a^2 u^2) du = erf(a)/a with a = sqrt(2 i z).  erf(a)/a is even in
    a, so the branch of the square root is irrelevant; the limit at z = 0 is
    2/sqrt(pi).
    """
    z = np.asarray(z, dtype=complex)
    a = np.sqrt(2j * z)
    small = np.abs(a) < 1e-6
    a_safe = np.where(small, 1.0, a)
    out = sp.erf(a_safe) / a_safe
    # series: erf(a)/a = 2/sqrt(pi) (1 - a^2/3 + ...)
    out = np.where(small, 2.0 / np.sqrt(np.pi) * (1.0 - a * a / 3.0), out)
    return out


def Estar(x):
    """Fresnel-type integral E*(x) = int_0^x e^{-it}/sqrt(2 pi t) dt.

    For real non-negative ``x`` this equals C2(x) - i S2(x).  General
    arguments use sqrt(x/2) * Estar_over_sqrt(x/2).
    """
    x = np.asarray(x)
    if np.isrealobj(x) and np.all(x >= 0):
        s, c = sp.fresnel(np.sqrt(2.0 * x / np.pi))
        return c - 1j * s
    z = np.asarray(x, dtype=complex) / 2.0
    return np.sqrt(z) * Estar_over_sqrt(z)


def E(x):
    """E(x) = int_0^x e^{+it}/sqrt(2 pi t) dt (complex conjugate of E* for real x >= 0)."""
    return np.conj(Estar(x))


def theodorsen(k):
    """Theodorsen's function C(k) = H1(2)(k) / (H1(2)(k) + i H0(2)(k))."""
    k = np.asarray(k, dtype=float)
    k = np.maximum(k, 1e-12)
    h1 = sp.hankel2(1, k)
    h0 = sp.hankel2(0, k)
    return h1 / (h1 + 1j * h0)


def sears(k):
    """Sears' gust response S(k) = (J0(k) - i J1(k)) C(k) + i J1(k).

    |S| -> 1 as k -> 0 and |S| ~ 1/sqrt(2 pi k) as k -> infinity.
    """
    k = np.asarray(k, dtype=float)
    kk = np.maximum(k, 1e-12)
    return (sp.j0(kk) - 1j * sp.j1(kk)) * theodorsen(kk) + 1j * sp.j1(kk)
