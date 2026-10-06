"""Sound power and 1/3-octave band levels."""
from __future__ import annotations

import numpy as np

__all__ = ["sound_power", "third_octave", "P_REF", "W_REF"]

P_REF = 2e-5          # Pa
W_REF = 1e-12         # W


def sound_power(lists, opt, geom, flow, Spp):
    """P1[omega, strip]: integral of the far-field spectrum over the polar angles (with the
    flight-effect weighting), per unit angular frequency, from ``Spp[omega, theta, strip]``."""
    MX = flow.MX
    th = np.asarray(lists.theta, float)
    if opt.get("emission_angle"):
        X = np.pi + np.arctan2(-np.sin(th), MX + np.cos(th))
        dist = (np.sin(th) / np.sin(X)) ** 2
    else:
        X = th
        dist = 1.0
    F = (1 - MX ** 2) ** 2 * np.sqrt(1 - MX ** 2 * np.sin(X) ** 2) / \
        (np.sqrt(1 - MX ** 2 * np.sin(X) ** 2) - MX * np.cos(X)) ** 2
    Y = (F * np.sin(X))[None, :, None] * Spp * (dist[None, :, None] if np.ndim(dist) else dist)
    return np.trapezoid(Y, X, axis=1) * 2 * np.pi * geom.r0 ** 2 / flow.rho / flow.c0


def third_octave(f, psd, n_fine=4000):
    """Band levels of a one-sided PSD per hertz (log-linear interpolation between computed
    frequencies). Only the bands lying wholly inside the computed range are returned.

    Returns (centre frequencies [Hz], band power or mean-square in the PSD's units * Hz)."""
    f = np.asarray(f, float)
    psd = np.asarray(psd, float)
    if f.size < 2:
        return np.zeros(0), np.zeros(0)
    k = np.arange(-30, 31)
    fc = 1000.0 * 2.0 ** (k / 3.0)
    lo, hi = fc * 2 ** (-1 / 6), fc * 2 ** (1 / 6)
    keep = (lo >= f[0] * (1 - 1e-9)) & (hi <= f[-1] * (1 + 1e-9))
    fc, lo, hi = fc[keep], lo[keep], hi[keep]
    out = np.zeros(fc.size)
    with np.errstate(divide="ignore"):
        lp = np.log(np.maximum(psd, 1e-300))
    for i in range(fc.size):
        ff = np.geomspace(lo[i], hi[i], max(8, n_fine // 40))
        out[i] = np.trapezoid(np.exp(np.interp(np.log(ff), np.log(f), lp)), ff)
    return fc, out
