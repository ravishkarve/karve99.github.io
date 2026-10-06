"""Default case and table templates: a made-up 10 x 8 contra-rotating rotor (1/7 scale).

All numbers are invented for demonstration; they do not come from any rig.
"""
from __future__ import annotations

import copy

import numpy as np

from .inputs import BL_COLUMNS

__all__ = ["default_case", "synthetic_bl_tables", "synthetic_wake", "synthetic_ingestion", "bl_text",
           "bl_table", "BL_HEADER", "template"]

BL_HEADER = " ".join(BL_COLUMNS)


def synthetic_bl_tables(st=5):
    """Four boundary-layer tables (front top, front bottom, rear top, rear bottom), 13 columns, one row per strip."""
    r = np.linspace(0.088, 0.232, st)
    out = []
    for top, rot in ((True, 1), (False, 1), (True, 2), (False, 2)):
        d = np.linspace(2.6e-3, 1.7e-3, st) * (1.25 if top else 0.8) * (1.1 if rot == 2 else 1.0)
        ds = d * (0.32 if top else 0.22)
        th = ds / 1.45
        tauw = np.linspace(20, 44, st) * (0.8 if top else 1.1)
        taumax = tauw * (1.9 if top else 1.15)
        dpdx = np.linspace(2.2e4, 4.4e4, st) * (1 if top else -0.3)
        cols = [r, d, ds, th, np.zeros(st), taumax, dpdx, np.full(st, 1.2), np.linspace(100, 170, st),
                np.linspace(0.9, 0.6, st) * (1 if top else 0.3), np.full(st, 1.5e-5), tauw, np.zeros(st)]
        out.append(np.column_stack(cols))
    return out


def bl_text(table):
    return BL_HEADER + "\n" + "\n".join(" ".join(f"{v:.8e}" for v in row) for row in table) + "\n"


def bl_table(table):
    """13-column array -> inline table {column name: list}."""
    return {c: table[:, i].tolist() for i, c in enumerate(BL_COLUMNS) if c != "unused"}


def synthetic_wake(st=5):
    return {"bw": np.linspace(0.0065, 0.0042, st), "wrms_bg": np.linspace(0.6, 0.4, st),
            "wrms_wake": np.linspace(2.6, 1.7, st), "L_bg": np.linspace(0.010, 0.013, st),
            "L_wake": np.linspace(0.0042, 0.0031, st)}


def synthetic_ingestion():
    z = np.linspace(0.01, 0.12, 12)
    return {"z": z, "ua": np.full(z.size, 1.0), "la": 0.30 - 0.01 * np.arange(z.size),
            "ut": np.full(z.size, 2.0), "lt": 0.15 - 0.005 * np.arange(z.size)}


def _l(d):
    return {k: np.round(np.asarray(v, float), 10).tolist() for k, v in d.items()}


def default_case():
    """A complete case with the three sections filled in."""
    n = 7
    bl = synthetic_bl_tables()
    return copy.deepcopy({
        "rotor": {
            "stages": 2, "mach": 0.2, "c0": 340.0, "rho": 1.2, "gap": 0.22, "scale": 1.0,
            "front": {"blades": 10, "rpm": 2865.0,
                      "blade": _l({"r": np.linspace(0.07, 0.25, n), "chord": np.linspace(0.062, 0.044, n),
                                   "stagger_deg": np.linspace(35.5, 66.5, n)})},
            "rear": {"blades": 8, "rpm": 2578.0,
                     "blade": _l({"r": np.linspace(0.07, 0.23, n), "chord": np.linspace(0.064, 0.046, n),
                                  "stagger_deg": np.linspace(33.2, 61.9, n)})},
        },
        "noise_model": {
            "interaction": True, "self_noise": ["front", "rear"], "bl_ingestion": False,
            "formulation": "full", "strips": 5, "azimuth_points": 40,
            "frequency": {"min": 50.0, "max": 20000.0, "n": 30},
            "observers": {"theta_deg": [30.0, 60.0, 90.0, 120.0, 150.0], "radius": 2.54},
            "chapman": False, "emission_angle": False, "contraction_percent": 100,
            "ingestion": {"wall_distance": 0.27, "bl_height": 0.1, "hard_wall": True, "partial_loading": True,
                          "blade_correlation": True},
        },
        "spectra": {
            "interaction": {"turbulence": "von_karman", "length_scale": 0.4, "wake": _l(synthetic_wake())},
            "wall_pressure": {"model": "rozenberg", "convection": "del_alamo_fit", "correlation_length": "salze",
                              "bad_strips": "ignore",
                              "boundary_layers": {k: bl_table(t) for k, t in
                                                  zip(["front_top", "front_bottom", "rear_top", "rear_bottom"], bl)}},
            "ingestion": {"turbulence": "von_karman", "table": _l(synthetic_ingestion())},
        },
    })


def template(kind):
    """Text templates: blade, bl, wake, ingestion, case (JSON)."""
    if kind == "blade":
        b = default_case()["rotor"]["front"]["blade"]
        return "r chord stagger_deg\n" + "\n".join(f"{r:.6g} {c:.6g} {s:.6g}" for r, c, s in
                                                     zip(b["r"], b["chord"], b["stagger_deg"])) + "\n"
    if kind == "bl":
        return bl_text(synthetic_bl_tables()[0])
    if kind == "wake":
        w = synthetic_wake()
        return " ".join(w) + "\n" + "\n".join(" ".join(f"{w[k][i]:.6g}" for k in w) for i in range(len(w["bw"]))) + "\n"
    if kind == "ingestion":
        t = synthetic_ingestion()
        return " ".join(t) + "\n" + "\n".join(" ".join(f"{t[k][i]:.6g}" for k in t) for i in range(len(t["z"]))) + "\n"
    if kind == "case":
        import json
        return json.dumps(default_case(), indent=2) + "\n"
    raise ValueError(f"unknown template {kind!r}: blade, bl, wake, ingestion or case")
