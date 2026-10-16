"""Blade-section shapes: thickness forms and mean lines.

Coordinates are in chords from the leading edge (0 <= x <= 1).  Thickness forms are given as
the half thickness y_t(x) for a thickness ratio tau = t/c; mean lines by their slope eta'(x)
for unit design lift coefficient (the isolated thin-aerofoil lift at zero angle of attack
measured from the chord line).

Forms
-----
``naca16``  NACA 16-series (Lindsey, Stevenson & Daley, NACA TR 763 / NACA-RM-L8H23),
            the standard section of high-speed propellers and propfans:
              x <= 1/2 :  y_t = tau (0.989665 sqrt x - 0.23925 x - 0.041 x^2 - 0.5594 x^3)
              x >  1/2 :  y_t = tau (0.01 + 2.325 (1-x) - 3.42 (1-x)^2 + 1.46 (1-x)^3)
            leading-edge radius 0.48972 tau^2.
``naca65``  NACA 65-series basic thickness (Abbott & von Doenhoff), scaled from 65-010.
``naca4``   NACA four-digit thickness (open trailing edge), r_le = 1.1019 tau^2.

Mean lines
----------
``a1``        NACA a = 1.0 uniform-load mean line:  eta' = cl_d/(4 pi) ln((1-x)/x).
``parabolic`` circular (parabolic) arc:              eta' = cl_d/pi (1 - 2x).
"""
from __future__ import annotations

import numpy as np
from scipy.interpolate import PchipInterpolator

THICKNESS_FORMS = ("naca16", "naca65", "naca4")
MEAN_LINES = ("a1", "parabolic")

_N65_X = np.array([0.0, 0.5, 0.75, 1.25, 2.5, 5.0, 7.5, 10, 15, 20, 25, 30, 35, 40,
                   45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100]) / 100.0
_N65_Y = np.array([0.0, 0.772, 0.932, 1.169, 1.574, 2.177, 2.647, 3.040, 3.666, 4.143,
                   4.503, 4.760, 4.924, 4.996, 4.963, 4.812, 4.530, 4.146, 3.682, 3.156,
                   2.584, 1.987, 1.385, 0.810, 0.306, 0.0]) / 100.0 / 0.10
_N65_RLE = 0.00687 / 0.01          # r_le / tau^2  (65-010: r_le = 0.687 % at tau = 0.1)
_g = np.empty_like(_N65_X)
_g[1:] = _N65_Y[1:] / np.sqrt(_N65_X[1:])
_g[0] = np.sqrt(2.0 * _N65_RLE)
_N65_G = PchipInterpolator(_N65_X, _g)
_N65_DG = _N65_G.derivative()


def half_thickness(x, form="naca16"):
    """Half thickness y_t(x) for unit thickness ratio (tau = 1)."""
    x = np.clip(np.asarray(x, dtype=float), 0.0, 1.0)
    if form == "naca16":
        xf = np.minimum(x, 0.5)
        xa = 1.0 - np.maximum(x, 0.5)
        fwd = 0.989665 * np.sqrt(xf) - 0.23925 * xf - 0.041 * xf ** 2 - 0.5594 * xf ** 3
        aft = 0.01 + 2.325 * xa - 3.42 * xa ** 2 + 1.46 * xa ** 3
        return np.where(x <= 0.5, fwd, aft)
    if form == "naca65":
        return _N65_G(x) * np.sqrt(x)
    if form == "naca4":
        return 5.0 * (0.2969 * np.sqrt(x) - 0.126 * x - 0.3516 * x ** 2 + 0.2843 * x ** 3
                      - 0.1015 * x ** 4)
    raise ValueError(f"unknown thickness form {form!r}; use one of {THICKNESS_FORMS}")


def half_thickness_slope_times_sqrt(x, form="naca16"):
    """sqrt(x) * dy_t/dx for unit tau: finite at the leading edge."""
    x = np.clip(np.asarray(x, dtype=float), 0.0, 1.0)
    sx = np.sqrt(x)
    if form == "naca16":
        xf = np.minimum(x, 0.5)
        xa = 1.0 - np.maximum(x, 0.5)
        fwd = 0.5 * 0.989665 + sx * (-0.23925 - 0.082 * xf - 1.6782 * xf ** 2)
        aft = sx * (-2.325 + 6.84 * xa - 4.38 * xa ** 2)
        return np.where(x <= 0.5, fwd, aft)
    if form == "naca65":
        # y = g(x) sqrt(x)  ->  sqrt(x) y' = x g'(x) + g(x)/2
        return x * _N65_DG(x) + 0.5 * _N65_G(x)
    if form == "naca4":
        return 5.0 * (0.5 * 0.2969 + sx * (-0.126 - 0.7032 * x + 0.8529 * x ** 2 - 0.406 * x ** 3))
    raise ValueError(f"unknown thickness form {form!r}")


def leading_edge_radius(tau, form="naca16"):
    """Leading-edge radius / chord."""
    k = {"naca16": 0.5 * 0.989665 ** 2, "naca65": _N65_RLE, "naca4": 1.1019}[form]
    return k * np.asarray(tau, dtype=float) ** 2


def mean_line_slope(x, kind="a1"):
    """Mean-line slope eta'(x) for unit design lift coefficient."""
    x = np.clip(np.asarray(x, dtype=float), 1e-12, 1.0 - 1e-12)
    if kind == "a1":
        return np.log((1.0 - x) / x) / (4.0 * np.pi)
    if kind == "parabolic":
        return (1.0 - 2.0 * x) / np.pi
    raise ValueError(f"unknown mean line {kind!r}; use one of {MEAN_LINES}")


def mean_line(x, kind="a1"):
    """Mean-line ordinate eta(x) for unit design lift coefficient."""
    x = np.clip(np.asarray(x, dtype=float), 0.0, 1.0)
    if kind == "a1":
        with np.errstate(divide="ignore", invalid="ignore"):
            t1 = np.where(x < 1.0, (1.0 - x) * np.log(np.maximum(1.0 - x, 1e-300)), 0.0)
            t2 = np.where(x > 0.0, x * np.log(np.maximum(x, 1e-300)), 0.0)
        return -(t1 + t2) / (4.0 * np.pi)
    if kind == "parabolic":
        return x * (1.0 - x) / np.pi
    raise ValueError(f"unknown mean line {kind!r}")


def section_coordinates(tau, cl_design, form="naca16", mean="a1", n=121):
    """Upper and lower surface coordinates (x, y) of a section, LE at the origin."""
    th = np.linspace(0.0, np.pi, n)
    x = 0.5 * (1.0 - np.cos(th))
    yt = tau * half_thickness(x, form)
    yc = cl_design * mean_line(x, mean)
    return x, yc + yt, yc - yt
