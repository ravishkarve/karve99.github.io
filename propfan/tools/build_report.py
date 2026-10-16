"""Build the technical report (report.html) from stored solver output.

    python tools/build_report.py [--refresh] [--artifact OUT.html]

Reads data/validation.json (tools/validate.py) and data/report_extra.json (radial
distributions and section studies; recomputed with --refresh or when missing) and writes
report.html with static SVG figures.  --artifact also writes the page body without the
document wrapper (for publishing as a hosted page).
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import math
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
REPO = "https://github.com/ravishkarve/karve99.github.io"


# ---------------------------------------------------------------------------------- data
def compute_extra():
    import numpy as np
    from hsprop import OperatingPoint, PropellerSolver, SectionOptions, cases
    from hsprop.gas import Atmosphere
    from hsprop.section import NormalPlane, SectionModel

    def tunnel(M, J):
        return OperatingPoint(mach=M, atmosphere=Atmosphere.from_total(288.15, 101325.0, M), J=J)

    keep = ["r_R", "mach", "mach_n", "sweep_deg", "cl", "cl_n", "cd", "cd_profile", "cd_wave", "cd_sep",
            "cd_choke", "choke_ratio", "f_attached", "le_singularity", "u_spill", "alpha_deg", "gamma",
            "dT_dr", "sigma"]
    out = {}
    sv = PropellerSolver(cases.reference("sr3_class"))
    for key, op, cp in [("design", tunnel(0.8, 3.06), 1.7), ("low_power", tunnel(0.8, 3.06), 0.6),
                        ("takeoff", OperatingPoint(mach=0.2, altitude=0.0, J=0.875), 1.0)]:
        r = sv.solve_for(op, CP=cp)
        rad = {k: np.asarray(r.radial[k]).tolist() for k in keep}
        rad["mach_n_eff"] = []
        rad["V"] = r.op["V"]
        out[key] = dict(eta=r.eta, CT=r.CT, CP=r.CP, beta75=r.beta_ref, losses=r.losses, radial=rad)
        # effective (relieved) normal Mach number at the solution
        geo = sv._geometry(r.dbeta)
        npl = sv._normal_plane(geo, np.radians(r.radial["phi_deg"]))
        kap = sv._relief_wavenumber(geo, npl)
        mn = np.asarray(r.radial["mach_n"])
        out[key]["radial"]["mach_n_eff"] = np.sqrt(np.maximum(mn ** 2 - kap ** 2, 0.0)).tolist()
        out[key]["radial"]["kappa"] = kap.tolist()
    # section studies: thin vs thick at low speed; free transition through bubble onset
    al = np.linspace(0.0, 18.0, 73)
    sec = {"alpha": al.tolist()}
    for tau in (0.04, 0.12):
        sm = SectionModel(["naca16"] * al.size, ["a1"] * al.size, SectionOptions())
        a = np.radians(al)
        one = np.ones_like(a)
        rr = sm.evaluate(NormalPlane.plain(a, 0 * one, 0 * one, tau * one, 0 * one), 0.25 * one, 3e6 * one)
        sec[f"cl_{tau}"] = rr.cl.tolist()
        sec[f"cd_{tau}"] = rr.cd.tolist()
        sec[f"f_{tau}"] = rr.f_attached.tolist()
    out["sections"] = sec
    al = np.linspace(-3.0, 3.0, 121)
    a = np.radians(al)
    one = np.ones_like(a)
    sm = SectionModel(["naca16"] * al.size, ["a1"] * al.size, SectionOptions(xtr_upper=1.0, xtr_lower=1.0))
    rr = sm.evaluate(NormalPlane.plain(a, 0 * one, 0 * one, 0.04 * one, 0.3 * one), 0.6 * one, 2e6 * one)
    out["transition"] = dict(alpha=al.tolist(), xtr_upper=rr.x_tr[:, 0].tolist(), xtr_lower=rr.x_tr[:, 1].tolist(),
                             cd_profile=rr.cd_profile.tolist())
    return out


# ---------------------------------------------------------------------------------- svg
_uid = [0]


def _nice(lo, hi, n=5):
    span = hi - lo
    step = 10 ** math.floor(math.log10(span / n))
    for m in (1, 2, 2.5, 5, 10):
        if span / (m * step) <= n:
            step *= m
            break
    first = math.ceil(lo / step - 1e-9) * step
    ticks = []
    t = first
    while t <= hi + 1e-9 * step:
        ticks.append(round(t, 10))
        t += step
    return ticks


def _fmt(v):
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:g}"


def chart(series, xlab, ylab, xr, yr, xticks=None, yticks=None, w=680, h=300, label="", refs=(), notes=()):
    """Line/marker chart.  series: dicts(x, y, cls ('s1'|'s2'|'s3'|'ink'), kind ('line'|'marker'|
    'hollow'|'line+marker'), name, tip (list of str), lab (direct label at the last point))."""
    _uid[0] += 1
    L, R, T, B = 52, 18, 10, 46
    pw, ph = w - L - R, h - T - B
    x0, x1 = xr
    y0, y1 = yr

    def X(v):
        return L + (v - x0) / (x1 - x0) * pw

    def Y(v):
        return T + (1 - (v - y0) / (y1 - y0)) * ph

    xt = xticks or _nice(x0, x1)
    yt = yticks or _nice(y0, y1)
    cid = f"clip{_uid[0]}"
    o = [f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(label)}">',
         f'<defs><clipPath id="{cid}"><rect x="{L}" y="{T - 4}" width="{pw + 4}" height="{ph + 8}"/></clipPath></defs>']
    for v in yt:
        o.append(f'<line class="grid" x1="{L}" x2="{L + pw}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>')
        o.append(f'<text class="tick" x="{L - 7}" y="{Y(v) + 4:.1f}" text-anchor="end">{_fmt(v)}</text>')
    for v in xt:
        o.append(f'<text class="tick" x="{X(v):.1f}" y="{T + ph + 17}" text-anchor="middle">{_fmt(v)}</text>')
    o.append(f'<line class="axis" x1="{L}" x2="{L + pw}" y1="{T + ph}" y2="{T + ph}"/>')
    o.append(f'<text class="axlab" x="{L + pw / 2:.1f}" y="{h - 6}" text-anchor="middle">{xlab}</text>')
    o.append(f'<text class="axlab" x="13" y="{T + ph / 2:.1f}" text-anchor="middle" '
             f'transform="rotate(-90 13 {T + ph / 2:.1f})">{ylab}</text>')
    o.append(f'<g clip-path="url(#{cid})">')
    for ref in refs:                                   # (kind, value, text)
        kind, v, txt = ref
        if kind == "h":
            o.append(f'<line class="ln ref" x1="{L}" x2="{L + pw}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>')
        elif kind == "v":
            o.append(f'<line class="ln ref" x1="{X(v):.1f}" x2="{X(v):.1f}" y1="{T}" y2="{T + ph}"/>')
        elif kind == "diag":
            o.append(f'<line class="ln ref" x1="{X(x0):.1f}" y1="{Y(x0):.1f}" x2="{X(x1):.1f}" y2="{Y(x1):.1f}"/>')
        elif kind == "band":
            lo, hi = v
            pts = f"{X(x0):.1f},{Y(x0 + hi):.1f} {X(x1):.1f},{Y(x1 + hi):.1f} {X(x1):.1f},{Y(x1 + lo):.1f} {X(x0):.1f},{Y(x0 + lo):.1f}"
            o.append(f'<polygon class="band" points="{pts}"/>')
    for s in series:
        xs, ys = s["x"], s["y"]
        if "line" in s.get("kind", "line"):
            d = " ".join(f"{'M' if i == 0 else 'L'}{X(a):.1f} {Y(b):.1f}" for i, (a, b) in enumerate(zip(xs, ys))
                         if b is not None)
            dash = ' stroke-dasharray="6 4"' if s.get("dash") else ""
            o.append(f'<path class="ln {s["cls"]}" d="{d}" stroke-width="{s.get("sw", 2)}"{dash}/>')
    o.append("</g>")
    for s in series:
        kind = s.get("kind", "line")
        tips = s.get("tip")
        for i, (a, b) in enumerate(zip(s["x"], s["y"])):
            if b is None:
                continue
            if "marker" in kind or kind == "hollow":
                r = s.get("r", 4.5)
                cls = f'mk {s["cls"]}' + (" hollow" if kind == "hollow" else "")
                o.append(f'<circle class="{cls}" cx="{X(a):.1f}" cy="{Y(b):.1f}" r="{r}"/>')
            if tips:
                o.append(f'<circle class="hit" cx="{X(a):.1f}" cy="{Y(b):.1f}" r="10"><title>{html.escape(tips[i])}</title></circle>')
        if s.get("lab"):
            lx, ly, anchor = s["lab"]
            o.append(f'<text class="dl {s["cls"]}" x="{X(lx):.1f}" y="{Y(ly):.1f}" text-anchor="{anchor}">'
                     f'{html.escape(s["name"])}</text>')
    for (a, b, txt, anchor) in notes:
        o.append(f'<text class="note" x="{X(a):.1f}" y="{Y(b):.1f}" text-anchor="{anchor}">{html.escape(txt)}</text>')
    o.append("</svg>")
    return "".join(o)


def barh(cats, groups, xlab, xr, w=680, label="", unit=""):
    """Grouped horizontal bars: cats (labels), groups: list of dict(name, cls, values)."""
    _uid[0] += 1
    L, R, T, B = 230, 30, 8, 40
    n_g = len(groups)
    bh, gap = 9, 2
    row = n_g * (bh + gap) + 10
    h = T + B + row * len(cats)
    pw = w - L - R
    x0, x1 = xr

    def X(v):
        return L + (v - x0) / (x1 - x0) * pw

    o = [f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(label)}">']
    for v in _nice(x0, x1, 6):
        o.append(f'<line class="grid" x1="{X(v):.1f}" x2="{X(v):.1f}" y1="{T}" y2="{T + row * len(cats)}"/>')
        o.append(f'<text class="tick" x="{X(v):.1f}" y="{T + row * len(cats) + 16}" text-anchor="middle">{_fmt(v)}</text>')
    o.append(f'<line class="axis" x1="{X(0):.1f}" x2="{X(0):.1f}" y1="{T}" y2="{T + row * len(cats)}"/>')
    for i, c in enumerate(cats):
        yc = T + i * row + 5
        o.append(f'<text class="cat" x="{L - 10}" y="{yc + n_g * (bh + gap) / 2 + 3:.1f}" text-anchor="end">{html.escape(c)}</text>')
        for j, g in enumerate(groups):
            v = g["values"][i]
            y = yc + j * (bh + gap)
            xa, xb = sorted([X(0), X(v)])
            tip = html.escape(f"{c}, {g['name']}: {v:+.2f}{unit}")
            o.append(f'<rect class="bar {g["cls"]}" x="{xa:.1f}" y="{y:.1f}" width="{max(xb - xa, 0.8):.1f}" '
                     f'height="{bh}" rx="2"><title>{tip}</title></rect>')
            tx = X(v) + (5 if v >= 0 else -5)
            txt = f"{v:+.1f}" if abs(v) >= 0.05 else "0.0"
            o.append(f'<text class="bval" x="{tx:.1f}" y="{y + bh - 1:.1f}" text-anchor="{"start" if v >= 0 else "end"}">{txt}</text>')
    o.append(f'<text class="axlab" x="{L + pw / 2:.1f}" y="{h - 6}" text-anchor="middle">{xlab}</text>')
    o.append("</svg>")
    return "".join(o)


def legend(items):
    return '<div class="legend">' + "".join(
        f'<span><i class="sw {c}{" dot" if d else ""}"></i>{html.escape(n)}</span>' for n, c, d in items) + "</div>"


# ---------------------------------------------------------------------------------- code links
def code_links(commit):
    files = {
        "cascade.py": [("map_lattice", r"def map_lattice"), ("ThinCascade", r"class ThinCascade"),
                       ("solve_tabulated", r"def solve_tabulated")],
        "section.py": [("evaluate", r"def evaluate"), ("relief", r"kx = kappa"), ("cp_lim", r"cp_lim = np.maximum"),
                       ("shock", r"sloss_u = "), ("thin", r"f_thin = 1.0"), ("vortex", r"dcn_v = "),
                       ("choke", r"chi = mass_flux_function"), ("throat", r"def _throat")],
        "solver.py": [("relief_k", r"def _relief_wavenumber"), ("newton", r"def _newton"), ("assemble", r"def _assemble"),
                      ("body", r"T_body = "), ("solve_for", r"def solve_for"), ("estimate", r"def _pitch_estimate"),
                      ("influence", r"def _influence")],
        "boundary_layer.py": [("march", r"def march"), ("transition", r"lam_prob = ")],
        "design.py": [("betz", r"def betz_circulation"), ("design", r"def design"), ("ideal", r"def _ideal_section")],
        "wake.py": [("vortex", r"class VortexSystem")],
        "nacelle.py": [("nacelle", r"class NacelleFlow")],
    }
    out = {}
    for fn, pats in files.items():
        lines = (ROOT / "hsprop" / fn).read_text().splitlines()
        for key, pat in pats:
            n = next((i + 1 for i, ln in enumerate(lines) if re.search(pat, ln)), 1)
            url = f"{REPO}/blob/{commit}/propfan/hsprop/{fn}#L{n}"
            out[f"{fn}:{key}"] = f'<a class="loc" href="{url}">{fn}:{n}</a>'
    return out


# ---------------------------------------------------------------------------------- page
CSS = r"""
:root {
  --bg: #f3f5f7; --paper: #ffffff; --ink: #16202b; --ink-2: #3a4655; --muted: #5e6a79;
  --rule: #d5dbe3; --soft: #edf1f5; --accent: #1b5ea8; --accent-soft: #e5edf8;
  --grid: #e6eaef; --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a;
  --warn: #9a4a06; --warn-bg: #fdf3e7; --warn-rule: #f0c79a;
  --serif: "Source Serif 4", "Source Serif Pro", Georgia, "Times New Roman", serif;
  --sans: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
  --cond: "IBM Plex Sans Condensed", "Arial Narrow", "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0e1218; --paper: #141a22; --ink: #e6ebf1; --ink-2: #c2cbd6; --muted: #8e99a8;
    --rule: #2a333f; --soft: #1b222c; --accent: #7fb2ee; --accent-soft: #1b2a3c;
    --grid: #232b36; --s1: #3987e5; --s2: #d95926; --s3: #199e70;
    --warn: #f3a765; --warn-bg: #2a1e12; --warn-rule: #5c3a18;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #0e1218; --paper: #141a22; --ink: #e6ebf1; --ink-2: #c2cbd6; --muted: #8e99a8;
  --rule: #2a333f; --soft: #1b222c; --accent: #7fb2ee; --accent-soft: #1b2a3c;
  --grid: #232b36; --s1: #3987e5; --s2: #d95926; --s3: #199e70;
  --warn: #f3a765; --warn-bg: #2a1e12; --warn-rule: #5c3a18;
  color-scheme: dark;
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; scroll-behavior: smooth; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 17px/1.62 var(--serif); }
.page { max-width: 1180px; margin: 0 auto; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); padding-block: 28px 64px; }
.masthead { background: var(--paper); border: 1px solid var(--rule); padding: 28px clamp(18px, 4vw, 48px) 26px; }
.journal { font: 600 12px/1.4 var(--cond); letter-spacing: .09em; text-transform: uppercase; color: var(--accent); display: flex; flex-wrap: wrap; gap: 6px 18px; }
.journal span + span { color: var(--muted); }
h1 { font: 700 clamp(26px, 3.6vw, 38px)/1.15 var(--cond); margin: 14px 0 12px; max-width: 42ch; text-wrap: balance; }
.byline { font: 15px/1.5 var(--sans); color: var(--ink-2); margin: 0; }
.meta { display: flex; flex-wrap: wrap; gap: 4px 22px; margin: 14px 0 0; font: 13px/1.5 var(--sans); color: var(--muted); }
.meta b { color: var(--ink-2); font-weight: 500; }
.layout { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0; margin-top: 18px; }
@media (min-width: 1100px) { .layout { grid-template-columns: 220px minmax(0, 1fr); gap: 28px; } }
nav.toc { font: 13.5px/1.45 var(--sans); background: var(--paper); border: 1px solid var(--rule); padding: 16px 18px; margin-bottom: 18px; align-self: start; }
@media (min-width: 1100px) { nav.toc { position: sticky; top: calc(env(safe-area-inset-top, 0px) + 16px); max-height: calc(100vh - 32px); overflow-y: auto; margin-bottom: 0; } }
nav.toc p { font: 600 11.5px var(--cond); letter-spacing: .09em; text-transform: uppercase; color: var(--muted); margin: 0 0 8px; }
nav.toc ol { list-style: none; margin: 0; padding: 0; display: grid; gap: 3px; }
nav.toc a { color: var(--ink-2); text-decoration: none; display: grid; grid-template-columns: 2.1em 1fr; }
nav.toc a:hover { color: var(--accent); }
nav.toc a span:first-child { color: var(--muted); font-variant-numeric: tabular-nums; }
article { background: var(--paper); border: 1px solid var(--rule); padding: clamp(20px, 4vw, 52px); min-width: 0; }
article > * { max-width: 72ch; }
article > figure, article > .scroll, article > .eqblock, article > .abstract, article > .callout, article > .pair { max-width: none; }
.abstract { background: var(--soft); padding: 20px 24px; margin: 0 0 28px; font-size: 16px; }
.abstract h2 { margin-top: 0; }
h2 { font: 600 23px/1.25 var(--cond); margin: 44px 0 10px; text-wrap: balance; }
h2 .n, h3 .n { color: var(--accent); margin-right: .45em; font-variant-numeric: tabular-nums; }
h3 { font: 600 18px/1.3 var(--cond); margin: 28px 0 6px; }
p { margin: 0 0 14px; }
a { color: var(--accent); }
a.loc { font: 500 12.5px var(--mono); text-decoration: none; background: var(--accent-soft); color: var(--accent); padding: 1px 5px; border-radius: 3px; white-space: nowrap; }
a.loc:hover { text-decoration: underline; }
code { font: 13.5px var(--mono); background: var(--soft); padding: 1px 4px; border-radius: 3px; }
pre { font: 13px/1.55 var(--mono); background: var(--soft); padding: 12px 14px; overflow-x: auto; max-width: 100%; }
pre code { background: none; padding: 0; }
ul, ol { padding-left: 1.3em; margin: 0 0 14px; }
li { margin: 3px 0; }
figure { margin: 26px 0 30px; }
figure svg.chart { width: 100%; height: auto; display: block; }
figcaption { font: 14px/1.5 var(--sans); color: var(--ink-2); margin-top: 8px; max-width: 80ch; }
figcaption b { color: var(--ink); font-weight: 600; }
.pair { display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 12px 24px; }
.pair > div { min-width: 0; }
.sub { font: 500 13px var(--sans); color: var(--ink-2); margin: 0 0 2px; }
.legend { display: flex; flex-wrap: wrap; gap: 4px 16px; font: 13px var(--sans); color: var(--ink-2); margin: 4px 0 2px; }
.legend span { display: inline-flex; align-items: center; gap: 7px; }
.sw { display: inline-block; width: 20px; height: 0; border-top: 2.5px solid var(--s1); }
.sw.s2 { border-color: var(--s2); } .sw.s3 { border-color: var(--s3); } .sw.ink { border-color: var(--ink-2); }
.sw.dot { width: 10px; height: 10px; border: 2px solid var(--s1); border-radius: 50%; }
.sw.dot.s2 { border-color: var(--s2); } .sw.dot.ink { border-color: var(--ink-2); }
svg.chart .grid { stroke: var(--grid); stroke-width: 1; }
svg.chart .axis { stroke: var(--rule); stroke-width: 1.2; }
svg.chart .tick { fill: var(--muted); font: 11.5px var(--mono); }
svg.chart .axlab { fill: var(--ink-2); font: 12.5px var(--sans); }
svg.chart .cat { fill: var(--ink-2); font: 12.5px var(--sans); }
svg.chart .bval { fill: var(--muted); font: 11px var(--mono); }
svg.chart .note { fill: var(--muted); font: 11.5px var(--sans); }
svg.chart .dl { font: 600 12px var(--sans); fill: var(--ink-2); }
svg.chart .ln { fill: none; stroke-linejoin: round; stroke-linecap: round; }
svg.chart .ln.s1 { stroke: var(--s1); } svg.chart .ln.s2 { stroke: var(--s2); } svg.chart .ln.s3 { stroke: var(--s3); }
svg.chart .ln.ink { stroke: var(--ink-2); }
svg.chart .ln.ref { stroke: var(--muted); stroke-width: 1.2; stroke-dasharray: 5 4; }
svg.chart .band { fill: var(--soft); stroke: none; }
svg.chart .mk { stroke: var(--paper); stroke-width: 2; }
svg.chart .mk.s1 { fill: var(--s1); } svg.chart .mk.s2 { fill: var(--s2); } svg.chart .mk.s3 { fill: var(--s3); } svg.chart .mk.ink { fill: var(--ink-2); }
svg.chart .mk.hollow { fill: var(--paper); stroke-width: 2.4; }
svg.chart .mk.hollow.s1 { stroke: var(--s1); } svg.chart .mk.hollow.s2 { stroke: var(--s2); } svg.chart .mk.hollow.ink { stroke: var(--ink-2); }
svg.chart .bar.s1 { fill: var(--s1); } svg.chart .bar.s2 { fill: var(--s2); }
svg.chart .hit { fill: transparent; cursor: crosshair; }
svg.chart .hit:hover { fill: var(--ink); fill-opacity: .16; }
.scroll { overflow-x: auto; max-width: 100%; margin: 18px 0 24px; }
table { border-collapse: collapse; width: 100%; font: 13.5px/1.45 var(--sans); }
caption { caption-side: top; text-align: left; font: 14px/1.5 var(--sans); color: var(--ink-2); padding-bottom: 8px; }
th { text-align: left; font-weight: 600; color: var(--ink); border-bottom: 1.5px solid var(--ink-2); padding: 6px 10px 6px 0; vertical-align: bottom; }
td { border-bottom: 1px solid var(--rule); padding: 7px 10px 7px 0; vertical-align: top; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td.good { color: var(--ink); }
.eqblock { overflow-x: auto; max-width: 100%; margin: 6px 0 14px; }
mjx-container[display="true"] { overflow-x: auto; overflow-y: hidden; max-width: 100%; }
.callout { background: var(--warn-bg); border: 1px solid var(--warn-rule); padding: 14px 18px; margin: 18px 0; font-size: 16px; }
.callout .tag { font: 600 11.5px var(--cond); letter-spacing: .08em; text-transform: uppercase; color: var(--warn); display: block; margin-bottom: 4px; }
.new { font: 600 11px var(--cond); letter-spacing: .06em; text-transform: uppercase; color: var(--accent); background: var(--accent-soft); padding: 1px 6px; border-radius: 3px; margin-left: 6px; vertical-align: 2px; }
.refs { font: 14.5px/1.5 var(--serif); padding-left: 2.2em; }
.refs li { margin: 5px 0; }
.foot { font: 13px/1.5 var(--sans); color: var(--muted); margin-top: 36px; border-top: 1px solid var(--rule); padding-top: 12px; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
@media (max-width: 560px) { body { font-size: 16px; } .abstract { padding: 16px; } }
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500'
         '&family=IBM+Plex+Sans+Condensed:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600'
         '&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap">')

MATHJAX = ('<script>window.MathJax = { tex: { tags: "ams", inlineMath: [["\\\\(", "\\\\)"]], '
           'displayMath: [["\\\\[", "\\\\]"]] }, svg: { fontCache: "global" }, options: { enableMenu: false } };</script>'
           '<script src="https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-svg.js" async></script>')


def pct(v):
    return f"{100 * v:.1f}"


def build(val, ext, commit, date):
    C = code_links(commit)
    res = val["results"]
    meas = val["measured"]

    def eta(key, i=0):
        return res[key][i]["eta"]

    # ---------------- figure: validation parity
    cases_ = [("SR-3 design, M 0.80", meas["sr3_design"], eta("sr3_design")),
              ("SR-3 design loading, M 0.85", meas["sr3_m085"], res["sr3_mach_trend"][1]["eta"]),
              ("SR-2, M 0.80", meas["sr2_design"], eta("sr2_design")),
              ("SR-3 take-off", meas["sr3_takeoff"], eta("sr3_takeoff")),
              ("SR-2 take-off", meas["sr2_takeoff"], eta("sr2_takeoff"))]
    errs = [100 * (m - d) for _, d, m in cases_]
    mae = sum(abs(e) for e in errs) / len(errs)
    par = chart([dict(x=[100 * d for _, d, _ in cases_[:3]], y=[100 * m for _, _, m in cases_[:3]], cls="s1",
                      kind="marker", name="cruise",
                      tip=[f"{n}: measured {100 * d:.1f} %, hsprop {100 * m:.1f} %" for n, d, m in cases_[:3]]),
                 dict(x=[100 * d for _, d, _ in cases_[3:]], y=[100 * m for _, _, m in cases_[3:]], cls="s2",
                      kind="marker", name="take-off",
                      tip=[f"{n}: measured {100 * d:.1f} %, hsprop {100 * m:.1f} %" for n, d, m in cases_[3:]])],
                "measured net efficiency (%)", "hsprop net efficiency (%)", (48, 82), (48, 82),
                xticks=[50, 55, 60, 65, 70, 75, 80], yticks=[50, 55, 60, 65, 70, 75, 80], w=520, h=420,
                label="Predicted against measured efficiency", refs=[("band", (-3, 3), ""), ("diag", 0, "")],
                notes=[(72.5, 79.0, "±3 points", "middle")])

    # ---------------- figure: Mach trend
    tr3 = sorted(res["sr3_mach_trend"], key=lambda r: r["mach"])
    tr2 = sorted(res["sr2_mach_trend"], key=lambda r: r["mach"])
    mach = chart([dict(x=[r["mach"] for r in tr3], y=[100 * r["eta"] for r in tr3], cls="s1", kind="line+marker",
                       name="SR-3 class (hsprop)", tip=[f"SR-3 class, M {r['mach']:.2f}: {100 * r['eta']:.1f} %" for r in tr3]),
                  dict(x=[r["mach"] for r in tr2], y=[100 * r["eta"] for r in tr2], cls="s2", kind="line+marker",
                       name="SR-2 class (hsprop)", tip=[f"SR-2 class, M {r['mach']:.2f}: {100 * r['eta']:.1f} %" for r in tr2]),
                  dict(x=[0.8, 0.85], y=[78.7, 74.3], cls="s1", kind="hollow", r=6, name="SR-3 measured",
                       tip=["SR-3 measured, M 0.80: 78.7 % (TM-79124)", "SR-3 measured, M 0.85: 74.3 % (TM-88969)"]),
                  dict(x=[0.8], y=[75.8], cls="s2", kind="hollow", r=6, name="SR-2 measured",
                       tip=["SR-2 measured, M 0.80: 75.8 % (TM-79124)"])],
                 "flight Mach number", "net efficiency (%)", (0.58, 0.87), (70, 86),
                 xticks=[0.6, 0.65, 0.7, 0.75, 0.8, 0.85], yticks=[70, 74, 78, 82, 86], w=520, h=420,
                 label="Efficiency against Mach number at constant power loading")

    # ---------------- figure: power sweep
    p3 = sorted(res["sr3_power_m08"], key=lambda r: r["CP"])
    p2 = sorted(res["sr2_power_m08"], key=lambda r: r["CP"])
    hs = sorted(res["hs12_power_m08"], key=lambda r: r["CP"])
    power = chart([dict(x=[r["CP"] for r in p3], y=[100 * r["eta"] for r in p3], cls="s1", kind="line+marker",
                        name="SR-3 class", tip=[f"SR-3 class, CP {r['CP']:.2f}: {100 * r['eta']:.1f} %" for r in p3],
                        lab=(2.62, 62.5, "end")),
                   dict(x=[r["CP"] for r in p2], y=[100 * r["eta"] for r in p2], cls="s2", kind="line+marker",
                        name="SR-2 class", tip=[f"SR-2 class, CP {r['CP']:.2f}: {100 * r['eta']:.1f} %" for r in p2],
                        lab=(0.62, 49.5, "start")),
                   dict(x=[r["CP"] for r in hs], y=[100 * r["eta"] for r in hs], cls="s3", kind="line+marker",
                        name="12-blade", tip=[f"12-blade, CP {r['CP']:.2f}: {100 * r['eta']:.1f} %" for r in hs],
                        lab=(3.0, 66.3, "end")),
                   dict(x=[1.7], y=[78.7], cls="s1", kind="hollow", r=6, name="SR-3 measured",
                        tip=["SR-3 measured at the design point: 78.7 %"]),
                   dict(x=[1.7], y=[75.8], cls="s2", kind="hollow", r=6, name="SR-2 measured",
                        tip=["SR-2 measured at the design point: 75.8 %"])],
                  "power coefficient CP", "net efficiency (%)", (0.5, 3.1), (48, 84),
                  xticks=[0.5, 1.0, 1.5, 2.0, 2.5, 3.0], yticks=[50, 56, 62, 68, 74, 80],
                  label="Efficiency against power coefficient at Mach 0.8", refs=[("h", 80.0, "")],
                  notes=[(0.55, 81.3, "SR-3 above 80 % at lower power (TM-79124)", "start")])

    # ---------------- figure: loss breakdown
    keys = [("induced_axial", "induced, axial"), ("induced_swirl", "induced, swirl"), ("profile", "profile (friction)"),
            ("wave", "wave (shocks)"), ("separation_le", "separation and leading edge"), ("choke", "passage choke")]
    Ld = res["sr3_design"][0]["losses"]
    Lt = res["sr3_takeoff"][0]["losses"]
    losses = barh([k[1] for k in keys],
                  [dict(name="cruise, M 0.8, CP 1.7", cls="s1", values=[100 * Ld[k] for k, _ in keys]),
                   dict(name="take-off, M 0.2, CP 1.0", cls="s2", values=[100 * Lt[k] for k, _ in keys])],
                  "loss, % of shaft power", (0, 28), label="Loss breakdown of the SR-3 class", unit=" %")

    # ---------------- figure: ablation
    abl = [(k.split("|")[2], v[0]["eta"]) for k, v in res.items() if k.startswith("ablation|design|")]
    ablt = {k.split("|")[2]: v[0]["eta"] for k, v in res.items() if k.startswith("ablation|takeoff|")}
    base_d, base_t = eta("sr3_design"), eta("sr3_takeoff")
    ablation = barh([a for a, _ in abl],
                    [dict(name="cruise", cls="s1", values=[100 * (e - base_d) for _, e in abl]),
                     dict(name="take-off", cls="s2", values=[100 * (ablt[a] - base_t) for a, _ in abl])],
                    "change of net efficiency when the model is switched off (points)", (-2, 6),
                    label="Ablation study", unit=" points")

    # ---------------- figure: radial, design point
    rd = ext["design"]["radial"]
    rad_m = chart([dict(x=rd["r_R"], y=rd["mach"], cls="ink", kind="line", name="relative Mach number",
                        lab=(0.66, 1.0, "end"), dash=True),
                   dict(x=rd["r_R"], y=rd["mach_n"], cls="s1", kind="line", name="normal Mach number",
                        lab=(0.995, 1.22, "end")),
                   dict(x=rd["r_R"], y=rd["mach_n_eff"], cls="s2", kind="line", name="effective (3-D relief)",
                        lab=(0.99, 0.62, "end"))],
                  "r / R", "Mach number", (0.2, 1.0), (0.5, 1.25), xticks=[0.2, 0.4, 0.6, 0.8, 1.0],
                  yticks=[0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2], w=520, h=320,
                  label="Mach numbers along the SR-3-class blade at the design point")
    rad_d = chart([dict(x=rd["r_R"], y=[1e4 * v for v in rd["cd_profile"]], cls="s1", kind="line", name="profile",
                        lab=(0.42, 108, "middle")),
                   dict(x=rd["r_R"], y=[1e4 * v for v in rd["cd_wave"]], cls="s2", kind="line", name="wave",
                        lab=(0.86, 104, "end")),
                   dict(x=rd["r_R"], y=[1e4 * v for v in rd["cd_choke"]], cls="s3", kind="line", name="choke",
                        lab=(0.3, 24, "middle"))],
                  "r / R", "section drag (counts)", (0.2, 1.0), (0, 150), xticks=[0.2, 0.4, 0.6, 0.8, 1.0],
                  yticks=[0, 50, 100, 150], w=520, h=320, label="Section drag components at the design point")

    # ---------------- figure: low power choke spill
    rl = ext["low_power"]["radial"]
    V = rl["V"]
    spill = chart([dict(x=rl["r_R"], y=rl["choke_ratio"], cls="s1", kind="line+marker", r=3, name="choke ratio",
                         tip=[f"r/R {a:.3f}: chi {b:.3f}" for a, b in zip(rl["r_R"], rl["choke_ratio"])])],
                  "r / R", "choke ratio  χ", (0.2, 1.0), (0.7, 1.05), xticks=[0.2, 0.4, 0.6, 0.8, 1.0],
                  yticks=[0.7, 0.8, 0.9, 1.0], w=520, h=300, label="Passage choke ratio at low power",
                  refs=[("h", 1.0, "")])
    spill2 = chart([dict(x=rl["r_R"], y=[-100 * u / V for u in rl["u_spill"]], cls="s2", kind="line+marker", r=3,
                         name="spilled inflow",
                         tip=[f"r/R {a:.3f}: spill {-100 * u / V:.2f} % of V" for a, u in zip(rl["r_R"], rl["u_spill"])])],
                   "r / R", "spilled inflow (% of V)", (0.2, 1.0), (0, 8), xticks=[0.2, 0.4, 0.6, 0.8, 1.0],
                   yticks=[0, 2, 4, 6, 8], w=520, h=300, label="Spilled inflow at low power")

    # ---------------- figure: sections, thin vs thick
    sc = ext["sections"]
    secfig = chart([dict(x=sc["alpha"], y=sc["cl_0.04"], cls="s1", kind="line", name="4 % thick (long bubble)",
                         lab=(17.5, 0.62, "end")),
                    dict(x=sc["alpha"], y=sc["cl_0.12"], cls="s2", kind="line", name="12 % thick (leading-edge stall)",
                         lab=(17.5, 0.38, "end"))],
                   "angle of attack (deg)", "lift coefficient", (0, 18), (0, 1.6), xticks=[0, 3, 6, 9, 12, 15, 18],
                   yticks=[0, 0.4, 0.8, 1.2, 1.6], w=520, h=300, label="Lift of thin and thick sections")
    tc = ext["transition"]
    trfig = chart([dict(x=tc["alpha"], y=tc["xtr_upper"], cls="s1", kind="line", name="upper surface",
                        lab=(2.9, 0.62, "end")),
                   dict(x=tc["alpha"], y=tc["xtr_lower"], cls="s2", kind="line", name="lower surface",
                        lab=(-2.9, 0.1, "start"))],
                  "angle of attack (deg)", "transition x / c", (-3, 3), (0, 1), xticks=[-3, -2, -1, 0, 1, 2, 3],
                  yticks=[0, 0.25, 0.5, 0.75, 1.0], w=520, h=300, label="Expected transition location")

    # ---------------- tables
    def row(cells, num_from=1):
        return "<tr>" + "".join(f'<td class="num">{c}</td>' if i >= num_from else f"<td>{c}</td>"
                                for i, c in enumerate(cells)) + "</tr>"
    vtab = "".join(row([n, pct(d), pct(m), f"{100 * (m - d):+.1f}"]) for n, d, m in cases_)
    trtab = "".join(row([f"{r3['mach']:.2f}", f"{r3['J']:.3f}", f"{r3['CP']:.3f}", pct(r3['eta']), pct(r2['eta'])], 0)
                    for r3, r2 in zip(tr3, tr2))
    ptab = "".join(row([f"{r['CP']:.2f}", pct(r['eta']), f"{r['CT']:.3f}", f"{r['beta75']:.2f}"], 0) for r in p3)
    eu = json.loads((ROOT / "data" / "euler_lattice_verification.json").read_text())
    etab = ""
    for c in sorted(eu, key=lambda c: c["sigma"]):
        e, lm, nv = (c["euler"][1] / c["euler"][0], c["lattice_map"][1] / c["lattice_map"][0], c["naive"][1] / c["naive"][0])
        etab += row([f"{c['sigma']:.1f}", f"{c['stagger']:.0f}°", f"{c['M_lo']:.1f} → {c['M_hi']:.2f}", f"{e:.3f}",
                     f"{lm:.3f} ({100 * (lm / e - 1):+.1f} %)", f"{nv:.3f} ({100 * (nv / e - 1):+.1f} %)"], 3)

    ld = ext["design"]["losses"]
    sections = []
    S = sections.append

    S(f"""
<section class="abstract" id="abstract">
<h2>Abstract</h2>
<p><code>hsprop</code> predicts the performance of propellers whose blades are so wide and so numerous that the blade
row behaves like a compressor cascade: the propfans of the 1980s and the very-high-solidity propellers proposed for
Mach 0.8 transport. A load-adapted lifting line carries blade elements that are compressible, swept rows of thin
aerofoils. Six models are new: a Prandtl–Glauert map of the blade lattice, verified against Euler solutions; a
spanwise-wavenumber relief of the normal Mach number that bounds strip theory near Mach 1; a shock-loss integral
built on the exact normal-shock entropy rise; a leading-edge separation model that separates long-bubble
decambering on thin unswept sections from the leading-edge vortex on swept ones; passage choke at low power posed
as a complementarity condition and solved inside Newton's method together with the circulation; and transition
treated as a random process, whose expected location is a smooth functional of the edge-speed distribution. The
model was compared with five measured efficiencies of the NASA SR-3 and SR-2 propfans from take-off (Mach 0.2)
to Mach 0.85; the mean absolute error is {mae:.1f} points and the largest {max(abs(e) for e in errs):.1f}. Every
operating point from CP 0.6 to 2.6 at Mach 0.8 and at take-off converges, in 2–10 s each.</p>
</section>

<h2 id="s1"><span class="n">1</span>The problem</h2>
<p>A propfan blade row at Mach 0.8 is three different machines. At the design point the outer blade runs at
helical Mach numbers of 1.0–1.15 behind 30–45° of sweep, its sections only 2–3 % thick and, near the root, a
solidity above 1: a transonic swept cascade. At take-off the same sections meet the air 5–12° off their design
incidence, the leading-edge suction peaks of 2 % sections cannot be carried, and the flow separates at the nose. At
low power the root sections turn to negative incidence in passages narrower than their inlet streamtubes, and
choke. A blade-element method built on isolated aerofoils and a Prandtl–Glauert factor misses all three. The NASA
SR series (eight blades, activity factor 203–235, design point Mach 0.8, J 3.06, CP 1.7) is the reference
data set for this class of propeller and is used here for validation.</p>

<h2 id="s2"><span class="n">2</span>Model overview</h2>
<p>The blade is a lifting line on its quarter-chord line, discretised into 28 cosine-spaced strips. Its trailing
vorticity follows a prescribed helicoidal wake whose pitch and contraction adapt to the loading
({C['wake.py:vortex']}); images in the spinner close the wake at the hub. Each strip is evaluated as a blade element
in the plane normal to its effective sweep ({C['section.py:evaluate']}): an infinite row of thin aerofoils with
thickness and camber, in compressible flow, with a boundary layer, shock losses, separation and passage choke.
The circulation and the choke spillage of all strips are found together by Newton's method
({C['solver.py:newton']}), and the collective pitch is trimmed to a power or thrust coefficient
({C['solver.py:solve_for']}). The spinner and nacelle enter through a compressible line-source solution
({C['nacelle.py:nacelle']}).</p>

<h2 id="s3"><span class="n">3</span>The blade element as a compressible row<span class="new">new</span></h2>
<p>Linear thin-aerofoil theory for a periodic row is solved exactly: the vorticity and source distributions are
Glauert series, the row kernel is the periodic Cauchy kernel less its isolated part,</p>
<div class="eqblock">\\[ R(\\zeta) = \\cot\\frac{{\\pi\\zeta}}{{P}} - \\frac{{P}}{{\\pi\\zeta}}, \\qquad \\zeta \\in \\mathbb{{C}}, \\]</div>
<p>and the boundary condition is projected on the Chebyshev modes (Galerkin), {C['cascade.py:ThinCascade']}. The
flat-plate row reproduces Weinig's exact lift to four digits. Compressibility enters through a new result. The
linearised compressible flow through a row of pitch \\(s\\) and stagger \\(\\xi\\) is, after the Prandtl–Glauert
stretch of the chordwise coordinate, an incompressible flow through a <em>different</em> row:</p>
<div class="eqblock">\\[ s' = s\\sqrt{{\\sin^2\\xi + \\beta^2\\cos^2\\xi}}, \\qquad \\tan\\xi' = \\frac{{\\tan\\xi}}{{\\beta}}, \\qquad
u_{{\\text{{comp}}}} = \\frac{{u'_{{\\text{{inc}}}}}}{{\\beta}}, \\qquad \\beta = \\sqrt{{1 - M_n^2}}. \\]</div>
<p>A dense row therefore feels compressibility through its geometry as well as through the factor \\(1/\\beta\\): the
mapped row is more staggered and, for small stagger, denser. The common practice of dividing the incompressible
row result by \\(\\beta\\) ignores this. Table 1 compares both with Euler solutions of the same rows
({C['cascade.py:map_lattice']}); a universal table of the mapped-row solution, interpolated in
\\(\\ln(\\sigma' + 0.05)\\) and \\(\\xi'\\), makes the section evaluation cheap ({C['cascade.py:solve_tabulated']}).</p>
<div class="scroll"><table>
<caption><b>Table 1.</b> Change of row lift slope between two Mach numbers: Euler solution, lattice map and the naive
\\(1/\\beta\\) rule (error against Euler in brackets).</caption>
<thead><tr><th class="num">σ</th><th class="num">stagger</th><th class="num">M</th><th class="num">Euler</th>
<th class="num">lattice map</th><th class="num">naive PG</th></tr></thead><tbody>{etab}</tbody></table></div>
<p>The section is placed in the plane normal to its effective sweep (independence principle), with Küchemann's
unsweeping of the isobars within a few chords of the tip. Kármán–Tsien's rule with Lighthill's nose correction
turns the linear surface speeds into pressures and local Mach numbers.</p>

<h2 id="s4"><span class="n">4</span>Transonic flow</h2>
<h3>4.1 Three-dimensional relief<span class="new">new</span></h3>
<p>Strip theory makes compressibility singular where the normal Mach number reaches 1, and propfan blades have wide
chords next to a free tip: the outer blade is a wing of aspect ratio 1–2. A linear disturbance
\\(e^{{i(k_x x + k_z z)}}\\) on a planar blade decays away from it at the rate</p>
<div class="eqblock">\\[ k_y^2 = (1 - M^2)\\,k_x^2 + k_z^2 \\quad\\Longrightarrow\\quad M_{{\\text{{eff}}}}^2 = M^2 - \\kappa^2, \\qquad \\kappa = \\frac{{k_z}}{{k_x}}, \\]</div>
<p>so a disturbance with spanwise structure behaves as a two-dimensional one at a lower Mach number. The sources and
vortices of the blade end at the tip (the hub is a mirror), so a strip at span distance \\(d\\) from the tip carries a
quarter-wave spanwise mode against the chordwise half wave: \\(\\kappa = c_n/(2d + c_n)\\)
({C['solver.py:relief_k']}). The relief applies to the chord-scale field. Near the leading edge the disturbance
scale is the distance \\(x\\) itself, so the local factor is</p>
<div class="eqblock">\\[ \\beta(x)^2 = \\beta^2 + \\kappa^2 \\min\\!\\left(\\frac{{2x}}{{c}}, 1\\right)^2 , \\]</div>
<p>and the suction peak keeps its full compressibility ({C['section.py:relief']}). Local Mach numbers are always
recovered from pressures with the actual Mach number. In the lifting line the relief recovers about half of the
gap between strip theory and the compressible finite-wing (Helmbold) lift slope at aspect ratio 2.</p>
<h3>4.2 Shock losses<span class="new">new</span></h3>
<p>The wave drag of each surface is the integral of the entropy rise of a normal shock at the local Mach number over
the supersonic region ({C['section.py:shock']}),</p>
<div class="eqblock">\\[ c_{{d,w}} = K_w \\sum_{{\\text{{surfaces}}}} \\int \\ln\\frac{{p_{{01}}}}{{p_{{02}}}}\\big(M(x)\\big)\\,dx, \\qquad K_w = 6, \\]</div>
<p>which equals the cube law \\((M-1)^3\\) near \\(M = 1.15\\), where the constant is fixed by Korn's drag-divergence
equation, reduces to Lock's fourth-power rise and grows more slowly for strong shocks. As the normal Mach number
nears 1 the pocket reaches the trailing edge and its terminal shock turns into the oblique trailing-edge shocks of
supersonic flow; the drag is then bounded smoothly by that of the same section at the low-supersonic end of the
band, \\(c_{{d,w}} \\leftarrow (c_{{d,w}}^{{-4}} + c_{{d,\\text{{Ackeret}}}}^{{-4}})^{{-1/4}}\\). Above \\(M_n = 0.9\\) the section blends
into linear supersonic theory, which it reaches at 1.15.</p>

<h2 id="s5"><span class="n">5</span>High power: leading-edge separation<span class="new">new</span></h2>
<p>The suction a nose can carry is limited: by a short laminar bubble at low speed (\\(C_p \\ge -7\\)) and by a shock
above a local Mach number of 1.45. With \\(\\eta\\) the ratio of that limit to the linear-theory suction peak, the
lost part of the leading-edge thrust is drag, as in Carlson's attainable-thrust method ({C['section.py:cp_lim']}):</p>
<div class="eqblock">\\[ c_{{d,\\text{{le}}}} = (1 - \\eta)\\,\\frac{{2\\pi A_0^2}}{{\\beta}}\\sqrt{{f}}, \\]</div>
<p>where \\(A_0\\) is the leading-edge coefficient of the row solution and \\(f\\) the attached fraction (the suction of a
partly separated section scales with \\(\\sqrt f\\), as in the Beddoes–Leishman chord force). What happens next depends
on thickness and sweep, after McCullough &amp; Gault's three types of stall ({C['section.py:thin']}):</p>
<ul>
<li>a thick section (normal-plane \\(t/c\\) above 9 %) stalls at the nose when its bubble bursts;</li>
<li>on a thin, unswept section the burst bubble reattaches as a long bubble that keeps the normal force but grows
over the chord and decambers it: \\(f = 1 - 0.9\\,S\\big((|A_0|/\\beta - 0.085)/0.2\\big)\\), fitted to NACA 64A006
(lift below potential from about 5°, maximum 0.8 near 9.5°);</li>
<li>on a swept edge the separated shear layer rolls up into a leading-edge vortex that is carried along the edge
and holds the normal force until it bursts; Polhamus' suction analogy turns the lost suction into vortex lift,
\\(\\Delta c_n = \\operatorname{{sign}}(A_0)\\,k_v\\,c_{{d,\\text{{le}}}}\\), with \\(k_v\\) rising from 0 at 10° of sweep to 1 at 40°
({C['section.py:vortex']}). Vaczy &amp; McCormick observed such a vortex on propfan blades at take-off.</li>
</ul>
<figure><div class="pair">
<div><p class="sub">(a) Lift at Mach 0.25, symmetric NACA 16 sections</p>{secfig}</div>
<div><p class="sub">(b) Expected transition location, 4 % section, Mach 0.6, free transition</p>{trfig}</div>
</div>
<figcaption><b>Figure 1.</b> (a) The thin section keeps its lift through the long-bubble regime and stalls gently
past 10°; the thick one stalls abruptly at the nose. (b) The transition point moves continuously as the suction
peaks grow on either surface (§7).</figcaption></figure>
""")

    S(f"""
<h2 id="s6"><span class="n">6</span>Low power: passage choke and spillage<span class="new">new</span></h2>
<p>A dense row passes at most the mass flow of a sonic throat. With \\(\\Phi\\) the mass-flux function, \\(A_1\\) the inlet
streamtube of one passage and \\(o\\) the throat between the suction surface of one blade and the pressure surface of
the next ({C['section.py:throat']}), the choke ratio is</p>
<div class="eqblock">\\[ \\chi = \\frac{{\\Phi(M_1)\\,A_1}}{{\\Phi^*\\,o}} \\le 1 . \\]</div>
<p>A two-dimensional row whose upstream state demands \\(\\chi > 1\\) has no solution; on a propeller the excess flow
spills radially round the strip. The spilled inflow \\(s\\) (fraction of \\(V\\)) of every strip is therefore a
complementarity variable: either \\(s = 0\\) and \\(\\chi < 1\\), or \\(\\chi = 1\\) and \\(s > 0\\). It is written with the smoothed
Fischer–Burmeister function and solved inside Newton's method together with the circulation:</p>
<div class="eqblock">\\[ R_\\Gamma = \\Gamma - G\\big(u_a(\\Gamma) - Vs,\\; u_t(\\Gamma)\\big) = 0, \\qquad
R_s = s + (1 - \\chi) - \\sqrt{{s^2 + (1-\\chi)^2 + 2\\varepsilon^2}} = 0 . \\]</div>
<p>Both residuals depend on the strips only through local section functions, so the Jacobian blocks are the
influence matrices scaled by section derivatives that two extra sweeps of the section model provide. The blockage
that spills the flow raises the pressure ahead of the root; its interaction gain is charged back as spillage drag.
Replacing an earlier fixed-point treatment by this formulation cut a low-power solution from 183 s, unconverged,
to 9 s with quadratic convergence. Figure 2 shows the result at CP 0.6.</p>
<figure><div class="pair">
<div><p class="sub">(a) Choke ratio</p>{spill}</div>
<div><p class="sub">(b) Spilled inflow</p>{spill2}</div>
</div>
<figcaption><b>Figure 2.</b> SR-3 class at Mach 0.8, CP 0.6. The root strips sit on the choke limit, \\(\\chi = 1\\), and
spill up to {max(-100 * u / V for u in rl['u_spill']):.0f} % of their inflow; outboard the passages are open and nothing spills.</figcaption></figure>

<h2 id="s7"><span class="n">7</span>Boundary layer and transition<span class="new">new</span></h2>
<p>The layer is an integral one: Thwaites' method while laminar, Head's entrainment method when turbulent, both with
compressibility, and Squire–Young's formula for the drag ({C['boundary_layer.py:march']}). A first-crossing
transition criterion jumps when a second suction peak appears or a bubble forms, and every jump breaks Newton's
method on the lifting line. Transition is therefore treated as a random process, as in Emmons' theory of turbulent
spots and the intermittency of Dhawan &amp; Narasimha. Spots are born at a rate that grows with the excess over
Michel's criterion and with the depth of laminar separation; the probability that the layer is still laminar at
\\(x\\) is \\(e^{{-B(x)}}\\), and the transition point is its expectation ({C['boundary_layer.py:transition']}):</p>
<div class="eqblock">\\[ B(x) = \\int_0^x \\left[\\frac{{(Re_\\theta/Re_{{\\theta,\\text{{Michel}}}} - 1)^+}}{{0.003}} + \\frac{{(\\lambda_{{\\text{{on}}}} - \\lambda)^+}}{{0.09 \\times 0.002}}\\right] dx', \\qquad
x_{{tr}} = \\int_0^{{x_f}} e^{{-B(x)}}\\,dx . \\]</div>
<p>It is a smooth functional of the edge speeds (Figure 1b). The default trip \\(x_f = 0.05\\) represents the
crossflow, rotation and roughness of real propfan blades; free transition is an option.</p>

<h2 id="s8"><span class="n">8</span>Lifting line, spinner and bookkeeping</h2>
<p>The induced velocities come from Biot–Savart integration over the bound and trailing vortices of all blades and
their hub images ({C['solver.py:influence']}). On a swept lifting line, thin trailing filaments induce a spurious
near-field velocity that depends on the panel width; giving each filament a core of a quarter of the local chord,
the scale over which a section sheds its vorticity, removes it, and results do not change for cores between 0.1
and 0.4 chords. The relative state of every strip follows from the rothalpy. Power, thrust and the losses balance
exactly ({C['solver.py:assemble']}):</p>
<div class="eqblock">\\[ P - T V = L_{{\\text{{induced, axial}}}} + L_{{\\text{{induced, swirl}}}} + L_{{\\text{{profile}}}} + L_{{\\text{{wave}}}} + L_{{\\text{{separation}}}} + L_{{\\text{{choke}}}} + L_{{\\text{{spill}}}} . \\]</div>
<p>The work the blades do against the spinner's velocity field returns as the pressure force the propeller field
exerts on the body: a potential flow does no net work. The net thrust includes that reaction
({C['solver.py:body']}), so a spinner earns only its real benefit, a lower Mach number at the blade root. At the
SR-3 design point the induced losses are {pct(ld['induced_axial'] + ld['induced_swirl'])} % of the power
({pct(ld['induced_swirl'])} % of it swirl), profile drag {pct(ld['profile'])} %, shocks {pct(ld['wave'])} % and choke
{pct(ld['choke'])} % (Figure 3).</p>
<figure>{legend([("cruise, M 0.8, CP 1.7", "s1", False), ("take-off, M 0.2, CP 1.0", "s2", False)])}{losses}
<figcaption><b>Figure 3.</b> Where the power goes, SR-3 class. At cruise the swirl left in the wake is the largest
loss; at take-off the axial momentum of the heavily loaded disk and the separated leading edges dominate.</figcaption></figure>

<h2 id="s9"><span class="n">9</span>Numerics</h2>
<p>Newton's method with a backtracking line search and a trust region of 6° on the change of incidence solves for
circulation and spillage. The influence matrices are frozen within a Newton solve and the wake is re-shaped a few
times. A first solve with attached flow everywhere (a homotopy) starts the full model next to the physical branch.
Near stall a propeller has two solutions at one power, attached and stalled at a higher pitch, so the pitch is
approached from the attached side, as a governor does: a pitch below the target on the attached branch, from an
actuator-disk estimate ({C['solver.py:estimate']}), then a bracket and Illinois regula falsi. Every model in §3–7
is a smooth function of the inflow, which keeps the convergence quadratic; a point takes 2–10 s.</p>

<h2 id="s10"><span class="n">10</span>Inverse design</h2>
<p>The reference propellers are designed the way the SR blades were ({C['design.py:design']}). The loading is the
Betz optimum in the closed form of Betz and Prandtl,
\\(B\\Gamma = 2\\pi r F w \\sin\\phi\\cos\\phi\\), with Prandtl's tip function \\(F\\) and no hub loss behind the spinner
({C['design.py:betz']}); the outer 10 % is unloaded for compressibility. Every section carries its share at ideal
incidence, zero leading-edge singularity in its compressible swept row, which fixes camber and twist
({C['design.py:ideal']}); \\(w\\) is trimmed to the design power. Designed this way without the 3-D relief, the
SR-3-class blade gets an integrated design lift coefficient of 0.196 against the published 0.214.</p>
""")

    S(f"""
<h2 id="s11"><span class="n">11</span>Verification</h2>
<div class="scroll"><table>
<caption><b>Table 2.</b> Checks against exact or independent results (all in <code>tests/</code>).</caption>
<thead><tr><th>Check</th><th>Result</th></tr></thead><tbody>
<tr><td>Weinig's exact flat-plate cascade</td><td>reproduced to 4 digits</td></tr>
<tr><td>Lattice map against Euler solutions (Table 1)</td><td>within −8.7 … +1.4 %; naive rule −18 … +29 %</td></tr>
<tr><td>Isolated aerofoil against a panel method (pymises)</td><td>within 1 %</td></tr>
<tr><td>Spheroid surface speed; Göthert's rule</td><td>within 0.6 %; within 5 %</td></tr>
<tr><td>Blasius plate; turbulent plate (Schlichting)</td><td>within 2 %; 6 % low</td></tr>
<tr><td>Drag divergence of a 6 % section</td><td>Korn's equation with κ<sub>A</sub> ≈ 0.90</td></tr>
<tr><td>Weak-shock entropy law</td><td>within 8 % at M = 1.01–1.02</td></tr>
<tr><td>48-bladed rotor against the actuator disk</td><td>swirl within 1 %, axial velocity within 3 %</td></tr>
<tr><td>Loss bookkeeping</td><td>P − TV equals the itemised losses to 10<sup>−9</sup></td></tr>
<tr><td>Choke complementarity at low power</td><td>χ = 1 ± 0.01 wherever s &gt; 1 %, s ≈ 0 where χ &lt; 0.95</td></tr>
<tr><td>Transition continuity</td><td>largest drag step shrinks with the incidence step</td></tr>
</tbody></table></div>

<h2 id="s12"><span class="n">12</span>Validation against the NASA tests</h2>
<p>Neither blade's tabulated geometry was available, so both were reconstructed from their published descriptions
({C['design.py:design']}): eight blades, 0.622 m diameter, hub-to-tip ratio 0.235 and NACA 16 sections. SR-3 has
activity factor 235, 45° tip sweep and an area-ruled spinner; SR-2 is straight, with activity factor 203 and a
conventional spinner. Planform and thickness are smooth curves with the published integral properties; camber
and twist come from §10. Cruise points are run at the Reynolds number of the NASA Lewis 8×6 ft tunnel, take-off
at sea level. <code>tools/validate.py</code> reproduces every number below in about two minutes on four cores.</p>
<div class="scroll"><table>
<caption><b>Table 3.</b> Net efficiency, measured and predicted (percent).</caption>
<thead><tr><th>Case</th><th class="num">measured</th><th class="num">hsprop</th><th class="num">error</th></tr></thead>
<tbody>{vtab}</tbody></table></div>
<figure><div class="pair">
<div><p class="sub">(a) Predicted against measured</p>{legend([("cruise", "s1", True), ("take-off", "s2", True)])}{par}</div>
<div><p class="sub">(b) Constant design power loading (CP/J³ and tip speed fixed)</p>
{legend([("SR-3 class", "s1", False), ("SR-2 class", "s2", False), ("measured", "ink", True)])}{mach}</div>
</div>
<figcaption><b>Figure 4.</b> (a) All five measured efficiencies are predicted within ±3 points; mean absolute error
{mae:.1f} points. (b) The predicted efficiency is flat to Mach 0.7 and falls steeply beyond 0.8, as measured: 4.0
points from Mach 0.8 to 0.85 against 4.4. The model places SR-2 within 2 points of SR-3, where the tests showed it 3
points lower.</figcaption></figure>
<figure>{legend([("SR-3 class", "s1", False), ("SR-2 class", "s2", False), ("12-blade, AF 200", "s3", False), ("measured", "ink", True)])}{power}
<figcaption><b>Figure 5.</b> Power sweep at Mach 0.8 and J 3.06, from low power (choked roots, negative incidence)
to high power (shocks and separation at the tip). The SR-3 class peaks at {max(100 * r['eta'] for r in p3):.1f} % near
CP 1.2; the tests reported efficiencies above 80 % at power loadings below the design value. The twelve-bladed
derivative carries 30 % more power at the same efficiency.</figcaption></figure>
<div class="scroll"><table>
<caption><b>Table 4.</b> Mach trend at constant design power loading (net efficiency, %).</caption>
<thead><tr><th class="num">M</th><th class="num">J</th><th class="num">CP</th><th class="num">SR-3 class</th><th class="num">SR-2 class</th></tr></thead>
<tbody>{trtab}</tbody></table></div>
<figure><div class="pair">
<div><p class="sub">(a) Mach numbers along the blade</p>{rad_m}</div>
<div><p class="sub">(b) Section drag components</p>{rad_d}</div>
</div>
<figcaption><b>Figure 6.</b> SR-3 class at the design point. Sweep holds the normal Mach number near 0.85 over the
outer blade; Küchemann's unsweeping lifts it toward the tip, and the 3-D relief lowers the effective value there. The
wave drag concentrates in the outer 10 % of the span; the root strips sit at the choke limit.</figcaption></figure>

<h2 id="s13"><span class="n">13</span>What each model contributes</h2>
<p>Switching each model off in turn at the SR-3 design point and at take-off (Figure 7) shows where it matters. At
take-off the limited leading-edge suction is worth 5.6 points: without it the thin blades would carry suction peaks
no real nose can. At cruise the 3-D relief, the transition model, the cascade, sweep and choke spillage each move
the efficiency by 1–2 points.</p>
<figure>{legend([("cruise", "s1", False), ("take-off", "s2", False)])}{ablation}
<figcaption><b>Figure 7.</b> Change of net efficiency when one model is switched off (points).</figcaption></figure>

<h2 id="s14"><span class="n">14</span>Limitations</h2>
<ul>
<li>The reconstructed geometries are the largest single uncertainty. The model does not resolve the measured 3–5
point advantage of SR-3 over SR-2; it places both within ±3 points of their data.</li>
<li>The 3-D relief, Küchemann unsweeping and vortex lift are strip-wise models of three-dimensional effects, not a
lifting-surface or CFD solution. Normal Mach numbers above 1.15 use linear supersonic theory.</li>
<li>Steady axisymmetric inflow, single rotation; no angle of attack, no contra-rotation, no noise.</li>
<li>The net efficiency includes the body's reaction to the propeller field; blade-only efficiency is reported as
<code>eta_blade</code>.</li>
</ul>

<h2 id="s15"><span class="n">15</span>Using it</h2>
<pre><code>cd propfan &amp;&amp; pip install -e ".[plot,test]"
hsprop run examples/my_propeller.toml        # your geometry, points and sweeps from a TOML file
hsprop point sr3_class --mach 0.8 --altitude 10668 --J 3.06 --CP 1.7 --radial
hsprop design my_prop.json --mach 0.8 --altitude 10668 --tip-speed 243.8 --CP 1.7 -o designed.json
python tools/validate.py                     # the validation in §12-13</code></pre>
<p>A geometry is a table of radius, chord, blade angle, thickness, design lift coefficient and sweep, with a spinner
or any axisymmetric nacelle; every model can be switched in a <code>[model]</code> section.</p>

<h2 id="refs">References</h2>
<ol class="refs">
<li>R. J. Jeracki, D. C. Mikkelson, B. J. Blaha. <em>Wind tunnel performance of four energy efficient propellers
designed for Mach 0.8 cruise.</em> NASA TM-79124, 1979. <a href="https://ntrs.nasa.gov/citations/19790011898">NTRS 19790011898</a></li>
<li>C. Rohrbach, F. B. Metzger, D. M. Black, R. M. Ladden. <em>Evaluation of wind tunnel performance testings of
an advanced 45° swept eight-bladed propeller at Mach numbers from 0.45 to 0.85.</em> NASA CR-3505, 1982.
<a href="https://ntrs.nasa.gov/api/citations/19820011304/downloads/19820011304.pdf">NTRS 19820011304</a></li>
<li>G. L. Stefko, R. J. Jeracki. <em>Wind tunnel results of advanced high speed propellers in the takeoff, climb
and landing operating regimes.</em> NASA TM-87030, 1985. <a href="https://ntrs.nasa.gov/citations/19850021613">NTRS 19850021613</a></li>
<li>D. C. Mikkelson, G. A. Mitchell, L. J. Bober. <em>Summary of recent NASA propeller research.</em> NASA
TM-83733, 1984. <a href="https://ntrs.nasa.gov/api/citations/19840024274/downloads/19840024274.pdf">NTRS 19840024274</a></li>
<li><em>Experimental aerodynamic performance of advanced 40°-swept, 10-blade propeller model at Mach 0.6 to
0.85.</em> NASA TM-88969, 1988. <a href="https://ntrs.nasa.gov/api/citations/19890001494/downloads/19890001494.pdf">NTRS 19890001494</a></li>
<li>G. L. Stefko, G. E. Rose, G. G. Podboy. <em>Wind tunnel performance results of an aeroelastically scaled 2/9
model of the PTA flight test prop-fan.</em> NASA TM-89917, 1987. <a href="https://ntrs.nasa.gov/citations/19870015861">NTRS 19870015861</a></li>
<li>F. Weinig. <em>Die Strömung um die Schaufeln von Turbomaschinen.</em> Barth, Leipzig, 1935.</li>
<li>D. Küchemann. <em>The aerodynamic design of aircraft.</em> Pergamon, 1978.</li>
<li>E. C. Polhamus. <em>A concept of the vortex lift of sharp-edge delta wings based on a leading-edge-suction
analogy.</em> NASA TN D-3767, 1966.</li>
<li>B. A. Vaczy, D. C. McCormick. <em>A study of the leading edge vortex and tip vortex on prop-fan blades.</em>
ASME Journal of Turbomachinery 109, 1987.</li>
<li>G. B. McCullough, D. E. Gault. <em>Examples of three representative types of airfoil-section stall at low
speed.</em> NACA TN 2502, 1951.</li>
<li>H. W. Carlson, R. J. Mack. <em>Estimation of leading-edge thrust for supersonic wings of arbitrary planform.</em>
NASA TP-1270, 1978.</li>
<li>H. W. Emmons. <em>The laminar-turbulent transition in a boundary layer.</em> J. Aeronautical Sciences 18,
1951; S. Dhawan, R. Narasimha. J. Fluid Mechanics 3, 1958.</li>
<li>B. Thwaites (1949); M. R. Head (1958); R. Michel (1951); R. C. Lock (1986); A. Fischer, <em>A special Newton-type
optimization method</em>, Optimization 24, 1992.</li>
<li>C. N. Adkins, R. H. Liebeck. <em>Design of optimum propellers.</em> J. Propulsion and Power 10, 1994.</li>
</ol>
<p class="foot">Built by <code>tools/build_report.py</code> on {date} from commit {commit}. Figures are drawn from the
stored solver output (<code>data/validation.json</code>, <code>data/report_extra.json</code>); hover over a data
point for its values.</p>
""")
    body = "".join(sections)
    toc = [("abstract", "", "Abstract"), ("s1", "1", "The problem"), ("s2", "2", "Model overview"),
           ("s3", "3", "Compressible row"), ("s4", "4", "Transonic flow"), ("s5", "5", "High power"),
           ("s6", "6", "Low power"), ("s7", "7", "Boundary layer"), ("s8", "8", "Lifting line and bookkeeping"),
           ("s9", "9", "Numerics"), ("s10", "10", "Inverse design"), ("s11", "11", "Verification"),
           ("s12", "12", "Validation"), ("s13", "13", "Ablation"), ("s14", "14", "Limitations"),
           ("s15", "15", "Using it"), ("refs", "", "References")]
    nav = "".join(f'<li><a href="#{a}"><span>{n}</span><span>{t}</span></a></li>' for a, n, t in toc)
    content = f"""<div class="page">
<header class="masthead">
  <div class="journal"><span>Technical report</span><span>Propeller aerodynamics</span><span>hsprop 0.1.0</span></div>
  <h1>hsprop: performance of very-high-solidity propellers and propfans from take-off to Mach 0.85</h1>
  <p class="byline">Model, code and report by Claude Code (Anthropic), working in the repository
  <a href="{REPO}">ravishkarve/karve99.github.io</a> at the request of its owner.</p>
  <div class="meta"><span><b>Built</b> {date}</span><span><b>Source</b> commit
  <a href="{REPO}/tree/{commit}/propfan">{commit}</a></span><span><b>Validation</b> NASA SR-3 and SR-2, mean error {mae:.1f} points</span></div>
</header>
<div class="layout">
<nav class="toc" aria-label="Contents"><p>Contents</p><ol>{nav}</ol></nav>
<article>{body}</article>
</div>
</div>"""
    return content


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="recompute data/report_extra.json")
    ap.add_argument("--artifact", help="also write the page body (no document wrapper) to this path")
    ap.add_argument("-o", "--output", default=str(ROOT / "report.html"))
    args = ap.parse_args(argv)
    val = json.loads((ROOT / "data" / "validation.json").read_text())
    extra_path = ROOT / "data" / "report_extra.json"
    if args.refresh or not extra_path.exists():
        extra_path.write_text(json.dumps(compute_extra(), default=float))
    ext = json.loads(extra_path.read_text())
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                            text=True).stdout.strip() or "unknown"
    date = datetime.date.today().strftime("%-d %B %Y")
    content = build(val, ext, commit, date)
    title = "hsprop Technical Report"
    head = (f'<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            f'<title>{title}</title>{FONTS}<style>{CSS}</style>')
    page = f'<!doctype html>\n<html lang="en">\n<head>\n{head}\n</head>\n<body>\n{content}\n{MATHJAX}\n</body>\n</html>\n'
    Path(args.output).write_text(page)
    print(f"wrote {args.output} ({len(page) / 1024:.0f} kB)")
    if args.artifact:
        art = (f'<title>{title}</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n{FONTS}\n'
               f'<style>{CSS}</style>\n{content}\n{MATHJAX}\n')
        Path(args.artifact).write_text(art)
        print(f"wrote {args.artifact}")


if __name__ == "__main__":
    main()
