"""JSON API used by the dashboard (Pyodide worker or the local server)."""
from __future__ import annotations

import json
import time
import traceback

import numpy as np

__all__ = ["run", "default_case", "parse_table", "template", "options"]


def _ok(**kw):
    return json.dumps(dict(ok=True, **kw), allow_nan=False)


def _err(e):
    return json.dumps({"ok": False, "error": str(e), "trace": traceback.format_exc(limit=3)})


def _clean(x):
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (float, np.floating)):
        return float(x) if np.isfinite(x) else None
    return x


def run(case_json):
    from .config import run as run_case
    try:
        case = json.loads(case_json) if isinstance(case_json, str) else case_json
        t0 = time.time()
        res = run_case(case)
        return _ok(result=_clean(res.to_dict()), seconds=round(time.time() - t0, 2))
    except Exception as e:                                   # noqa: BLE001
        return _err(e)


def default_case():
    from .examples import default_case as dc
    return _ok(case=dc())


def template(kind):
    from .examples import template as t
    try:
        return _ok(text=t(kind))
    except Exception as e:                                   # noqa: BLE001
        return _err(e)


def options():
    from .config import BAD_STRIPS, CONVECTION, CORRELATION, LENGTH_SCALE, TURBULENCE, WALL_PRESSURE
    return _ok(wall_pressure=list(WALL_PRESSURE), convection=list(CONVECTION), correlation_length=list(CORRELATION),
               turbulence=list(TURBULENCE), length_scale=list(LENGTH_SCALE), bad_strips=list(BAD_STRIPS))


def parse_table(kind, text):
    """Read a table file for the dashboard: blade, bl, wake or ingestion -> {column: list}."""
    from .config import INGESTION_COLUMNS, WAKE_COLUMNS, _blade, _bl_table, _named_table
    from .inputs import BL_COLUMNS
    try:
        if kind == "blade":
            d = _blade(text, ".", "blade table")
            return _ok(table=_clean({k: v.tolist() for k, v in d.items() if k in ("r", "chord", "stagger_deg")}))
        if kind == "bl":
            t = _bl_table(text, ".")
            names = {"R": "R", "d": "delta", "d_star": "delta_star", "mom_th": "theta", "taumax": "tau_max",
                     "dpdx": "dpdx", "rhow": "rho_wall", "uinf": "U_inf", "pi": "Pi", "nuw": "nu_wall",
                     "tauwall": "tau_wall", "discard": "discard"}
            return _ok(table=_clean({names[k]: np.asarray(v).tolist() for k, v in t.items()}),
                       columns=[c for c in BL_COLUMNS if c != "unused"])
        if kind == "wake":
            return _ok(table=_clean({k: v.tolist() for k, v in _named_table(text, WAKE_COLUMNS, ".", "wake table").items()}))
        if kind == "ingestion":
            return _ok(table=_clean({k: v.tolist() for k, v in
                                     _named_table(text, INGESTION_COLUMNS, ".", "ingestion table").items()}))
        raise ValueError(f"unknown table kind {kind!r}")
    except Exception as e:                                   # noqa: BLE001
        return _err(e)
