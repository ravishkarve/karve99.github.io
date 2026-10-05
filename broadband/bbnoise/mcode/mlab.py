"""MATLAB-compatible helpers used by the MATLAB-code port.

The original is MATLAB code; reproducing its results to round-off needs MATLAB's exact
behaviour for a handful of built-ins:

* ``mround``    round half away from zero (numpy rounds half to even)
* ``interp_idx`` ``interp1(v, xi)``: linear interpolation of ``v`` at 1-based
  index positions ``xi`` (NaN outside the array), which the MATLAB code uses to place strips
* ``interp1``   ``interp1(x, y, xi)`` with NaN outside the data range
* ``mlinspace`` ``linspace(a, b, 1)`` returns ``b`` in MATLAB
* ``mlogspace`` ``logspace(a, b, n)``
* ``colon_first`` ``a:b`` with array operands uses their first elements
* ``erfz``      the complex error function exactly as in the MATLAB code's ``erfz.m``
  (M. Leutenegger's series), so complex arguments round the same way
* ``fzero``     MATLAB's interval search around a scalar start point, then a
  Brent root solve on the bracket
* ``csqrt`` / ``cpow`` / ``clog10`` real-or-complex functions that return complex
  values for negative real arguments, as MATLAB does
"""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import brentq
from scipy.special import erf

EPS = np.finfo(float).eps


def mround(x):
    x = np.asarray(x, float)
    return np.sign(x) * np.floor(np.abs(x) + 0.5)


def interp_idx(v, xi):
    v = np.asarray(v, float).ravel()
    xi = np.asarray(xi, float)
    out = np.interp(xi, np.arange(1, v.size + 1, dtype=float), v)
    return np.where((xi < 1) | (xi > v.size), np.nan, out)


def interp1(x, y, xi):
    x = np.asarray(x, float).ravel()
    y = np.asarray(y, float).ravel()
    xi_arr = np.asarray(xi, float)
    order = np.argsort(x)
    out = np.interp(xi_arr, x[order], y[order])
    out = np.where((xi_arr < x.min()) | (xi_arr > x.max()), np.nan, out)
    return out if np.ndim(xi) else float(out)


def mlinspace(a, b, n):
    n = int(n)
    if n == 1:
        return np.array([float(b)])
    return np.linspace(a, b, n)


def mlogspace(a, b, n):
    return 10.0 ** mlinspace(a, b, n)


def colon_first(x):
    """Scalar used by MATLAB's ``-x:x`` when ``x`` is an array (its first element)."""
    return float(np.ravel(np.asarray(x, float))[0])


def csqrt(x):
    return np.sqrt(np.asarray(x, dtype=complex))


def cpow(x, p):
    return np.power(np.asarray(x, dtype=complex), p)


def clog10(x):
    return np.log10(np.asarray(x, dtype=complex))


def creal(x):
    """Return a real array when the imaginary part is identically zero (as MATLAB would show it)."""
    x = np.asarray(x)
    if np.iscomplexobj(x) and not np.any(np.imag(x)):
        return np.real(x)
    return x


# ---------------------------------------------------------------------------
# erfz.m (M. Leutenegger 2008), vectorised
# ---------------------------------------------------------------------------

_N_ERFZ = math.sqrt(1.0 - 4.0 * math.log(EPS / 2.0))


def _parts(R, I):
    R2 = R * R
    e2iRI = np.exp(-2j * R * I)
    with np.errstate(divide="ignore", invalid="ignore"):
        E = (1 - e2iRI) / (2 * np.pi * R)
    E = np.where(R == 0, 0.0, E)
    F = 0.0
    Hr = 0.0
    Hi = 0.0
    for n in range(1, int(math.ceil(_N_ERFZ)) + 1):
        H = n * n / 4.0
        H = np.exp(-H) / (H + R2)
        F = F + H
        H = H * np.exp(-n * I)
        Hi = Hi + n / 2.0 * H
        Hr = Hr + H
    e = np.exp(-R2) * (E + R * F / np.pi - e2iRI * (R * Hr + 1j * Hi) / (2 * np.pi))
    R3 = R2 + math.log(2 * np.pi)
    Gr = 0.0
    Gi = 0.0
    M = 2 * I
    n = np.maximum(1.0, np.floor(M - _N_ERFZ))
    Mmax = int(math.ceil(np.max(M + _N_ERFZ - n)))
    for _ in range(0, Mmax + 1):
        n1 = n / 2.0
        n2 = n1 * n1
        G = np.exp(n * I - n2 - R3 - np.log(n2 + R2))
        Gi = Gi - n1 * G
        Gr = Gr + G
        n = n + 1
    e = e - e2iRI * (R * Gr + 1j * Gi)
    z0 = R == 0
    e = np.where(z0, e + 1j * I / np.pi, e)
    return e


def erfz(z):
    z = np.asarray(z)
    if z.size == 0:
        return z
    if not np.iscomplexobj(z):
        return erf(z)
    R = np.real(z).astype(float)
    I = np.imag(z).astype(float)
    shape = z.shape
    R = R.ravel()
    I = I.ravel()
    e = np.full(R.shape, np.nan, dtype=complex)
    fin_r = np.isfinite(R)
    fin_i = np.isfinite(I)
    k = fin_i                                     # n >= 2
    e[k] = erf(R[k])
    sel = fin_r & fin_i & (I != 0)
    if np.any(sel):
        Rs = R[sel]
        Is = I[sel]
        P = _parts(Rs, np.abs(Is))
        P = np.where(Is < 0, np.conj(P), P)
        e[sel] = e[sel] + P
    return e.reshape(shape)


# ---------------------------------------------------------------------------
# fzero with a scalar start point (MATLAB's bracket search)
# ---------------------------------------------------------------------------

def fzero(fun, x0):
    x0 = float(x0)
    fx = fun(x0)
    if fx == 0:
        return x0
    dx = x0 / 50.0 if x0 != 0 else 1.0 / 50.0
    a = b = x0
    fa = fb = fx
    twosqrt = math.sqrt(2.0)
    for _ in range(2000):
        if (fa > 0) != (fb > 0):
            break
        dx = twosqrt * dx
        a = x0 - dx
        fa = fun(a)
        if (fa > 0) != (fb > 0):
            break
        b = x0 + dx
        fb = fun(b)
    else:
        raise ValueError("fzero: no sign change found")
    if fa == 0:
        return a
    if fb == 0:
        return b
    lo, hi = (a, b) if a < b else (b, a)
    return brentq(fun, lo, hi, xtol=1e-300, rtol=4 * EPS, maxiter=500)


def trapz(x, y, axis=0):
    return np.trapezoid(y, x, axis=axis)
