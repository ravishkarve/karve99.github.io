"""Precompute the case library, Euler examples and verification report for the dashboard.

Usage:  python tools/precompute.py [panel|euler|verify|all]
Writes JSON files into ../data/.
"""
from __future__ import annotations

import json
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymises.config import build_case  # noqa: E402
from pymises.webapi import compact  # noqa: E402

DATA = ROOT / "data"

FAMILIES = [
    {
        "id": "compressor",
        "name": "C4 compressor cascade",
        "note": "C4 thickness (8 % t/c) on a circular-arc camber line, metal angles 45/15 deg, "
                "s/c = 0.9, 0.4 % trailing-edge thickness.",
        "geometry": {"type": "parametric", "inlet_metal_angle": 45.0, "exit_metal_angle": 15.0,
                     "max_thickness": 0.08, "thickness_form": "c4", "pitch": 0.9,
                     "te_thickness": 0.004},
        "grid": {"inlet_angle": [35.0, 37.0, 39.0, 41.0, 43.0, 45.0, 47.0, 49.0, 51.0],
                 "inlet_mach": [0.3, 0.5, 0.65], "reynolds": [2.5e5, 5.0e5, 1.0e6]},
    },
    {
        "id": "turbine",
        "name": "Turbine cascade",
        "note": "Front-loaded Bezier camber (LE fraction 0.72), metal angles 30/-60 deg, NACA 65 "
                "thickness 18 %, s/c = 0.85, 1 % trailing-edge thickness.",
        "geometry": {"type": "parametric", "camber": "bezier", "le_camber_fraction": 0.72,
                     "inlet_metal_angle": 30.0, "exit_metal_angle": -60.0, "max_thickness": 0.18,
                     "thickness_form": "naca65", "pitch": 0.85, "te_thickness": 0.01},
        "grid": {"inlet_angle": [18.0, 22.0, 26.0, 30.0, 34.0],
                 "inlet_mach": [0.15, 0.3], "reynolds": [2.5e5, 5.0e5, 1.0e6]},
    },
]

AIRFOIL_DAT = (ROOT / "examples" / "naca4412.dat").read_text()
FAMILIES.append({
    "id": "selig",
    "name": "NACA 4412 cascade (Selig file)",
    "note": "NACA 4412 from a 69-point Selig coordinate file (examples/naca4412.dat), stagger 30 deg, "
            "s/c = 0.83: the aerofoil-coordinates input path.",
    "geometry": {"type": "selig", "coordinates": AIRFOIL_DAT, "stagger": 30.0, "pitch": 0.83},
    "grid": {"inlet_angle": [30.0, 32.0, 34.0, 36.0, 38.0, 40.0, 42.0, 44.0, 46.0, 48.0, 50.0, 52.0, 54.0, 56.0],
             "inlet_mach": [0.3, 0.5], "reynolds": [2.5e5, 5.0e5, 1.0e6]},
})

EULER_CASES = [
    {"id": "euler_m05", "title": "Compressor, M1 = 0.50, viscous Euler",
     "geometry": FAMILIES[0]["geometry"], "flow": {"inlet_mach": 0.5, "inlet_angle": 43.0, "reynolds": 5e5},
     "viscous": {"enabled": True}},
    {"id": "euler_m065", "title": "Compressor, M1 = 0.65, viscous Euler",
     "geometry": FAMILIES[0]["geometry"], "flow": {"inlet_mach": 0.65, "inlet_angle": 45.0, "reynolds": 1e6},
     "viscous": {"enabled": True}},
    {"id": "euler_m072_inv", "title": "Compressor, M1 = 0.72, inviscid Euler (supersonic patch)",
     "geometry": FAMILIES[0]["geometry"], "flow": {"inlet_mach": 0.72, "inlet_angle": 47.0, "reynolds": 1e6},
     "viscous": {"enabled": False}, "euler": {"tol": 1e-4, "mass_tol": 5e-5, "max_steps": 20000}},
    {"id": "euler_turbine", "title": "Turbine, M1 = 0.30, viscous Euler (100 x 40 cells)",
     "geometry": FAMILIES[1]["geometry"], "flow": {"inlet_mach": 0.3, "inlet_angle": 30.0, "reynolds": 5e5},
     "viscous": {"enabled": True}, "euler": {"ni_blade": 100, "nj": 40}},
    {"id": "euler_airfoil", "title": "NACA 4412 (Selig file), M1 = 0.50, viscous Euler",
     "geometry": FAMILIES[2]["geometry"], "flow": {"inlet_mach": 0.5, "inlet_angle": 40.0, "reynolds": 5e5},
     "viscous": {"enabled": True}},
]


def key(beta, mach, re):
    # formatted like JavaScript's String(number) so the dashboard can rebuild keys
    return f"{beta:g}|{mach:g}|{re:.0f}"


def _run_panel(args):
    fam, beta, mach, re = args
    cfg = {"case": {"name": fam["name"], "method": "panel"}, "geometry": dict(fam["geometry"]),
           "flow": {"inlet_mach": mach, "inlet_angle": beta, "reynolds": re}}
    t0 = time.time()
    try:
        res = build_case(cfg).solver().solve()
        c = compact(res)
        for side in c["bl"] or {}:
            for k in ("ue", "re_theta"):
                c["bl"][side].pop(k, None)
        c.pop("blade")
        return fam["id"], key(beta, mach, re), c, time.time() - t0
    except Exception as exc:  # keep going; record the failure
        return fam["id"], key(beta, mach, re), {"error": repr(exc)}, time.time() - t0


def run_panel_library(processes=4):
    DATA.mkdir(exist_ok=True)
    jobs = [(f, b, m, r) for f in FAMILIES for b in f["grid"]["inlet_angle"]
            for m in f["grid"]["inlet_mach"] for r in f["grid"]["reynolds"]]
    out = {f["id"]: {k: v for k, v in f.items()} | {"cases": {}} for f in FAMILIES}
    t0 = time.time()
    with Pool(processes) as pool:
        for i, (fid, k, c, dt) in enumerate(pool.imap_unordered(_run_panel, jobs)):
            out[fid]["cases"][k] = c
            print(f"[{i + 1}/{len(jobs)}] {fid} {k} {dt:.1f}s "
                  f"{'ERR ' + c['error'] if 'error' in c else 'omega=%.4f' % c['perf']['omega']}",
                  flush=True)
    for f in FAMILIES:
        b = build_case({"geometry": f["geometry"]}).blade
        out[f["id"]]["blade"] = compact_blade(b)
    (DATA / "library.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"library done in {time.time() - t0:.0f}s")


def compact_blade(b):
    from pymises.webapi import _r
    d = b.to_dict()
    return {"x": _r(d["x"], 6), "y": _r(d["y"], 6), "pitch": d["pitch"], "chord": _r(d["chord"]),
            "stagger": _r(d["stagger_deg"]), "solidity": _r(d["solidity"]),
            "max_thickness": _r(d["max_thickness"]), "inlet_metal_angle": _r(d["inlet_metal_angle"]),
            "exit_metal_angle": _r(d["exit_metal_angle"])}


def _run_euler(case):
    cfg = {"case": {"name": case["title"], "method": "euler"}, "geometry": dict(case["geometry"]),
           "flow": dict(case["flow"]), "viscous": dict(case["viscous"]),
           "euler": dict(case.get("euler", {}))}
    t0 = time.time()
    try:
        res = build_case(cfg).solver().solve()
        c = compact(res)
        c["id"] = case["id"]
        c["family"] = next((f["id"] for f in FAMILIES if f["geometry"] == case["geometry"]), None)
        c["title"] = case["title"]
        c["seconds"] = time.time() - t0
        print(f"euler {case['id']} done in {c['seconds']:.0f}s omega={c['perf']['omega']:.4f}",
              flush=True)
        return c
    except Exception as exc:
        print(f"euler {case['id']} failed: {exc!r}", flush=True)
        return {"id": case["id"], "title": case["title"], "error": repr(exc)}


def run_euler_cases(processes=4):
    DATA.mkdir(exist_ok=True)
    with Pool(min(processes, len(EULER_CASES))) as pool:
        res = pool.map(_run_euler, EULER_CASES)
    (DATA / "euler.json").write_text(json.dumps(res, separators=(",", ":")))


def run_verification():
    from pymises.verification import run_all, write_report
    res = run_all(progress=lambda c: print(f"  {'PASS' if c.passed else 'FAIL'} {c.name} "
                                           f"{c.value:.3e} ({c.seconds:.1f}s)", flush=True))
    write_report(res, DATA)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("panel", "all"):
        run_panel_library()
    if what in ("euler", "all"):
        run_euler_cases()
    if what in ("verify", "all"):
        run_verification()
