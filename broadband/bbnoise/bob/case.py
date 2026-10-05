"""``type = "bob"`` cases: run the BoB 3.5 port from a case dictionary.

Case layout (BoB names throughout)::

    {"type": "bob",
     "launch_file": "launch_BoB.m",          # optional: BoB launch script (opt.* lines)
     "options": {...},                       # opt.* values (override the launch file)
     "inputs": {"geom": {...}, "cond": {...}} or "inputs_file": "INPUT/case.mat",
     "bl_files": [front top, front bottom, rear top, rear bottom],   # paths or file text
     "wake": {"bw": [...], "wrms_bg": [...], "wrms_wake": [...], "L_bg": [...], "L_wake": [...]}
             or "wake_file": "Wake_data.mat",
     "bl_ingestion": {"z": [...], "ua": [...], "la": [...], "ut": [...], "lt": [...]} or a path,
     "base_dir": "."}

Spectra are reported as one-sided PSDs per hertz, 4 pi |Spp| (BoB's
``*_directivity.dat`` convention), and sound power as 4 pi |P1| (BoB's PWL).
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np

from .inputs import BoBError, read_bl_file, read_bl_ingestion
from .options import DEFAULTS, parse_launch_file
from .pp import _power
from .run import run_bob

__all__ = ["bob_options", "run_bob_raw", "run_bob_case", "case_from_launch"]


def _jsonable(v):
    if isinstance(v, np.ndarray):
        return v.tolist()
    if isinstance(v, (np.floating, np.integer)):
        return v.item()
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


def bob_options(case, base_dir="."):
    opt = dict(DEFAULTS)
    lf = case.get("launch_file")
    if lf:
        p = Path(lf) if Path(lf).is_absolute() else Path(base_dir) / lf
        opt.update(parse_launch_file(p.read_text()))
    if case.get("launch_text"):
        opt.update(parse_launch_file(case["launch_text"]))
    opt.update(case.get("options", {}))
    return opt


def _resolve(base, v):
    if isinstance(v, str) and "\n" not in v:
        p = Path(v) if Path(v).is_absolute() else Path(base) / v
        return str(p)
    return v


def _bl_sources(case, base):
    files = case.get("bl_files")
    if not files:
        return None
    return [read_bl_file(_resolve(base, f)) if not isinstance(f, dict) else f for f in files]


def _bl_struct(sources, stage_count):
    out = {}
    for rot in range(stage_count):
        for side, d in (("t", sources[2 * rot]), ("b", sources[2 * rot + 1])):
            for k, v in d.items():
                if k == "R":
                    continue
                out.setdefault(f"{k}_{side}", []).append(np.asarray(v, float))
    return {k: np.array(v) for k, v in out.items()}


def _inputs(case, base):
    if "inputs" in case:
        return {"geom": case["inputs"]["geom"], "cond": case["inputs"]["cond"]}
    if case.get("inputs_file"):
        return _resolve(base, case["inputs_file"])
    return None


def _wake(case, base):
    w = case.get("wake")
    if isinstance(w, dict):
        return {k: np.atleast_1d(np.asarray(w[k], float)) for k in ("bw", "wrms_bg", "wrms_wake", "L_bg", "L_wake")}
    if case.get("wake_file"):
        from .inputs import load_wake_data
        return load_wake_data(_resolve(base, case["wake_file"]))
    return None


def _ingestion(case, base):
    v = case.get("bl_ingestion")
    if v is None:
        return None
    if isinstance(v, dict):
        z = v.get("z", v.get("bl_wnd"))
        return {"bl_wnd": np.asarray(z, float), "bl_ua": np.asarray(v.get("ua", v.get("bl_ua")), float),
                "bl_la": np.asarray(v.get("la", v.get("bl_la")), float),
                "bl_ut": np.asarray(v.get("ut", v.get("bl_ut")), float),
                "bl_lt": np.asarray(v.get("lt", v.get("bl_lt")), float)}
    return read_bl_ingestion(_resolve(base, v))


def run_bob_raw(case, progress=None):
    """Run a BoB case and return :func:`run_bob`'s raw output (``.Spps``, ``.lists``, ...)."""
    base = case.get("base_dir", ".")
    opt = bob_options(case, base)
    srcs = _bl_sources(case, base)
    bl_data = _bl_struct(srcs, int(opt["StageCount"])) if srcs else None
    return run_bob(opt, base, case_data=_inputs(case, base), bl_data=bl_data, wake_data=_wake(case, base),
                   bl_ingestion=_ingestion(case, base), progress=progress)


def run_bob_case(case, res, progress=None):
    """Fill a :class:`bbnoise.model.CaseResult` from a BoB case."""
    from ..model import Curve
    t0 = time.time()
    out = run_bob_raw(case, progress)
    res.bob = out
    o = out.opt
    lists = out.lists if out.lists is not None else (out.p.lists if out.p is not None else None)
    omega = np.asarray(lists.omega, float)
    res.f = omega / (2 * math.pi) / lists.scale
    theta_star = np.atleast_1d(np.asarray(o["theta"], float))
    th0 = round(float(np.degrees(theta_star[0])), 6)
    form = "BoB Amiet" if o.get("amiet") else "BoB full"
    st = int(o["st_num"])
    info_rotors = {}

    def strips_info(rot, geom, flow):
        r = geom.rj[:, rot]
        U = flow.U_X2[:, 0] if (rot == 1 and hasattr(flow, "U_X2") and np.any(flow.U_X2)) else flow.Ux[:, rot, 0]
        return {"r": r, "dr": np.full(st, geom.drj[rot]), "chord": geom.C[:, rot], "U": U}

    def add(key, label_mech, rotor, cat, variant, rot=None, Spp=None, geom=None, flow=None, power_lists=None):
        S = np.asarray(out.Spps[key] if Spp is None else Spp)
        S = S[..., None] if S.ndim == 3 else S
        G = 4 * math.pi * np.abs(S[:, 0, st, 0])
        direc = None
        if S.shape[1] > 1:
            oas = [10 * math.log10(max(np.trapezoid(4 * math.pi * np.abs(S[:, t, st, 0]), res.f), 1e-300) / 4e-10)
                   for t in range(S.shape[1])]
            direc = {"theta": np.round(np.degrees(theta_star), 6), "oaspl": np.array(oas)}
        pwl = None
        if power_lists is not None and S.shape[1] > 1:
            P1 = _power(power_lists, o, geom, flow, S[..., 0])
            pwl = 4 * math.pi * np.abs(P1[:, st]) * lists.scale ** 3          # BoB's PWL, per Hz
        strips = None
        if rot is not None and geom is not None:
            si = strips_info(rot, geom, flow)
            si["G"] = 4 * math.pi * np.abs(S[:, 0, :st, 0]).T
            strips = si
        res.curves.append(Curve(f"{rotor}: {label_mech} - {variant} - {form}", label_mech, form, variant, rotor,
                                th0, G, direc, pwl, category=cat, strips=strips))

    if out.geom is not None:
        g, fl = out.geom, out.flow
        names = ["front", "rear"]
        for rot in range(int(o["StageCount"])):
            si = strips_info(rot, g, fl)
            info_rotors[names[rot]] = {
                "name": names[rot], "B": float(g.B[rot]), "rpm": float(g.OM[rot] * 30 / math.pi),
                "bpf_hz": float(g.B[rot] * g.OM[rot] / (2 * math.pi)), "tip_mach_relative": float(si["U"][-1] / fl.c0),
                "Mx": float(fl.MX),
                "strips": [{"r": float(si["r"][j]), "dr": float(si["dr"][j]), "chord": float(si["chord"][j]),
                            "U": float(si["U"][j]), "psi_deg": float(90 - np.degrees(g.alpha[j, rot])),
                            "stagger_deg": float(np.degrees(g.alpha[j, rot])), "aoa_deg": float(g.alfa[j, rot]),
                            "M": float(si["U"][j] / fl.c0)} for j in range(st)]}
        if isinstance(out.Spps.get("BRWI"), np.ndarray):
            add("BRWI", "BRWI (rotor-wake interaction)", "rear", "interaction",
                "von Karman" if o.get("Karman_spec", True) else "Liepmann", 1, geom=g, flow=fl, power_lists=out.lists)
        for key, rot in (("BRTE1", 0), ("BRTE2", 1)):
            if isinstance(out.Spps.get(key), np.ndarray):
                add(key, "BRTE (trailing edge)", names[rot], "self", f"{o.get('phi_sw')}, Uc {o.get('Uc')}, lr {o.get('lr')}",
                    rot, geom=g, flow=fl, power_lists=out.lists)
    if out.p is not None:
        for key, var in (("BPRI", "total"), ("BPRINW", "no wall"), ("BPRIC1", "interference C1"),
                         ("BPRIC2", "interference C2"), ("BPRIA", "image source")):
            add(key, "BL ingestion (BPRI_BL)", "front", "interaction", var)
    res.info["rotors"] = info_rotors
    res.info["bob"] = {"options": _jsonable({k: v for k, v in o.items() if not isinstance(v, dict)}),
                       "seconds": round(time.time() - t0, 3),
                       "theta_convention": "theta* from the upstream axis (Airbus convention, opt.theta)"}
    return res


def case_from_launch(launch_path, name=None):
    """A ``type = "bob"`` case that runs a BoB launch script from its own folder."""
    p = Path(launch_path).resolve()
    return {"type": "bob", "name": name or f"BoB: {p.parent.name}/{p.name}", "launch_file": p.name,
            "base_dir": str(p.parent)}
