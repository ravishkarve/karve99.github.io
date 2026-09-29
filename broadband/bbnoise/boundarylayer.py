"""Trailing-edge boundary-layer estimators used when no measured or computed
boundary layer is available.

* ``bpm``: Brooks, Pope & Marcolini (1989, NASA RP-1218) NACA 0012 correlations
  for the boundary-layer thickness delta and displacement thickness delta* at
  the trailing edge, tripped or untripped, with angle-of-attack corrections
  for the pressure and suction sides.
* ``flat_plate``: turbulent 1/7th power-law flat plate at x = chord.

Both return :class:`~bbnoise.wallpressure.BoundaryLayer` objects (suction and
pressure side), completed with the standard correlations.
"""
from __future__ import annotations

import numpy as np

from .wallpressure import BoundaryLayer

__all__ = ["bpm_thickness", "bpm", "flat_plate", "make_boundary_layers"]


def bpm_thickness(chord, U, nu=1.5e-5, alpha_deg=0.0, tripped=True):
    """BPM trailing-edge delta and delta* (pressure side, suction side) [m]."""
    R = U * chord / nu
    lr = np.log10(R)
    if tripped:
        d0 = chord * 10 ** (1.892 - 0.9045 * lr + 0.0596 * lr ** 2)
        ds0 = chord * (0.0601 * R ** -0.114 if R <= 0.3e6 else
                       10 ** (3.411 - 1.5397 * lr + 0.1059 * lr ** 2))
    else:
        d0 = chord * 10 ** (1.6569 - 0.9045 * lr + 0.0596 * lr ** 2)
        ds0 = chord * 10 ** (3.0187 - 1.5397 * lr + 0.1059 * lr ** 2)
    a = abs(alpha_deg)
    # pressure side
    dp = d0 * 10 ** (-0.04175 * a + 0.00106 * a ** 2)
    dsp = ds0 * 10 ** (-0.0432 * a + 0.00113 * a ** 2)
    # suction side
    if tripped:
        if a <= 5:
            fs, fds = 10 ** (0.0311 * a), 10 ** (0.0679 * a)
        elif a <= 12.5:
            fs, fds = 0.3468 * 10 ** (0.1231 * a), 0.381 * 10 ** (0.1516 * a)
        else:
            fs, fds = 5.718 * 10 ** (0.0258 * a), 14.296 * 10 ** (0.0258 * a)
    else:
        if a <= 7.5:
            fs, fds = 10 ** (0.03114 * a), 10 ** (0.0679 * a)
        elif a <= 12.5:
            fs, fds = 0.0303 * 10 ** (0.2336 * a), 0.0162 * 10 ** (0.3066 * a)
        else:
            fs, fds = 12.0 * 10 ** (0.0258 * a), 52.42 * 10 ** (0.0258 * a)
    return {"pressure": (dp, dsp), "suction": (d0 * fs, ds0 * fds)}


def bpm(chord, U, nu=1.5e-5, alpha_deg=0.0, tripped=True, rho=1.225, c0=340.0,
        H=(1.4, 1.4), beta_c=(0.0, 0.0), Ue_over_U=1.0):
    """Suction/pressure-side boundary layers from the BPM correlations.

    ``H`` and ``beta_c`` are (suction, pressure) values since BPM gives only
    delta and delta*; skin friction then follows from Ludwieg-Tillmann.
    """
    th = bpm_thickness(chord, U, nu, alpha_deg, tripped)
    out = {}
    for i, side in enumerate(("suction", "pressure")):
        d, ds = th[side]
        bl = BoundaryLayer(Ue=U * Ue_over_U, delta_star=ds, delta=d, H=H[i],
                           beta_c=beta_c[i], rho=rho, nu=nu, c0=c0)
        bl.notes.append(f"BPM {'tripped' if tripped else 'untripped'} NACA0012, alpha={alpha_deg:g} deg")
        out[side] = bl.complete()
    return out


def flat_plate(chord, U, nu=1.5e-5, rho=1.225, c0=340.0, beta_c=0.0):
    """1/7th power-law turbulent flat plate at x = chord (both sides identical)."""
    Rex = U * chord / nu
    delta = 0.37 * chord * Rex ** -0.2
    ds = delta / 8.0
    th = 7.0 * delta / 72.0
    cf = 0.0592 * Rex ** -0.2
    out = {}
    for side in ("suction", "pressure"):
        bl = BoundaryLayer(Ue=U, delta_star=ds, delta=delta, theta=th, cf=cf,
                           beta_c=beta_c, rho=rho, nu=nu, c0=c0)
        bl.notes.append("1/7 power-law flat plate")
        out[side] = bl.complete()
    return out


def _radial(v, r_over_R):
    """Scalar, or {'r_over_R': [...], 'value': [...]} interpolated at r_over_R (mean if None)."""
    if isinstance(v, dict):
        xs = np.asarray(v.get("r_over_R"), float)
        ys = np.asarray(v.get("value"), float)
        return float(np.mean(ys)) if r_over_R is None else float(np.interp(r_over_R, xs, ys))
    return v


USER_KEYS = ("delta_star", "delta", "theta", "delta_star_over_c", "delta_over_c", "theta_over_c", "H", "cf",
             "tau_w", "dpdx", "beta_c", "Pi", "tau_max", "Ue", "Ue_over_U")


def make_boundary_layers(spec: dict, chord, U, rho=1.225, nu=1.5e-5, c0=340.0, r_over_R=None):
    """Build suction/pressure boundary layers from a configuration dictionary.

    spec = {"method": "bpm", "alpha_deg": 0, "tripped": true, "H": [1.4, 1.4],
            "beta_c": [0, 0]}
         | {"method": "flat_plate"}
         | {"method": "user", "suction": {...}, "pressure": {...}}   (or "both": {...})

    User boundary layers accept delta_star, delta, theta [m] or delta_star_over_c,
    delta_over_c, theta_over_c (scaled by the local chord, convenient for rotors),
    H, cf, tau_w, dpdx or beta_c, Pi, tau_max and Ue [m/s] or Ue_over_U.  Every
    value may be a scalar or a radial distribution {"r_over_R": [...], "value": [...]}
    (``r_over_R`` of the blade element; the mean is used for a stationary airfoil).
    Quantities left out are estimated (see BoundaryLayer.complete); delta* is
    required, or theta together with H.
    """
    method = spec.get("method", "bpm").lower()
    if method == "bpm":
        H = spec.get("H", (1.4, 1.4))
        bc = spec.get("beta_c", (0.0, 0.0))
        if np.isscalar(H):
            H = (H, H)
        if np.isscalar(bc):
            bc = (bc, bc)
        return bpm(chord, U, nu, spec.get("alpha_deg", 0.0), spec.get("tripped", True), rho, c0,
                   H=tuple(H), beta_c=tuple(bc), Ue_over_U=spec.get("Ue_over_U", 1.0))
    if method in ("flat_plate", "flatplate"):
        return flat_plate(chord, U, nu, rho, c0, spec.get("beta_c", 0.0))
    if method == "user":
        out = {}
        for side in ("suction", "pressure"):
            raw = dict(spec.get("both", {}))
            raw.update(spec.get(side, {}))
            s = {k: _radial(v, r_over_R) for k, v in raw.items() if k in USER_KEYS and v is not None and v != ""}
            for key in ("delta_star", "delta", "theta"):
                if f"{key}_over_c" in s:
                    s[key] = float(s.pop(f"{key}_over_c")) * chord
            Ue = float(s.pop("Ue")) if "Ue" in s else float(s.pop("Ue_over_U", 1.0)) * U
            s.pop("Ue_over_U", None)
            if "delta_star" not in s:
                if "theta" in s and "H" in s:
                    s["delta_star"] = s["theta"] * s["H"]
                else:
                    raise ValueError(f"user boundary layer ({side} side) needs delta* (or theta and H)")
            if "beta_c" in s and "dpdx" in s:
                s.pop("dpdx")
            bl = BoundaryLayer(Ue=Ue, rho=rho, nu=nu, c0=c0, **{k: float(v) for k, v in s.items()})
            bl.notes.append("user boundary layer")
            out[side] = bl.complete()
        return out
    raise ValueError(f"unknown boundary-layer method {method!r}")
