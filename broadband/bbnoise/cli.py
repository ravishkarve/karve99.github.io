"""Command-line interface:  ``bbnoise <command> ...``  (or ``python -m bbnoise``).

Commands
--------
list                         list the literature test cases
case KEY [-o DIR]            run a literature case
run FILE [-o DIR]            run a case file (.toml or .json)
example KEY FILE             write a literature case to FILE (JSON) as a template
wps --Ue .. --delta-star ..  evaluate the wall-pressure models for a boundary layer
template blade|bl FILE       write an example blade or boundary-layer table (CSV)
verify [-o DIR]              run the verification suite
serve [--port 8000]          start the local web dashboard

Common options for case/run: --formulation full|simplified|eq3.18|eq5.7 (repeatable;
the thesis eqs. 3.18 / 5.7 compute trailing-edge self noise only),
--set path.to.key=value (override any case entry, value parsed as JSON),
--no-plots, --quiet.
"""
from __future__ import annotations

import argparse
import json
import sys
import time


def _apply_overrides(case, sets, formulations):
    for s in sets or []:
        key, _, val = s.partition("=")
        try:
            v = json.loads(val)
        except json.JSONDecodeError:
            v = val
        d = case
        parts = key.split(".")
        for p in parts[:-1]:
            if isinstance(d, list):
                d = d[int(p)]
            else:
                d = d.setdefault(p, {})
        if isinstance(d, list):
            d[int(parts[-1])] = v
        else:
            d[parts[-1]] = v
    if formulations:
        case["formulations"] = formulations
    return case


def _run(case, args):
    from .io import write_results
    from .model import run_case
    prog = None if args.quiet else (lambda m: print(f"  .. {m}", flush=True))
    res = run_case(case, progress=prog)
    print(res.summary())
    if args.output:
        for f in write_results(res, args.output, plots=not args.no_plots):
            print(f"  wrote {f}")
    return 0


def _cmd_list(args):
    from .cases import CASES
    for k, c in CASES.items():
        print(f"{k:28s} {c['name']}")
        if args.verbose:
            print(f"{'':28s} {c.get('description', '')}")
            print(f"{'':28s} ref: {c.get('reference', '')}\n")
    return 0


def _cmd_case(args):
    from .cases import get_case
    case = _apply_overrides(get_case(args.key), args.set, args.formulation)
    return _run(case, args)


def _cmd_run(args):
    from .io import load_case
    case = _apply_overrides(load_case(args.file), args.set, args.formulation)
    return _run(case, args)


def _cmd_example(args):
    from .cases import get_case
    from .io import save_case
    print("wrote", save_case(get_case(args.key), args.file))
    return 0


def _cmd_template(args):
    from pathlib import Path
    from .tables import BL_TEMPLATE, BLADE_TEMPLATE
    Path(args.file).write_text(BLADE_TEMPLATE if args.kind == "blade" else BL_TEMPLATE)
    print("wrote", args.file)
    return 0


def _cmd_wps(args):
    import numpy as np
    from .wallpressure import WPS_MODELS, BoundaryLayer, wps_normalised
    bl = BoundaryLayer(Ue=args.Ue, delta_star=args.delta_star, delta=args.delta, theta=args.theta, H=args.H,
                       cf=args.cf, beta_c=args.beta_c, dpdx=args.dpdx, nu=args.nu, rho=args.rho,
                       c0=args.c0).complete()
    print("boundary layer:", ", ".join(f"{k}={v:.4g}" for k, v in bl.as_dict().items()
                                        if isinstance(v, (float, int)) and v is not None))
    for n in bl.notes:
        print("  note:", n)
    models = args.models or list(WPS_MODELS)
    wt = np.geomspace(0.05, 50, 13)
    print("\n10 log10(Phi Ue / (tau_w^2 delta*)) versus omega delta*/Ue")
    print(f"{'omega~':>9s} " + " ".join(f"{m[:11]:>11s}" for m in models))
    vals = {m: 10 * np.log10(np.maximum(wps_normalised(m, wt, bl), 1e-30)) for m in models}
    for i, w in enumerate(wt):
        print(f"{w:9.3g} " + " ".join(f"{vals[m][i]:11.2f}" for m in models))
    return 0


def _cmd_verify(args):
    from .verification import run_all, write_report
    t0 = time.time()
    res = run_all(progress=None if args.quiet else
                  (lambda c: print(f"  {'PASS' if c.passed else 'FAIL'}  {c.name:28s} {c.metric}: "
                                   f"{c.value:.3g} (tol {c.tolerance:.3g})  [{c.seconds:.1f} s]", flush=True)))
    n = sum(r.passed for r in res)
    print(f"{n}/{len(res)} checks passed in {time.time() - t0:.1f} s")
    if args.output:
        for f in write_report(res, args.output):
            print(f"  wrote {f}")
    return 0 if n == len(res) else 1


def _cmd_serve(args):
    from .server import serve
    serve(args.port, args.host)
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="bbnoise", description="Broadband rotor noise after Blandeau (2011): "
                                "rotor-wake interaction and trailing-edge self noise, full and simplified "
                                "(Amiet) formulations, wall-pressure models including the VKI GEP model.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def run_opts(sp):
        sp.add_argument("-o", "--output", help="output directory (CSV, JSON, PNG)")
        sp.add_argument("--formulation", action="append", choices=["full", "simplified", "eq3.18", "eq5.7"])
        sp.add_argument("--set", action="append", metavar="PATH=VALUE", help="override a case entry")
        sp.add_argument("--no-plots", action="store_true")
        sp.add_argument("-q", "--quiet", action="store_true")

    s = sub.add_parser("list", help="list literature cases")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(fn=_cmd_list)
    s = sub.add_parser("case", help="run a literature case")
    s.add_argument("key")
    run_opts(s)
    s.set_defaults(fn=_cmd_case)
    s = sub.add_parser("run", help="run a case file")
    s.add_argument("file")
    run_opts(s)
    s.set_defaults(fn=_cmd_run)
    s = sub.add_parser("example", help="write a case template")
    s.add_argument("key")
    s.add_argument("file")
    s.set_defaults(fn=_cmd_example)
    s = sub.add_parser("template", help="write an example blade or boundary-layer table")
    s.add_argument("kind", choices=["blade", "bl"])
    s.add_argument("file")
    s.set_defaults(fn=_cmd_template)
    s = sub.add_parser("wps", help="evaluate wall-pressure models")
    s.add_argument("--Ue", type=float, required=True)
    s.add_argument("--delta-star", type=float, required=True)
    for k in ("delta", "theta", "H", "cf", "beta-c", "dpdx"):
        s.add_argument(f"--{k}", type=float, dest=k.replace("-", "_"))
    s.add_argument("--nu", type=float, default=1.5e-5)
    s.add_argument("--rho", type=float, default=1.225)
    s.add_argument("--c0", type=float, default=340.0)
    s.add_argument("--models", nargs="+")
    s.set_defaults(fn=_cmd_wps)
    s = sub.add_parser("verify", help="run the verification suite")
    s.add_argument("-o", "--output")
    s.add_argument("-q", "--quiet", action="store_true")
    s.set_defaults(fn=_cmd_verify)
    s = sub.add_parser("serve", help="start the local web dashboard")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--host", default="127.0.0.1")
    s.set_defaults(fn=_cmd_serve)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
