"""Command line: ``bbn run case.toml -o out``, ``bbn template KIND [FILE]``, ``bbn serve``."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

__all__ = ["main"]


def _cmd_run(args):
    from .config import load, run
    from .inputs import SolverError
    from .output import write
    case = load(args.case)
    prog = None if args.quiet else (lambda m: print(f"  .. {m}", flush=True))
    t0 = time.time()
    try:
        res = run(case, progress=prog)
    except SolverError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"{Path(args.case).name}: {len(res.curves)} spectra in {time.time() - t0:.1f} s")
    print(res.summary())
    out = Path(args.output or Path(args.case).with_suffix("").name + "_out")
    for p in write(res, out):
        print(f"  wrote {p}")
    return 0


def _cmd_template(args):
    from .examples import template
    text = template(args.kind)
    if args.file:
        Path(args.file).write_text(text)
        print(f"wrote {args.file}")
    else:
        sys.stdout.write(text)
    return 0


def _cmd_serve(args):
    from .server import serve
    serve(args.port, args.host)
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="bbn", description="Rotor broadband noise after Blandeau's thesis")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("run", help="run a case (TOML or JSON with rotor / noise_model / spectra sections)")
    s.add_argument("case")
    s.add_argument("-o", "--output", help="output folder (default <case>_out)")
    s.add_argument("-q", "--quiet", action="store_true")
    s.set_defaults(fn=_cmd_run)
    s = sub.add_parser("template", help="write a template: case, blade, bl, wake or ingestion")
    s.add_argument("kind", choices=["case", "blade", "bl", "wake", "ingestion"])
    s.add_argument("file", nargs="?")
    s.set_defaults(fn=_cmd_template)
    s = sub.add_parser("serve", help="serve the dashboard locally")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--host", default="127.0.0.1")
    s.set_defaults(fn=_cmd_serve)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
