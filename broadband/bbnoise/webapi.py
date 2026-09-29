"""JSON API shared by the in-browser (Pyodide) worker and the local HTTP server.

Every function takes and returns JSON strings so it can be called from
JavaScript without conversion.
"""
from __future__ import annotations

import json
import traceback
from dataclasses import asdict

import numpy as np

from . import __version__
from .cases import CASES, get_case
from .model import DEFAULTS, run_case
from .wallpressure import WPS_INFO, WPS_MODELS, BoundaryLayer, corcos_ly, wps, wps_normalised


def _ok(payload):
    return json.dumps({"ok": True, **payload}, allow_nan=False, default=_default)


def _err(e):
    return json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}",
                       "trace": traceback.format_exc().splitlines()[-4:]})


def _default(o):
    if isinstance(o, (np.floating,)):
        v = float(o)
        return v if np.isfinite(v) else None
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def _clean(obj):
    """Replace NaN/inf (not JSON) by None recursively."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (float, np.floating)):
        return float(obj) if np.isfinite(obj) else None
    if isinstance(obj, np.integer):
        return int(obj)
    return obj


def meta(_=None):
    try:
        return _ok({"version": __version__, "defaults": DEFAULTS,
                    "wps_models": [{"key": k, "info": WPS_INFO[k]} for k in WPS_MODELS],
                    "spectra": ["vonkarman", "liepmann"], "formulations": ["full", "simplified"],
                    "cases": [{"key": k, "name": c["name"], "type": c["type"],
                               "description": c.get("description", ""), "reference": c.get("reference", "")}
                              for k, c in CASES.items()]})
    except Exception as e:  # pragma: no cover
        return _err(e)


def case(key):
    try:
        return _ok({"case": get_case(key)})
    except Exception as e:
        return _err(e)


def run(case_json, progress=None):
    try:
        c = json.loads(case_json) if isinstance(case_json, str) else case_json
        res = run_case(c, progress=progress)
        return _ok({"result": _clean(res.to_dict())})
    except Exception as e:
        return _err(e)


def wall_pressure(bl_json, models_json=None):
    """Normalised and dimensional wall-pressure spectra for a boundary layer."""
    try:
        d = json.loads(bl_json) if isinstance(bl_json, str) else dict(bl_json)
        models = json.loads(models_json) if isinstance(models_json, str) else (models_json or list(WPS_MODELS))
        fields = {k: v for k, v in d.items() if k in BoundaryLayer.__dataclass_fields__ and v is not None
                  and k != "notes"}
        bl = BoundaryLayer(**fields).complete()
        wt = np.geomspace(0.01, 100.0, 120)
        f = np.geomspace(d.get("f_min", 50.0), d.get("f_max", 50000.0), 120)
        out = {"bl": _clean({k: v for k, v in bl.as_dict().items() if k != "notes"}), "notes": bl.notes,
               "omega_tilde": wt.tolist(), "f": f.tolist(), "models": []}
        for m in models:
            nrm = wps_normalised(m, wt, bl)
            dim = wps(m, 2 * np.pi * f, bl) * 2 * np.pi     # one-sided per Hz
            out["models"].append({"key": m, "info": WPS_INFO.get(m, ""),
                                  "normalised_db": _clean(10 * np.log10(np.maximum(nrm, 1e-30))),
                                  "psd_db": _clean(10 * np.log10(np.maximum(dim, 1e-30) / 4e-10))})
        out["corcos_ly"] = _clean(corcos_ly(2 * np.pi * f, 0.7 * bl.Ue))
        return _ok(out)
    except Exception as e:
        return _err(e)


def verify(_=None):
    try:
        from .verification import run_all
        return _ok({"checks": _clean([asdict(c) for c in run_all()])})
    except Exception as e:
        return _err(e)


API = {"meta": meta, "case": case, "run": run, "wall_pressure": wall_pressure, "verify": verify}
