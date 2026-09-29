"""JSON API used by the web dashboard (Pyodide worker) and the precompute script.

All functions take and return JSON strings so they can be called from
JavaScript without conversion.  Results are compacted (rounded, trimmed) so a
whole incidence sweep fits comfortably in a browser.
"""
from __future__ import annotations

import json
import math
import time
import traceback

import numpy as np

from .config import build_case, parse_config, run_case
from .geometry import Blade


def _r(a, sig=5):
    """Round an array/scalar to ``sig`` significant digits (JSON friendly)."""
    if a is None:
        return None
    if isinstance(a, (list, tuple, np.ndarray)):
        return [_r(v, sig) for v in (a.tolist() if isinstance(a, np.ndarray) else a)]
    if isinstance(a, (bool, np.bool_)):
        return bool(a)
    if isinstance(a, (int, np.integer)):
        return int(a)
    if isinstance(a, (float, np.floating)):
        a = float(a)
        if not math.isfinite(a):
            return None
        if a == 0.0:
            return 0.0
        return float(f"{a:.{sig}g}")
    return a


PERF_KEYS = ("omega", "omega_exit", "omega_inviscid", "omega_viscous", "beta1", "beta2",
             "beta2_inviscid", "incidence", "deviation", "turning", "M1", "M2", "M1_actual",
             "p2_p1", "p02_p01", "diffusion_factor", "zweifel", "velocity_ratio", "xtr_upper",
             "xtr_lower", "theta_te", "dstar_te", "H_te_upper", "H_te_lower", "sep_upper",
             "sep_lower", "inlet_metal_angle", "exit_metal_angle", "sweep_value", "peak_mis",
             "choked", "cl", "cd", "cd_momentum", "beta_m", "lift_drag", "beta1_inlet_plane")


def compact(result, field_stride=2):
    """Compact JSON-able summary of a :class:`CascadeResult`."""
    b = result.blade
    out = {
        "name": b["name"],
        "method": result.method,
        "flow": {k: _r(v) for k, v in result.flow.items()},
        "viscous": result.viscous,
        "blade": {"x": _r(b["x"], 6), "y": _r(b["y"], 6), "pitch": _r(b["pitch"]),
                  "chord": _r(b["chord"]), "stagger": _r(b["stagger_deg"]),
                  "solidity": _r(b["solidity"]), "max_thickness": _r(b["max_thickness"]),
                  "inlet_metal_angle": _r(b["inlet_metal_angle"]),
                  "exit_metal_angle": _r(b["exit_metal_angle"]), "te_gap": _r(b["te_gap"])},
        "perf": {k: _r(result.performance[k]) for k in PERF_KEYS if k in result.performance},
        "surf": {},
        "bl": None,
        "field": None,
        "warnings": list(result.warnings),
        "convergence": {k: _r(v) for k, v in result.convergence.items()
                        if isinstance(v, (int, float, bool, np.floating, np.integer))},
    }
    for srf in (result.upper, result.lower):
        o = np.argsort(srf.xc)
        out["surf"][srf.name] = {"xc": _r(srf.xc[o], 4), "mis": _r(srf.mis[o], 4),
                                 "cp": _r(srf.cp[o], 4)}
    if result.bl_upper is not None:
        out["bl"] = {}
        for bl in (result.bl_upper, result.bl_lower):
            out["bl"][bl.name] = {"xc": _r(bl.xc, 4), "H": _r(bl.H, 4), "theta": _r(bl.theta, 4),
                                  "dstar": _r(bl.dstar, 4), "cf": _r(bl.cf, 4),
                                  "ue": _r(bl.ue, 4), "re_theta": _r(bl.re_theta, 4),
                                  "turb": [int(t) for t in bl.turbulent],
                                  "xtr": _r(bl.xtr_c), "forced": bool(bl.forced),
                                  "sep": _r(bl.separated, 4)}
    if result.field_data is not None:
        X = np.asarray(result.field_data["x"])
        Y = np.asarray(result.field_data["y"])
        M = np.asarray(result.field_data["mach"])
        k = max(1, int(field_stride))
        out["field"] = {"x": _r(X, 5), "y": _r(Y, 5), "mach": _r(M, 4),
                        "pitch": _r(result.field_data["pitch"])}
    return out


def run_config_json(text, fmt=".toml", progress=None):
    """Run a configuration given as text; returns JSON {ok, results | error}."""
    t0 = time.time()
    try:
        case = build_case(parse_config(text, fmt))
        results = run_case(case, progress=progress)
        payload = {"ok": True, "case": case.name, "sweep": case.sweep,
                   "results": [compact(r) for r in results], "seconds": time.time() - t0}
    except Exception as exc:
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc(limit=3)}
    return json.dumps(payload)


def blade_preview_json(geometry_json):
    """Blade geometry only (fast), for live previews while editing inputs."""
    from .config import build_blade
    try:
        blade = build_blade(json.loads(geometry_json))
        d = blade.to_dict()
        return json.dumps({"ok": True, "x": _r(d["x"], 6), "y": _r(d["y"], 6), "pitch": d["pitch"],
                           "stagger": _r(d["stagger_deg"]), "solidity": _r(d["solidity"]),
                           "max_thickness": _r(d["max_thickness"])})
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


def version_json():
    from . import __version__
    return json.dumps({"version": __version__})
