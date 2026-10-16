"""Run cases from TOML or JSON configuration files.

A configuration describes the propeller (or names a built-in one), the operating points and
optionally model switches.  Example (TOML)::

    [propeller]
    builtin = "sr3_class"          # or give the geometry below
    # blades = 8
    # diameter = 0.622
    # [propeller.blade]
    # r_R = [...]; chord_D = [...]; beta_deg = [...]; t_c = [...]; cl_design = [...]
    # mca_D = [...]                # mid-chord alignment (sweep), along the chord, / D
    # thickness_form = "naca16"; mean_line = "a1"
    # [propeller.spinner]
    # hub_radius_D = 0.1175; nose_length_D = 0.5; waist = 0.08

    [[point]]                      # one table per operating point
    mach = 0.8
    altitude = 10668.0
    tip_speed = 243.84
    CP = 1.7                       # solve the pitch for this power coefficient
                                   # (or CT = ..., or dbeta = ... / beta75 = ... for fixed pitch)

    [sweep]                        # optional: a map, varying one point parameter
    parameter = "CP"
    values = [0.8, 1.2, 1.6, 2.0]

    [model]                        # optional switches (SectionOptions / SolverSettings / WakeSettings)
    xtr_upper = 1.0
    choke_spill = true
"""
from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

import numpy as np

from .geometry import Blade, Nacelle, Propeller
from .section import SectionOptions
from .solver import OperatingPoint, PropellerSolver, SolverSettings
from .wake import WakeSettings


def load_config(path):
    path = Path(path)
    text = path.read_text()
    if path.suffix.lower() == ".json":
        return json.loads(text)
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib
    return tomllib.loads(text)


def build_propeller(cfg, base_dir="."):
    pc = cfg.get("propeller", {})
    if "file" in pc:
        return Propeller.load(Path(base_dir) / pc["file"])
    if "builtin" in pc:
        from . import cases
        return cases.reference(pc["builtin"])
    b = pc["blade"]
    blade = Blade(**{k: b[k] for k in b if k in Blade.__dataclass_fields__})
    nac = None
    if "spinner" in pc:
        sp = dict(pc["spinner"])
        hub = sp.pop("hub_radius_D", 0.5 * blade.hub_ratio)
        nac = Nacelle.spinner(hub, **sp)
    elif "nacelle" in pc:
        nac = Nacelle(np.asarray(pc["nacelle"]["x_D"]), np.asarray(pc["nacelle"]["r_D"]))
    return Propeller(blade, int(pc["blades"]), float(pc["diameter"]), nacelle=nac,
                     name=pc.get("name", "propeller"))


def _split_model(model):
    def pick(cls):
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in model.items() if k in names})
    known = set()
    for cls in (SectionOptions, SolverSettings, WakeSettings):
        known |= {f.name for f in fields(cls)}
    unknown = set(model) - known
    if unknown:
        raise ValueError(f"unknown [model] keys: {sorted(unknown)}")
    return pick(SectionOptions), pick(SolverSettings), pick(WakeSettings)


def run_config(path, progress=None):
    """Run every operating point (and sweep) of a configuration; returns a list of results."""
    cfg = load_config(path)
    prop = build_propeller(cfg, Path(path).parent)
    sec, st, wk = _split_model(cfg.get("model", {}))
    sv = PropellerSolver(prop, section=sec, wake=wk, settings=st)
    points = cfg.get("point", [])
    if isinstance(points, dict):
        points = [points]
    sweep = cfg.get("sweep")
    jobs = []
    for pt in points:
        if sweep:
            for v in sweep["values"]:
                jobs.append({**pt, sweep["parameter"]: v})
        else:
            jobs.append(pt)
    results = []
    prev = None
    for job in jobs:
        res = run_point(sv, job, dbeta0=prev)
        prev = res.dbeta
        results.append(res)
        if progress:
            progress(res)
    return prop, results


def run_point(sv: PropellerSolver, pt, dbeta0=None):
    pt = dict(pt)
    target = {k: pt.pop(k) for k in ("CP", "CT") if k in pt}
    beta75 = pt.pop("beta75", None)
    names = {f.name for f in fields(OperatingPoint)}
    unknown = set(pt) - names
    if unknown:
        raise ValueError(f"unknown operating-point keys: {sorted(unknown)}")
    op = OperatingPoint(**pt)
    if beta75 is not None:
        op.dbeta = float(beta75) - sv.prop.beta_ref(0.0)
    if target:
        return sv.solve_for(op, dbeta0=dbeta0 if dbeta0 is not None else op.dbeta, **target)
    return sv.solve(op)
