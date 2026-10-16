"""Validation and ablation runs against the published NASA propfan tests.

    python tools/validate.py [-j JOBS] [-o data/validation.json]

Cases (all on the reconstructed, inverse-designed SR-3-class and SR-2-class propellers):

* design point M 0.8, J 3.06, CP 1.70 (NASA Lewis 8x6 ft tunnel conditions), SR-3 and SR-2;
* SR-3 Mach trend at constant design power loading (CP/J^3 and tip speed fixed), M 0.6-0.85;
* M 0.8 power sweeps at J 3.06 (low to high power), SR-3 and SR-2;
* take-off, M 0.20, J 0.875, CP 1.00 (10x10 ft tunnel, sea-level conditions), SR-3 and SR-2;
* ablation at the SR-3 design point and take-off: each model component switched off in turn.

Measured values (net efficiency):
    SR-3 design 78.7 %, SR-2 design 75.8 %            (Jeracki, Mikkelson & Blaha, NASA TM-79124)
    SR-3 M 0.85 74.3 %                                 (NASA TM-88969)
    SR-3 take-off 54.9 %, SR-2 take-off 50.2 %         (Stefko & Jeracki, NASA TM-87030)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

MEASURED = {
    "sr3_design": 0.787, "sr2_design": 0.758, "sr3_m085": 0.743,
    "sr3_takeoff": 0.549, "sr2_takeoff": 0.502,
}

ABLATIONS = {
    "full model": ({}, {}),
    "isolated aerofoils (no cascade)": ({"cascade": False}, {}),
    "naive Prandtl-Glauert (no lattice map)": ({"lattice_map": False}, {}),
    "no sweep (cylindrical sections)": ({"sweep": False}, {}),
    "no Kuchemann unsweeping": ({"kuchemann": False}, {"kuchemann": False}),
    "no 3-D transonic relief": ({}, {"relief_3d": False}),
    "no choke spillage": ({}, {"choke_spill": False}),
    "no leading-edge suction limit": ({"le_suction": False}, {}),
    "free transition (Michel)": ({"xtr_upper": 1.0, "xtr_lower": 1.0}, {}),
}


def _point(job):
    """Run one list of operating points on one propeller; returns a list of row dicts."""
    from hsprop import OperatingPoint, PropellerSolver, SectionOptions, SolverSettings, cases
    from hsprop.gas import Atmosphere
    name, sec_kw, st_kw, points = job
    prop = cases.reference(name)
    sv = PropellerSolver(prop, section=SectionOptions(**sec_kw), settings=SolverSettings(**st_kw))
    rows = []
    prev = None
    for pt in points:
        M = pt["mach"]
        if pt.get("env") == "sea_level":
            op = OperatingPoint(mach=M, altitude=0.0, J=pt["J"])
        else:
            op = OperatingPoint(mach=M, atmosphere=Atmosphere.from_total(288.15, 101325.0, M), J=pt["J"])
        t0 = time.time()
        r = sv.solve_for(op, CP=pt["CP"], dbeta0=prev)
        prev = r.dbeta
        rows.append(dict(pt, eta=r.eta, eta_blade=r.op["eta_blade"], CT=r.CT, CP_out=r.CP, beta75=r.beta_ref,
                         converged=r.converged, seconds=time.time() - t0, losses=r.losses,
                         warnings=r.warnings))
    return rows


def jobs():
    J = []
    design = [dict(mach=0.8, J=3.06, CP=1.70)]
    takeoff = [dict(mach=0.2, J=0.875, CP=1.0, env="sea_level")]
    J.append(("sr3_design", ("sr3_class", {}, {}, design)))
    J.append(("sr2_design", ("sr2_class", {}, {}, design)))
    trend = [dict(mach=M, J=3.06 * M / 0.8, CP=1.7 * (M / 0.8) ** 3) for M in (0.8, 0.85, 0.75, 0.7, 0.65, 0.6)]
    J.append(("sr3_mach_trend", ("sr3_class", {}, {}, trend)))
    J.append(("sr2_mach_trend", ("sr2_class", {}, {}, trend)))
    sweep = [dict(mach=0.8, J=3.06, CP=cp) for cp in (1.7, 1.45, 1.2, 1.0, 0.8, 0.6, 2.0, 2.3, 2.6)]
    J.append(("sr3_power_m08", ("sr3_class", {}, {}, sweep)))
    J.append(("sr2_power_m08", ("sr2_class", {}, {}, sweep[:7])))
    J.append(("sr3_takeoff", ("sr3_class", {}, {}, takeoff)))
    J.append(("sr2_takeoff", ("sr2_class", {}, {}, takeoff)))
    hs = [dict(mach=0.8, J=3.06, CP=cp) for cp in (2.17, 1.8, 1.4, 1.0, 2.6, 3.0)]
    J.append(("hs12_power_m08", ("high_solidity_12", {}, {}, hs)))
    J.append(("hs12_takeoff", ("high_solidity_12", {}, {}, [dict(takeoff[0], CP=1.3)])))
    for label, (sec_kw, st_kw) in ABLATIONS.items():
        if label == "full model":
            continue
        J.append((f"ablation|design|{label}", ("sr3_class", sec_kw, st_kw, design)))
        J.append((f"ablation|takeoff|{label}", ("sr3_class", sec_kw, st_kw, takeoff)))
    return J


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("-j", "--jobs", type=int, default=4)
    ap.add_argument("-o", "--output", default=str(HERE.parent / "data" / "validation.json"))
    ap.add_argument("--only", help="run only jobs whose key contains this text")
    args = ap.parse_args(argv)
    todo = [j for j in jobs() if not args.only or args.only in j[0]]
    t0 = time.time()
    out = {"measured": MEASURED, "results": {}}
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        futs = {key: ex.submit(_point, job) for key, job in todo}
        for key, fut in futs.items():
            rows = fut.result()
            out["results"][key] = rows
            for r in rows:
                print(f"{key:55s} M {r['mach']:.2f} J {r['J']:.3f} CP {r['CP']:.3f}: eta {r['eta']:.4f} "
                      f"CT {r['CT']:.4f} beta75 {r['beta75']:6.2f} conv {r['converged']} ({r['seconds']:.0f} s)",
                      flush=True)
    out["seconds"] = time.time() - t0
    Path(args.output).write_text(json.dumps(out, indent=1, default=float))
    print(f"wrote {args.output} in {out['seconds']:.0f} s")


if __name__ == "__main__":
    main()
