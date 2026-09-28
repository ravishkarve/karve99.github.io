"""Command-line interface:  ``pymises <command> ...``  (or ``python -m pymises``).

Commands
--------
run CONFIG        run a case (or a sweep) from a TOML/JSON/YAML file and save results
verify            run the verification suite and write a report
blade CONFIG      export the configured blade in MISES blade.xxx format
example NAME DIR  write an example configuration (compressor, turbine, sweep, euler, mises)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _cmd_run(args):
    from .config import run_config
    t0 = time.time()
    prog = None if args.quiet else (lambda msg: print(f"  .. {msg}", flush=True))
    case, results, files = run_config(args.config, output_dir=args.output,
                                      plots=False if args.no_plots else None,
                                      progress=prog, verbose=args.verbose)
    if not args.quiet:
        for res in results:
            print(res.summary())
            print()
        print(f"{len(results)} solution(s) in {time.time() - t0:.1f} s; files written:")
        for f in files:
            print(f"  {f}")
    return 0 if all(not r.warnings for r in results) or args.allow_warnings else 0


def _cmd_verify(args):
    from .verification import run_all, write_report
    t0 = time.time()
    results = run_all(quick=args.quick, progress=None if args.quiet else
                      (lambda c: print(f"  {'PASS' if c.passed else 'FAIL'}  {c.name:28s} "
                                       f"{c.metric} = {c.value:.3e}  (tol {c.tolerance:.1e})  "
                                       f"[{c.seconds:.1f} s]", flush=True)))
    n_pass = sum(r.passed for r in results)
    print(f"{n_pass}/{len(results)} verification cases passed in {time.time() - t0:.1f} s")
    if args.output:
        files = write_report(results, args.output)
        for f in files:
            print(f"  wrote {f}")
    return 0 if n_pass == len(results) else 1


def _cmd_blade(args):
    from .config import build_case, load_config
    case = build_case(load_config(args.config))
    out = args.write or f"blade.{Path(args.config).stem}"
    case.blade.write_mises(out, inlet_angle=case.flow.inlet_angle)
    print(f"wrote {out}")
    print(json.dumps({k: v for k, v in case.blade.to_dict().items() if k not in ("x", "y")},
                     indent=1))
    return 0


def _cmd_example(args):
    from .examples import write_example, EXAMPLES
    if args.name not in EXAMPLES:
        print(f"unknown example '{args.name}'; choose from {sorted(EXAMPLES)}")
        return 2
    files = write_example(args.name, args.directory)
    for f in files:
        print(f"wrote {f}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pymises", description="Pythonic MISES-style cascade solver")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="run a configuration file")
    p.add_argument("config")
    p.add_argument("-o", "--output", help="output directory (default: from [case] output_dir)")
    p.add_argument("--no-plots", action="store_true")
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--allow-warnings", action="store_true")
    p.set_defaults(func=_cmd_run)

    p = sub.add_parser("verify", help="run the verification suite")
    p.add_argument("--quick", action="store_true", help="skip the slow Euler cases")
    p.add_argument("-o", "--output", help="directory for verification.json / verification.md")
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(func=_cmd_verify)

    p = sub.add_parser("blade", help="export the blade in MISES blade.xxx format")
    p.add_argument("config")
    p.add_argument("-w", "--write", help="output file name")
    p.set_defaults(func=_cmd_blade)

    p = sub.add_parser("example", help="write an example configuration")
    p.add_argument("name")
    p.add_argument("directory", nargs="?", default=".")
    p.set_defaults(func=_cmd_example)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
