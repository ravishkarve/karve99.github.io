"""The three input sections and how they drive the solver.

A case is a dictionary (or a TOML/JSON file) with three sections::

    [rotor]                      # what the rotor is
    stages = 2                   # 1 = front rotor only, 2 = contra-rotating pair
    mach = 0.2                   # flight Mach number
    c0 = 340.0                   # speed of sound [m/s]
    rho = 1.2                    # air density [kg/m^3]
    gap = 0.22                   # axial gap between the rotors [m]
    [rotor.front]
    blades = 10
    rpm = 2865.0                 # or omega = 300.0 [rad/s]
    blade = {r = [...], chord = [...], stagger_deg = [...]}     # hub to tip, or a table file
    [rotor.rear]
    ...

    [noise_model]                # which sources, how, for which observers
    interaction = true           # rotor-wake interaction noise of the rear rotor
    self_noise = ["front", "rear"]   # trailing-edge noise of these rotors
    bl_ingestion = false         # front rotor ingesting a wall boundary layer
    formulation = "full"         # trailing-edge noise: "full" or "simplified" (Amiet)
    strips = 5
    frequency = {min = 50.0, max = 20000.0, n = 50}
    observers = {theta_deg = [30, 60, 90, 120, 150], radius = 2.54}

    [spectra]                    # the source spectra
    [spectra.interaction]        # turbulence of the front-rotor wakes
    turbulence = "von_karman"    # or "liepmann"
    length_scale = 0.4           # factor C (L = C L_table), "pope" or "bw"
    wake = {bw = [...], wrms_bg = [...], wrms_wake = [...], L_bg = [...], L_wake = [...]}
    [spectra.wall_pressure]      # boundary layers at the trailing edge
    model = "rozenberg"          # willmarth_amiet, chase_howe, goody, kim_george, rozenberg, vki
    convection = "del_alamo_fit" # constant (0.8 U), gliebe, del_alamo, del_alamo_fit
    correlation_length = "salze" # corcos, corcos_delta, roger, roger_delta, roger_a110, efimtsov, salze
    boundary_layers = {front_top = "...", front_bottom = "...", rear_top = "...", rear_bottom = "..."}
    [spectra.ingestion]          # turbulence ingested from the wall boundary layer
    turbulence = "von_karman"
    table = {z = [...], ua = [...], la = [...], ut = [...], lt = [...]}

Angles theta* are measured from the upstream flight axis.  Tables can be given
inline, as text, or as file paths (relative to the case file).
"""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path

import numpy as np

from .defaults import DEFAULTS
from .inputs import BL_COLUMNS, SolverError, read_bl_file
from .run import solve

__all__ = ["run", "load", "solver_runs", "case_data", "WALL_PRESSURE", "CONVECTION", "CORRELATION",
           "TURBULENCE", "LENGTH_SCALE", "BAD_STRIPS", "SolverError"]

WALL_PRESSURE = {"willmarth_amiet": "WA", "chase_howe": "CH", "goody": "GY", "kim_george": "KG",
                 "rozenberg": "RZ", "vki": "VKI"}
CONVECTION = {"constant": "0.8", "gliebe": "GLB", "del_alamo": "DEL", "del_alamo_fit": "DEL2"}
CORRELATION = {"corcos": "COR", "corcos_delta": "CORL", "roger": "ROG", "roger_delta": "LGL",
               "roger_a110": "RGS", "efimtsov": "EFP", "salze": "SLZ"}
TURBULENCE = {"von_karman": True, "liepmann": False}
LENGTH_SCALE = {"pope": "Pope", "bw": "BW"}
BAD_STRIPS = {"ignore": "IGNORE", "replace": "REPLACE", "discard": "DISCARD"}
WAKE_COLUMNS = ["bw", "wrms_bg", "wrms_wake", "L_bg", "L_wake"]
INGESTION_COLUMNS = ["z", "ua", "la", "ut", "lt"]
BLADE_COLUMNS = ["r", "chord", "stagger_deg", "sweep", "aoa_deg"]
BL_SURFACES = ["front_top", "front_bottom", "rear_top", "rear_bottom"]


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def load(path):
    """Read a TOML or JSON case; table file paths inside it are resolved against its folder."""
    p = Path(path)
    text = p.read_text()
    if p.suffix.lower() == ".json":
        case = json.loads(text)
    else:
        try:
            import tomllib
        except ImportError:                                   # pragma: no cover - Python < 3.11
            import tomli as tomllib
        case = tomllib.loads(text)
    case.setdefault("base_dir", str(p.resolve().parent))
    return case


def _lookup(name, table, what):
    key = str(name).strip()
    if key in table:
        return table[key]
    low = key.lower().replace(" ", "_").replace("-", "_")
    if low in table:
        return table[low]
    if key in table.values() or key.upper() in table.values():
        return key if key in table.values() else key.upper()
    raise SolverError(f"unknown {what} {name!r}; choose from {', '.join(table)}")


def _text(src, base):
    if isinstance(src, (str, Path)) and "\n" not in str(src):
        p = Path(src)
        if not p.is_absolute():
            p = Path(base) / p
        if p.exists():
            return p.read_text()
        raise SolverError(f"file not found: {src}")
    return str(src)


def _named_table(src, columns, base, what):
    """A table as {column: array}: inline dict, or text/file with a header line of column names
    (any order) or without names (columns in the order given)."""
    if isinstance(src, dict):
        missing = [c for c in columns if c not in src]
        if missing:
            raise SolverError(f"{what}: missing column(s) {', '.join(missing)}")
        return {c: np.atleast_1d(np.asarray(src[c], float)) for c in columns}
    lines = [ln.strip() for ln in _text(src, base).splitlines() if ln.strip()]
    head = lines[0].lstrip("#").replace(",", " ").split()
    rows = [[float(v) for v in ln.replace(",", " ").split()] for ln in lines[1:]]
    tab = np.array(rows, float)
    if all(c in head for c in columns):
        return {c: tab[:, head.index(c)] for c in columns}
    if tab.shape[1] < len(columns):
        raise SolverError(f"{what}: needs columns {', '.join(columns)}")
    return {c: tab[:, i] for i, c in enumerate(columns)}


def _bl_table(src, base):
    """A boundary-layer table -> solver fields. Inline dicts use the column names of
    ``bbn.inputs.BL_COLUMNS``; text/files have 13 columns in that order after one header line."""
    if isinstance(src, dict):
        need = [c for c in BL_COLUMNS if c != "unused"]
        missing = [c for c in need if c not in src]
        if missing:
            raise SolverError(f"boundary-layer table: missing column(s) {', '.join(missing)}")
        col = {c: np.atleast_1d(np.asarray(src.get(c, np.zeros(len(src["R"]))), float)) for c in BL_COLUMNS}
        return {"R": col["R"], "d": col["delta"], "d_star": col["delta_star"], "mom_th": col["theta"],
                "taumax": col["tau_max"], "dpdx": col["dpdx"], "rhow": col["rho_wall"], "uinf": col["U_inf"],
                "pi": col["Pi"], "nuw": col["nu_wall"], "tauwall": col["tau_wall"], "discard": col["discard"]}
    return read_bl_file(_text(src, base))


def _blade(src, base, what):
    if isinstance(src, dict):
        if "r" not in src or "chord" not in src or "stagger_deg" not in src:
            raise SolverError(f"{what}: give r, chord and stagger_deg (hub to tip)")
        d = {c: np.atleast_1d(np.asarray(src[c], float)) for c in BLADE_COLUMNS if c in src}
    else:
        lines = [ln.strip() for ln in _text(src, base).splitlines() if ln.strip()]
        head = lines[0].lstrip("#").replace(",", " ").split()
        tab = np.array([[float(v) for v in ln.replace(",", " ").split()] for ln in lines[1:]], float)
        d = {c: tab[:, head.index(c)] for c in BLADE_COLUMNS if c in head}
        if "r" not in d or "chord" not in d or "stagger_deg" not in d:
            raise SolverError(f"{what}: the table needs columns r, chord, stagger_deg")
    d.setdefault("sweep", np.zeros(d["chord"].size))
    d.setdefault("aoa_deg", np.zeros(d["chord"].size))
    return d


def _omega(rot, what):
    if "omega" in rot:
        return float(rot["omega"])
    if "rpm" in rot:
        return float(rot["rpm"]) * math.pi / 30
    raise SolverError(f"{what}: give rpm or omega [rad/s]")


# ---------------------------------------------------------------------------
# section 1: rotor
# ---------------------------------------------------------------------------

def case_data(rotor, base="."):
    """Rotor section -> solver geometry and conditions."""
    stages = int(rotor.get("stages", 2))
    if "front" not in rotor:
        raise SolverError("rotor: the front rotor is missing")
    fr = rotor["front"]
    bf = _blade(fr["blade"], base, "front rotor blade")
    geom = {"scale": float(rotor.get("scale", 1.0)), "B1": float(fr["blades"]), "eta": float(rotor.get("gap", 0.0)),
            "r1": bf["r"], "c1": bf["chord"], "alpha1": np.radians(bf["stagger_deg"]), "s1": bf["sweep"],
            "c_upstream": 0.0}
    cond = {"Omega1": _omega(fr, "front rotor"), "Mx": float(rotor["mach"]), "c0": float(rotor.get("c0", 340.0)),
            "rho": float(rotor.get("rho", 1.225)), "AoA1": np.radians(bf["aoa_deg"]),
            "Cd": np.zeros(max(2, bf["chord"].size))}
    if "axial_velocity" in fr:
        cond["Ux1"] = np.atleast_1d(np.asarray(fr["axial_velocity"], float))
    if stages == 2:
        if "rear" not in rotor:
            raise SolverError("rotor: stages = 2 needs a rear rotor")
        rr = rotor["rear"]
        br = _blade(rr["blade"], base, "rear rotor blade")
        geom.update(B2=float(rr["blades"]), r2=br["r"], c2=br["chord"], alpha2=np.radians(br["stagger_deg"]),
                    s2=br["sweep"])
        cond.update(Omega2=_omega(rr, "rear rotor"), AoA2=np.radians(br["aoa_deg"]))
        if "axial_velocity" in rr:
            cond["Ux2"] = np.atleast_1d(np.asarray(rr["axial_velocity"], float))
    else:
        geom.update(B2=0.0, r2=np.zeros_like(bf["r"]), c2=np.zeros_like(bf["chord"]),
                    alpha2=np.zeros_like(bf["r"]), s2=np.zeros_like(bf["sweep"]))
        cond.update(Omega2=0.0, AoA2=np.zeros_like(bf["aoa_deg"]))
    return {"geom": geom, "cond": cond}


# ---------------------------------------------------------------------------
# sections 2 and 3: noise model and spectra -> solver runs
# ---------------------------------------------------------------------------

def _common(nm, rotor):
    o = dict(DEFAULTS)
    fr = nm.get("frequency", {})
    ob = nm.get("observers", {})
    o.update(st_num=int(nm.get("strips", 5)), phi_num=int(nm.get("azimuth_points", 50)),
             f_l=float(fr.get("min", 50.0)), f_h=float(fr.get("max", 20000.0)), f_num=int(fr.get("n", 50)),
             r0=float(ob.get("radius", 2.54)),
             theta=list(np.radians(np.atleast_1d(np.asarray(ob.get("theta_deg", [30, 60, 90, 120, 150]), float)))),
             chapman=bool(nm.get("chapman", False)), emission_angle=bool(nm.get("emission_angle", False)),
             contraction_perc=float(nm.get("contraction_percent", 100)),
             axial_velocity_tables=any("axial_velocity" in rotor.get(k, {}) for k in ("front", "rear")))
    return o


def _self_rotors(nm):
    s = nm.get("self_noise", [])
    if s is True:
        return ["front", "rear"]
    if not s:
        return []
    s = [s] if isinstance(s, str) else list(s)
    bad = [x for x in s if x not in ("front", "rear")]
    if bad:
        raise SolverError(f"noise_model.self_noise: use 'front' and/or 'rear' (got {bad})")
    return [x for x in ("front", "rear") if x in s]


def _formulation(nm):
    f = str(nm.get("formulation", "full")).lower()
    if f not in ("full", "simplified", "amiet"):
        raise SolverError("noise_model.formulation: 'full' or 'simplified'")
    return f != "full"


def solver_runs(case):
    """The solver calls needed for a case: list of (purpose, options, keyword inputs)."""
    base = case.get("base_dir", ".")
    rotor, nm, sp = case.get("rotor", {}), case.get("noise_model", {}), case.get("spectra", {})
    stages = int(rotor.get("stages", 2))
    data = case_data(rotor, base)
    inter = bool(nm.get("interaction", False))
    selfs = _self_rotors(nm)
    ingest = bool(nm.get("bl_ingestion", False))
    if not (inter or selfs or ingest):
        raise SolverError("noise_model: select at least one source (interaction, self_noise or bl_ingestion)")
    if inter and stages < 2:
        raise SolverError("interaction noise needs two rotors (rotor.stages = 2)")
    if "rear" in selfs and stages < 2:
        raise SolverError("self noise of the rear rotor needs rotor.stages = 2")
    simplified = _formulation(nm)
    runs = []
    base_opt = _common(nm, rotor)

    wake = None
    if inter:
        si = sp.get("interaction", {})
        if "wake" not in si:
            raise SolverError("spectra.interaction.wake: the wake table is needed for interaction noise")
        wake = _named_table(si["wake"], WAKE_COLUMNS, base, "wake table")
        ls = si.get("length_scale", 0.4)
        L = LENGTH_SCALE[str(ls).lower()] if isinstance(ls, str) and str(ls).lower() in LENGTH_SCALE else float(ls)
        inter_opt = dict(Karman_spec=_lookup(si.get("turbulence", "von_karman"), TURBULENCE, "turbulence spectrum"),
                         L=L)
    bl = None
    if selfs:
        wp = sp.get("wall_pressure", {})
        tabs = wp.get("boundary_layers", {})
        need = [f"{r}_{s}" for r in selfs for s in ("top", "bottom")]
        if "rear" in selfs:
            need = BL_SURFACES
        missing = [k for k in need if k not in tabs]
        if missing:
            raise SolverError(f"spectra.wall_pressure.boundary_layers: missing {', '.join(missing)}")
        bl = [_bl_table(tabs[k], base) for k in need]
        self_opt = dict(phi_sw=_lookup(wp.get("model", "rozenberg"), WALL_PRESSURE, "wall-pressure model"),
                        Uc=_lookup(wp.get("convection", "del_alamo_fit"), CONVECTION, "convection model"),
                        lr=_lookup(wp.get("correlation_length", "salze"), CORRELATION, "correlation-length model"),
                        baddata=_lookup(wp.get("bad_strips", "ignore"), BAD_STRIPS, "bad-strip option"))

    if inter and selfs == ["front", "rear"] and not simplified:
        o = dict(base_opt, StageCount=2, noise_type="BOTH", amiet=False, **inter_opt, **self_opt)
        runs.append(("rotor", o, dict(case_data=data, bl_data=bl, wake_data=wake)))
    else:
        if inter:
            o = dict(base_opt, StageCount=2, noise_type="BRWI", amiet=False, **inter_opt)
            runs.append(("rotor", o, dict(case_data=data, wake_data=wake)))
        if selfs:
            sc = 2 if "rear" in selfs else 1
            o = dict(base_opt, StageCount=sc, noise_type="BRTE", amiet=simplified, **self_opt)
            if sc == 1:
                o["contraction_perc"] = 100
            runs.append(("self", o, dict(case_data=_single(data) if sc == 1 else data, bl_data=bl)))
    if ingest:
        ing = nm.get("ingestion", {})
        si = sp.get("ingestion", {})
        o = dict(base_opt, StageCount=1, rotor_noise=False, installation_noise=True, p_noise_type="BPRI_BL",
                 noise_type="BRWI", amiet=True, chapman=False,
                 dwall=float(ing.get("wall_distance", 0.25)), bl_height=float(ing.get("bl_height", 0.1)),
                 wall=bool(ing.get("hard_wall", True)), partial_loading=bool(ing.get("partial_loading", True)),
                 BPRI_correlation=bool(ing.get("blade_correlation", True)),
                 spectral_phi_obs=list(np.radians(np.atleast_1d(np.asarray(ing.get("observer_azimuth_deg", [0.0]),
                                                                            float)))),
                 Karman_spec=_lookup(si.get("turbulence", "von_karman"), TURBULENCE, "turbulence spectrum"))
        table = None
        if si.get("table") is not None:
            t = _named_table(si["table"], INGESTION_COLUMNS, base, "ingestion table")
            table = {"bl_wnd": t["z"], "bl_ua": t["ua"], "bl_la": t["la"], "bl_ut": t["ut"], "bl_lt": t["lt"]}
            o["bl_turbulence_table"] = True
        else:
            c = si.get("constants", {})
            o.update(bl_turbulence_table=False, ua=float(c.get("ua", 1.0)), la=float(c.get("la", 0.3)),
                     ut=float(c.get("ut", 2.0)), lt=float(c.get("lt", 0.1)))
        runs.append(("ingestion", o, dict(case_data=_single(data), bl_ingestion=table)))
    return runs


def _single(data):
    d = copy.deepcopy(data)
    g, c = d["geom"], d["cond"]
    g.setdefault("B2", 0.0)
    for k in ("r2", "c2", "alpha2", "s2"):
        g.setdefault(k, np.zeros(1))
    c.setdefault("Omega2", 0.0)
    c.setdefault("AoA2", np.zeros(1))
    return d


def run(case, progress=None):
    """Run a case (dict with rotor / noise_model / spectra sections, or a path) -> :class:`bbn.results.Result`."""
    from .results import build
    if isinstance(case, (str, Path)) and os.path.exists(str(case)):
        case = load(case)
    outs = []
    for purpose, opt, kw in solver_runs(case):
        outs.append((purpose, solve(opt, progress=progress, **kw)))
    return build(case, outs)
