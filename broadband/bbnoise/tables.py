"""Radial tables read from files: blade geometry and trailing-edge boundary layers.

Both are plain text tables (CSV, TSV or whitespace separated) with a header
row; lines starting with ``#`` are comments.  JSON (a list of row objects) is
also accepted.

Blade table (``rotors[i].blade_file``)::

    r_over_R, chord          # or r [m] instead of r_over_R; chord in metres
    0.30,     0.050          # optional: Ux [m/s] (axial velocity through the disc)
    0.70,     0.060
    1.00,     0.040

Boundary-layer table (``brte.boundary_layer = {method = "file", path = ...}``),
either *long* with a ``side`` column (suction/pressure/both, or ss/ps, upper/lower)::

    r_over_R, side,     delta_star_over_c, H,   cf,     beta_c
    0.3,      suction,  0.016,             1.6, 0.0022, 1.5
    0.3,      pressure, 0.006,             1.4, 0.0030, 0
    1.0,      suction,  0.010,             1.6, 0.0024, 1.5
    ...

or *wide* with side prefixes (``suction_``, ``pressure_``, ``both_``, ``ss_``, ``ps_``)::

    r_over_R, suction_delta_star_over_c, suction_H, pressure_delta_star_over_c, pressure_H

Recognised quantities: delta_star, delta, theta [m] or delta_star_over_c,
delta_over_c, theta_over_c; H, cf, tau_w [Pa], dpdx [Pa/m], beta_c, Pi,
tau_max [Pa], Ue [m/s] or Ue_over_U.  Without a radius column (stationary
airfoil) the table has one row per side.  Values are interpolated linearly
between rows and held constant beyond the first and last radius.
"""
from __future__ import annotations

import csv
import io
import json
from functools import lru_cache

import numpy as np

__all__ = ["parse_table", "blade_from_table", "bl_from_table", "BLADE_TEMPLATE", "BL_TEMPLATE"]

BL_KEYS = ("delta_star", "delta", "theta", "delta_star_over_c", "delta_over_c", "theta_over_c", "H", "cf",
           "tau_w", "dpdx", "beta_c", "Pi", "tau_max", "Ue", "Ue_over_U")
_ALIASES = {"r/r": "r_over_R", "r_r": "r_over_R", "r_over_r": "r_over_R", "rr": "r_over_R", "r/rtip": "r_over_R",
            "dstar": "delta_star", "delta*": "delta_star", "ds": "delta_star", "deltastar": "delta_star",
            "dstar_over_c": "delta_star_over_c", "delta*/c": "delta_star_over_c", "ds/c": "delta_star_over_c",
            "delta/c": "delta_over_c", "theta/c": "theta_over_c", "ue/u": "Ue_over_U", "ue_over_u": "Ue_over_U",
            "ue": "Ue", "h": "H", "cf": "cf", "c_f": "cf", "beta": "beta_c", "betac": "beta_c", "beta_c": "beta_c",
            "pi": "Pi", "tau_w": "tau_w", "tauw": "tau_w", "dp/dx": "dpdx", "dpdx": "dpdx", "c": "chord",
            "chord": "chord", "ux": "Ux", "r": "r", "side": "side", "tau_max": "tau_max",
            "stagger": "stagger_deg", "stagger_deg": "stagger_deg", "alpha": "stagger_deg", "alpha_deg": "stagger_deg",
            "u_x": "U_X", "ux_rel": "U_X", "uxrel": "U_X", "w": "U_X"}
_SIDES = {"suction": "suction", "ss": "suction", "upper": "suction", "s": "suction",
          "pressure": "pressure", "ps": "pressure", "lower": "pressure", "p": "pressure", "both": "both"}

BLADE_TEMPLATE = """# Blade radial distribution: r_over_R (or r in metres), chord [m]; optional columns
# Ux (axial inflow [m/s]), stagger_deg (stagger from the rotor axis [deg]) and U_X
# (chordwise relative speed [m/s]).  Without stagger_deg the blade follows the inflow.
r_over_R,chord,stagger_deg
0.30,0.050,40
0.50,0.056,52
0.70,0.060,60
0.85,0.055,64
1.00,0.040,67
"""

BL_TEMPLATE = """# Trailing-edge boundary layers along the blade (one row per radius and side).
# Lengths as *_over_c (ratio to the local chord) or delta_star, delta, theta in metres.
# Optional columns: delta_over_c, theta_over_c, H, cf, beta_c (or dpdx), Pi, Ue_over_U (or Ue).
# Blank cells are estimated (H = 1.4, Ludwieg-Tillmann cf, Drela delta, Durbin-Reif Pi).
r_over_R,side,delta_star_over_c,H,cf,beta_c,Ue_over_U
0.3,suction,0.016,1.6,,1.5,1.0
0.3,pressure,0.006,1.4,,0,1.0
0.7,suction,0.012,1.6,,1.5,1.0
0.7,pressure,0.005,1.4,,0,1.0
1.0,suction,0.010,1.6,,1.5,1.0
1.0,pressure,0.005,1.4,,0,1.0
"""


def _canon(name):
    n = name.strip()
    low = n.lower().replace(" ", "")
    if n in BL_KEYS or n in ("r_over_R", "chord", "Ux", "U_X", "stagger_deg", "r", "side"):
        return n
    return _ALIASES.get(low, n)


def _split_side(col):
    """'suction_H' -> ('suction', 'H'); 'H' -> (None, 'H')."""
    for pre, side in _SIDES.items():
        for sep in ("_", ":", "."):
            if col.lower().startswith(pre + sep) and len(col) > len(pre) + 1:
                return side, _canon(col[len(pre) + 1:])
    return None, _canon(col)


def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    v = str(v).strip()
    if v == "" or v.lower() in ("nan", "none", "-", "na"):
        return None
    return float(v)


@lru_cache(maxsize=64)
def _parse_cached(text):
    t = text.strip()
    if t.startswith("[") or t.startswith("{"):
        data = json.loads(t)
        if isinstance(data, dict):
            data = data.get("rows", [data])
        header = list(dict.fromkeys(k for row in data for k in row))
        rows = [[row.get(k, "") for k in header] for row in data]
        return tuple(header), tuple(tuple(r) for r in rows)
    lines = [ln for ln in t.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        raise ValueError("the table is empty")
    sample = lines[0]
    if "," in sample:
        delim = ","
    elif ";" in sample:
        delim = ";"
    elif "\t" in sample:
        delim = "\t"
    else:
        delim = None
    if delim is None:
        rows = [ln.split() for ln in lines]
    else:
        rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delim))
    header = [h.strip() for h in rows[0]]
    body = [[c.strip() for c in r] + [""] * (len(header) - len(r)) for r in rows[1:] if any(c.strip() for c in r)]
    return tuple(header), tuple(tuple(r[:len(header)]) for r in body)


def parse_table(text):
    """Return (header, rows) with rows as lists of strings (or numbers for JSON input)."""
    header, rows = _parse_cached(text)
    return list(header), [list(r) for r in rows]


def _radius(header, rows, r_tip):
    cols = [_canon(h) for h in header]
    if "r_over_R" in cols:
        i = cols.index("r_over_R")
        return np.array([_num(r[i]) for r in rows], float)
    if "r" in cols:
        if not r_tip:
            raise ValueError("the table gives r in metres; the rotor tip radius is needed to convert it")
        i = cols.index("r")
        return np.array([_num(r[i]) for r in rows], float) / r_tip
    return None


def _radial_dict(x, y):
    ok = [i for i, v in enumerate(y) if v is not None]
    if not ok:
        return None
    xs = np.asarray([x[i] for i in ok], float)
    ys = np.asarray([y[i] for i in ok], float)
    o = np.argsort(xs)
    xs, ys = xs[o], ys[o]
    if len(xs) == 1:
        return float(ys[0])
    return {"r_over_R": [float(v) for v in xs], "value": [float(v) for v in ys]}


def blade_from_table(text, r_tip=None):
    """Blade table -> {'chord': radial dict, ['Ux', 'stagger_deg', 'U_X': radial dicts]}."""
    header, rows = parse_table(text)
    cols = [_canon(h) for h in header]
    x = _radius(header, rows, r_tip)
    if x is None:
        raise ValueError("the blade table needs an r_over_R (or r) column")
    if "chord" not in cols:
        raise ValueError("the blade table needs a chord column")
    out = {}
    for key in ("chord", "Ux", "stagger_deg", "U_X"):
        if key in cols:
            i = cols.index(key)
            d = _radial_dict(list(x), [_num(r[i]) for r in rows])
            if d is not None:
                out[key] = d
    if "chord" not in out:
        raise ValueError("the chord column is empty")
    chords = [out["chord"]] if isinstance(out["chord"], float) else out["chord"]["value"]
    if min(chords) <= 0:
        raise ValueError("chord values must be positive")
    return out


def bl_from_table(text, r_tip=None):
    """Boundary-layer table -> user boundary-layer spec with radial distributions."""
    header, rows = parse_table(text)
    cols = [_canon(h) for h in header]
    x = _radius(header, rows, r_tip)
    per_side = {"suction": {}, "pressure": {}, "both": {}}   # key -> list of (r, value)
    if "side" in cols:
        si = cols.index("side")
        for k, row in enumerate(rows):
            side = _SIDES.get(str(row[si]).strip().lower())
            if side is None:
                raise ValueError(f"row {k + 2}: unknown side {row[si]!r} (use suction or pressure)")
            for j, col in enumerate(cols):
                if col in BL_KEYS:
                    v = _num(row[j])
                    if v is not None:
                        per_side[side].setdefault(col, []).append((None if x is None else x[k], v))
    else:
        for j, h in enumerate(header):
            side, key = _split_side(h)
            if key not in BL_KEYS:
                continue
            side = side or "both"
            for k, row in enumerate(rows):
                v = _num(row[j])
                if v is not None:
                    per_side[side].setdefault(key, []).append((None if x is None else x[k], v))
    spec = {"method": "user"}
    found = False
    for side, d in per_side.items():
        vals = {}
        for key, pts in d.items():
            if x is None:
                if len(pts) > 1:
                    raise ValueError(f"{side} {key}: several rows but no r_over_R column")
                vals[key] = pts[0][1]
            else:
                r = [p[0] for p in pts]
                vals[key] = _radial_dict(r, [p[1] for p in pts])
        if vals:
            spec[side] = vals
            found = True
    if not found:
        raise ValueError("no boundary-layer quantity found; expected columns such as delta_star_over_c, H, cf")
    for side in ("suction", "pressure"):
        merged = dict(spec.get("both", {}))
        merged.update(spec.get(side, {}))
        if not any(k in merged for k in ("delta_star", "delta_star_over_c")) and not (
                any(k in merged for k in ("theta", "theta_over_c")) and "H" in merged):
            raise ValueError(f"{side} side: the table needs delta_star (or delta_star_over_c), or theta with H")
    return spec
