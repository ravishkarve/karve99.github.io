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
                    "spectra": ["vonkarman", "liepmann"], "formulations": ["full", "simplified", "eq3.18", "eq5.7", "eq2.73"],
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


def estimate_bl(case_json, rotor=None):
    """Mid-span boundary layers of a case (for pre-filling user boundary-layer inputs)."""
    try:
        from .boundarylayer import make_boundary_layers
        from .model import DEFAULTS, build_rotor
        from .model import normalise_case
        c = normalise_case(json.loads(case_json) if isinstance(case_json, str) else dict(case_json))
        fluid = dict(DEFAULTS["fluid"], **c.get("fluid", {}))
        sn = c.get("brte") or {}
        spec = sn.get("boundary_layer", {"method": "bpm"})
        if c.get("type", "rotor") == "rotor":
            names = [r.get("name") for r in c["rotors"]]
            which = rotor if rotor in names else (sn.get("rotors") or names)[0]
            spec = (sn.get("boundary_layers") or {}).get(which) or spec
            rot = build_rotor(c["rotors"][names.index(which)], fluid)
            st = rot.strips()[len(rot.strips()) // 2]
            chord, U, rR, where = st.chord, st.U, st.r / rot.r_tip, f"{which} rotor, r/R = {st.r / rot.r_tip:.2f}"
        else:
            chord, U, rR, where = float(c["airfoil"]["chord"]), float(c["airfoil"]["U"]), None, "airfoil"
        def pack(bls, chord, U):
            return {side: _clean({"delta_star_over_c": bl.delta_star / chord, "delta_over_c": bl.delta / chord,
                                  "theta_over_c": bl.theta / chord, "H": bl.H, "cf": bl.cf, "beta_c": bl.beta_c,
                                  "Ue_over_U": bl.Ue / U, "Pi": bl.Pi}) for side, bl in bls.items()}

        bls = make_boundary_layers(spec, chord, U, fluid["rho"], fluid["nu"], fluid["c0"], r_over_R=rR,
                                   r_tip=None if rR is None else rot.r_tip)
        radial = []
        if rR is not None:
            for st in rot.strips():
                b = make_boundary_layers(spec, st.chord, st.U, fluid["rho"], fluid["nu"], fluid["c0"],
                                         r_over_R=st.r / rot.r_tip, r_tip=rot.r_tip)
                radial.append({"r_over_R": st.r / rot.r_tip, **pack(b, st.chord, st.U)})
        return _ok({"where": where, "chord": chord, "U": U, "sides": pack(bls, chord, U), "radial": radial})
    except Exception as e:
        return _err(e)


def parse_table(kind, text, r_tip=None):
    """Parse an uploaded blade ('blade') or boundary-layer ('bl') table into case entries."""
    try:
        from .tables import bl_from_table, blade_from_table
        r_tip = float(r_tip) if r_tip not in (None, "", "null") else None
        if kind == "blade":
            return _ok({"blade": blade_from_table(text, r_tip)})
        return _ok({"boundary_layer": bl_from_table(text, r_tip)})
    except Exception as e:
        return _err(e)


def template(kind):
    from .tables import BL_TEMPLATE, BLADE_TEMPLATE
    return _ok({"text": BLADE_TEMPLATE if kind == "blade" else BL_TEMPLATE})


def verify(_=None):
    try:
        from .verification import run_all
        return _ok({"checks": _clean([asdict(c) for c in run_all()])})
    except Exception as e:
        return _err(e)


API = {"meta": meta, "case": case, "run": run, "wall_pressure": wall_pressure, "estimate_bl": estimate_bl,
       "parse_table": parse_table, "template": template, "verify": verify}
