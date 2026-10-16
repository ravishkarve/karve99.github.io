"""Command-line interface:  ``hsprop <command> ...``  (or ``python -m hsprop``).

Commands
--------
run CONFIG        run the operating points / sweep of a TOML or JSON file, print and save
point             one operating point of a built-in or saved propeller from the command line
design            inverse-design camber and twist of a propeller file for a design point
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _print(res):
    print(res.summary())
    print()


def _cmd_run(args):
    from .config import run_config
    t0 = time.time()
    prop, results = run_config(args.config, progress=None if args.quiet else _print)
    out = Path(args.output) if args.output else Path(args.config).with_suffix(".results.json")
    out.write_text(json.dumps({"propeller": prop.to_dict(), "results": [r.to_dict() for r in results]},
                              indent=1))
    print(f"{len(results)} point(s) in {time.time() - t0:.1f} s; wrote {out}")
    return 0


def _cmd_point(args):
    from .config import build_propeller, run_point
    from .solver import PropellerSolver
    cfg = {"propeller": {"file": args.propeller}} if args.propeller.endswith(".json") else \
        {"propeller": {"builtin": args.propeller}}
    prop = build_propeller(cfg)
    pt = {"mach": args.mach, "altitude": args.altitude}
    for k in ("rpm", "tip_speed", "J", "CP", "CT", "beta75"):
        v = getattr(args, k)
        if v is not None:
            pt[k] = v
    res = run_point(PropellerSolver(prop), pt)
    _print(res)
    if args.radial:
        rd = res.radial
        keys = ["r_R", "alpha_deg", "mach", "mach_n", "sweep_deg", "sigma", "k_lattice", "cl", "cd",
                "cd_wave", "choke_ratio", "f_attached"]
        print("  ".join(f"{k:>10s}" for k in keys))
        for i in range(len(rd["r_R"])):
            print("  ".join(f"{float(rd[k][i]):10.4f}" for k in keys))
    return 0


def _cmd_design(args):
    from .design import design
    from .geometry import Propeller
    from .solver import OperatingPoint
    prop = Propeller.load(args.propeller)
    op = OperatingPoint(mach=args.mach, altitude=args.altitude, tip_speed=args.tip_speed, rpm=args.rpm, J=args.J)
    prop, res = design(prop, op, args.CP, verbose=True, tip_relief=args.tip_relief)
    prop.save(args.output)
    _print(res)
    print(f"wrote {args.output}  (activity factor {prop.blade.activity_factor():.1f}, "
          f"integrated design CL {prop.blade.integrated_design_cl():.3f})")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hsprop", description="High-solidity propeller performance")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="run a configuration file")
    p.add_argument("config")
    p.add_argument("-o", "--output", help="results JSON (default: CONFIG.results.json)")
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(func=_cmd_run)

    p = sub.add_parser("point", help="one operating point")
    p.add_argument("propeller", help="built-in name (sr3_class, sr2_class, high_solidity_12) or a .json file")
    p.add_argument("--mach", type=float, required=True)
    p.add_argument("--altitude", type=float, default=0.0)
    p.add_argument("--rpm", type=float)
    p.add_argument("--tip-speed", dest="tip_speed", type=float)
    p.add_argument("--J", type=float)
    p.add_argument("--CP", type=float)
    p.add_argument("--CT", type=float)
    p.add_argument("--beta75", type=float)
    p.add_argument("--radial", action="store_true", help="print radial distributions")
    p.set_defaults(func=_cmd_point)

    p = sub.add_parser("design", help="inverse design (Betz loading at ideal incidence)")
    p.add_argument("propeller", help="propeller .json with planform, thickness and sweep")
    p.add_argument("--mach", type=float, required=True)
    p.add_argument("--altitude", type=float, default=0.0)
    p.add_argument("--rpm", type=float)
    p.add_argument("--tip-speed", dest="tip_speed", type=float)
    p.add_argument("--J", type=float)
    p.add_argument("--CP", type=float, required=True)
    p.add_argument("--tip-relief", dest="tip_relief", type=float, default=0.45)
    p.add_argument("-o", "--output", default="designed.json")
    p.set_defaults(func=_cmd_design)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
