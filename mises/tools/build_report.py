"""Build the pymises technical report (report.html) from the code, data and tests.

Every code reference in the report is resolved here by searching the source
for a pattern, so the cited line numbers always match the commit the report
is built from.  Figures are drawn as inline SVG from the stored data
(data/*.json); the aerofoil check is recomputed at build time.

Usage:  python tools/build_report.py [--fragment OUT]   (writes report.html)
"""
from __future__ import annotations

import html
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
ROOT = Path(__file__).resolve().parents[1]          # .../mises
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

GITHUB = "https://github.com/ravishkarve/karve99.github.io"


def git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


SHA = git("rev-parse", "HEAD")
SHA_SHORT = SHA[:7]

# ---------------------------------------------------------------------------
# code references: key -> (file relative to mises/, start pattern, end pattern)
# ---------------------------------------------------------------------------
REFS = {
    # package set-up
    "init_threads": ("pymises/__init__.py", r"OPENBLAS_NUM_THREADS", None),
    # geometry
    "geo_blade": ("pymises/geometry.py", r"^class Blade", None),
    "geo_post_init": ("pymises/geometry.py", r"    def __post_init__", None),
    "geo_le": ("pymises/geometry.py", r"def leading_edge_arclength", None),
    "geo_repanel": ("pymises/geometry.py", r"def repanel", None),
    "geo_closed_te": ("pymises/geometry.py", r"def closed_te", r"return Blade\(x, y, self.pitch"),
    "geo_from_parameters": ("pymises/geometry.py", r"def from_parameters", None),
    "geo_half_thickness": ("pymises/geometry.py", r"^def half_thickness", None),
    "geo_parse": ("pymises/geometry.py", r"^def parse_airfoil_coordinates", None),
    "geo_normalise": ("pymises/geometry.py", r"^def normalise_airfoil", None),
    "geo_spline_le": ("pymises/geometry.py", r"xl, yl = Blade\(x, y, 1.0\).le_point", None),
    "geo_from_airfoil": ("pymises/geometry.py", r"def from_airfoil", None),
    "geo_from_selig": ("pymises/geometry.py", r"def from_selig", None),
    "geo_to_selig": ("pymises/geometry.py", r"def to_selig", None),
    "geo_read_mises": ("pymises/geometry.py", r"def read_mises", None),
    "geo_axial": ("pymises/geometry.py", r"def axial_surfaces", None),
    # panel method
    "pan_logsinh": ("pymises/panel.py", r"^def _log_sinh_over_w", None),
    "pan_cothinv": ("pymises/panel.py", r"^def _coth_minus_inv", None),
    "pan_iso": ("pymises/panel.py", r"^def _vortex_psi_isolated", None),
    "pan_vcoef": ("pymises/panel.py", r"^def _vortex_psi_coeffs", None),
    "pan_srcvel": ("pymises/panel.py", r"^def _source_velocity", None),
    "pan_selfterm": ("pymises/panel.py", r"b = np.where\(np.abs\(b\) < 1e-12", None),
    "pan_wp": ("pymises/panel.py", r"Wp = np.sum\(W \* wq\[None\], axis=2\)", None),
    "pan_init": ("pymises/panel.py", r"def __init__\(self, blade: Blade\)", None),
    "pan_innerpsi": ("pymises/panel.py", r"def inner_psi", None),
    "pan_tegap": ("pymises/panel.py", r"# ---- trailing-edge gap panel", r"self.h_te, self.te_sds, self.te_scs = h, sds, scs"),
    "pan_assemble": ("pymises/panel.py", r"# ---- assemble and factor the system", r"self.lu = lu_factor\(M\)"),
    "pan_closedrow": ("pymises/panel.py", r"M\[N - 1, \[0, 1, 2\]\]", None),
    "pan_solve": ("pymises/panel.py", r"def solve\(self, inlet_angle_deg", None),
    "pan_package": ("pymises/panel.py", r"def _package", None),
    "pan_stag": ("pymises/panel.py", r"def stagnation_static", None),
    "pan_G": ("pymises/panel.py", r"def mass_defect_operator", None),
    "pan_D": ("pymises/panel.py", r"def ue_sensitivity", None),
    # boundary layer
    "bl_consts": ("pymises/boundary_layer.py", r"^GACON = ", r"^HTMAX"),
    "bl_hkin": ("pymises/boundary_layer.py", r"^def hkin", None),
    "bl_hslam": ("pymises/boundary_layer.py", r"^def hs_lam", None),
    "bl_hsturb": ("pymises/boundary_layer.py", r"^def hs_turb", None),
    "bl_cflam": ("pymises/boundary_layer.py", r"^def cf_lam", None),
    "bl_cfturb": ("pymises/boundary_layer.py", r"^def cf_turb", None),
    "bl_dilam": ("pymises/boundary_layer.py", r"^def di_lam", None),
    "bl_hc": ("pymises/boundary_layer.py", r"^def hc_dens", None),
    "bl_ampl": ("pymises/boundary_layer.py", r"^def ampl_rate", None),
    "bl_env": ("pymises/boundary_layer.py", r"^class BLEnvironment", None),
    "bl_station": ("pymises/boundary_layer.py", r"^def station_vars", None),
    "bl_core": ("pymises/boundary_layer.py", r"^def _interval_core", None),
    "bl_upw": ("pymises/boundary_layer.py", r"upw = 1.0 - 0.5", None),
    "bl_mom": ("pymises/boundary_layer.py", r"rez_t = tlog \+", None),
    "bl_shape": ("pymises/boundary_layer.py", r"rez_h = hlog \+", None),
    "bl_lam": ("pymises/boundary_layer.py", r"rez_lam = s2.A", None),
    "bl_lag": ("pymises/boundary_layer.py", r"rez_turb = \(scc", None),
    "bl_trpoint": ("pymises/boundary_layer.py", r"^def transition_point", None),
    "bl_intres": ("pymises/boundary_layer.py", r"^def interval_residuals", None),
    "bl_split": ("pymises/boundary_layer.py", r"rez_t\[tr\] = lt \+ tt", None),
    "bl_sim": ("pymises/boundary_layer.py", r"^def similarity_residuals", None),
    "bl_surfaces": ("pymises/boundary_layer.py", r"^def build_surfaces", None),
    "bl_stagnode": ("pymises/boundary_layer.py", r"if f < 0.25 and k >= 1:", None),
    "bl_xieff": ("pymises/boundary_layer.py", r"def _xi_eff", None),
    "bl_march": ("pymises/boundary_layer.py", r"def march\(self", None),
    "bl_inverse": ("pymises/boundary_layer.py", r"if allow_inverse and", None),
    "bl_coupled": ("pymises/boundary_layer.py", r"def solve_coupled", None),
    "bl_linesearch": ("pymises/boundary_layer.py", r"# backtracking line search", None),
    "bl_gate": ("pymises/boundary_layer.py", r"if frozen\[si\] or rmax > 2e-3", None),
    "bl_cycle": ("pymises/boundary_layer.py", r"if after in visited\[si\]", None),
    "bl_qs": ("pymises/boundary_layer.py", r"def _qs_sweep", None),
    "bl_assemble": ("pymises/boundary_layer.py", r"def _assemble", None),
    "bl_chain": ("pymises/boundary_layer.py", r"dUdm = dF\[:, None\] \* D", None),
    "bl_relax": ("pymises/boundary_layer.py", r"def _relaxation", None),
    "bl_jac": ("pymises/boundary_layer.py", r"def _residual_jacobian", None),
    "bl_updtr": ("pymises/boundary_layer.py", r"def _update_transition", None),
    "bl_advlam": ("pymises/boundary_layer.py", r"def _advance_laminar", None),
    "bl_remarch": ("pymises/boundary_layer.py", r"# large move: re-march", None),
    "bl_package": ("pymises/boundary_layer.py", r"def package\(self", None),
    "bl_newton": ("pymises/boundary_layer.py", r"^def _newton_bounded", None),
    # coupled solver
    "sol_flow": ("pymises/solver.py", r"^class FlowConditions", None),
    "sol_visc": ("pymises/solver.py", r"^class ViscousOptions", None),
    "sol_class": ("pymises/solver.py", r"^class CascadeSolver", None),
    "sol_kt": ("pymises/solver.py", r"def _compressibility_map", None),
    "sol_panel": ("pymises/solver.py", r"def _solve_panel", None),
    "sol_closedte_call": ("pymises/solver.py", r"blade = self.blade.closed_te\(\).repanel", None),
    "sol_minc": ("pymises/solver.py", r"m_inc = m_c \* ulin / ue_c", None),
    "sol_panel_loss": ("pymises/solver.py", r"loss = cascade_mixed_out_loss\(f.inlet_mach", None),
    "sol_mis_warn": ("pymises/solver.py", r"peak isentropic Mach", None),
    "sol_perf": ("pymises/solver.py", r"def _performance", None),
    "sol_euler": ("pymises/solver.py", r"def _solve_euler", None),
    "sol_cycles": ("pymises/solver.py", r"for cyc in range\(o.coupling_cycles\)", None),
    "sol_freeze": ("pymises/solver.py", r"fix_transition=\(cyc >= 2", None),
    "sol_transp": ("pymises/solver.py", r"es.set_transpiration", None),
    "sol_final": ("pymises/solver.py", r"fin = es.run\(tol=o.tol", None),
    "sol_omegainv": ("pymises/solver.py", r"omega_inv = \(es.mass_averaged_p0", None),
    "sol_dvisc": ("pymises/solver.py", r"d_visc = lv.omega - omega_core_mixed", None),
    "sol_closete": ("pymises/solver.py", r"^def _close_te_bl", None),
    # Euler
    "eu_opts": ("pymises/euler.py", r"^class EulerOptions", None),
    "eu_tol": ("pymises/euler.py", r"    tol: float = ", None),
    "eu_grid": ("pymises/euler.py", r"def for_blade", None),
    "eu_wallcl": ("pymises/euler.py", r"wc = 0.9 if abs\(a1 - a2\)", None),
    "eu_src": ("pymises/euler.py", r"# b-weighted outward face-vector sum", None),
    "eu_init": ("pymises/euler.py", r"def initialise", None),
    "eu_init_bp": ("pymises/euler.py", r"start from a slightly higher back pressure", None),
    "eu_ghosts": ("pymises/euler.py", r"def _ghosts", None),
    "eu_inlet": ("pymises/euler.py", r"# --- inlet \(characteristic\)", None),
    "eu_exit": ("pymises/euler.py", r"# --- exit ---", None),
    "eu_residual": ("pymises/euler.py", r"def residual\(self", None),
    "eu_walldiss": ("pymises/euler.py", r"# dissipation stencils at walls", None),
    "eu_switch": ("pymises/euler.py", r"# shock switch", None),
    "eu_flux": ("pymises/euler.py", r"def _flux", None),
    "eu_transp": ("pymises/euler.py", r"def _transpiration", None),
    "eu_irs": ("pymises/euler.py", r"def _smooth\(self, D\)", None),
    "eu_step": ("pymises/euler.py", r"def step\(self\)", None),
    "eu_positivity": ("pymises/euler.py", r"# positivity safeguard", None),
    "eu_iso": ("pymises/euler.py", r"if self.opts.isoenergetic:", None),
    "eu_run": ("pymises/euler.py", r"def run\(self, max_steps", None),
    "eu_ctrl": ("pymises/euler.py", r"# adaptive gain", None),
    "eu_choke": ("pymises/euler.py", r"self.choked = True", None),
    "eu_masscheck": ("pymises/euler.py", r"if abs\(m_out - m_in\) > o.mass_tol", None),
    "eu_p0avg": ("pymises/euler.py", r"def mass_averaged_p0", None),
    "eu_smoothgrid": ("pymises/euler.py", r"^def _smooth_interior", None),
    "eu_wallcluster": ("pymises/euler.py", r"^def _wall_clustered", None),
    "eu_thomas": ("pymises/euler.py", r"^def _thomas", None),
    # losses and gas
    "lo_mixed": ("pymises/losses.py", r"^def mixed_out", None),
    "lo_quad": ("pymises/losses.py", r"a = mdot \* \(gamma \+ 1.0\)", None),
    "lo_edge": ("pymises/losses.py", r"^def edge_state_for_mass", None),
    "lo_cascade": ("pymises/losses.py", r"^def cascade_mixed_out_loss", None),
    "lo_lieblein": ("pymises/losses.py", r"^def lieblein_loss", None),
    "gas_sutherland": ("pymises/gas.py", r"^def sutherland_ratio", None),
    # configuration, CLI, I/O, web
    "cfg_keys": ("pymises/config.py", r"^GEOMETRY_KEYS", None),
    "cfg_parse": ("pymises/config.py", r"^def parse_config", None),
    "cfg_dataclass": ("pymises/config.py", r"^def _dataclass_from", None),
    "cfg_build_blade": ("pymises/config.py", r"^def build_blade", None),
    "cfg_selig": ("pymises/config.py", r'elif kind == "selig":', None),
    "cfg_build_case": ("pymises/config.py", r"^def build_case", None),
    "cfg_sweep": ("pymises/config.py", r"^def _normalise_sweep", None),
    "cfg_run": ("pymises/config.py", r"^def run_case", None),
    "cli_main": ("pymises/cli.py", r"^def main", None),
    "cli_blade": ("pymises/cli.py", r"^def _cmd_blade", None),
    "io_save": ("pymises/io.py", r"^def save_result", None),
    "io_plot": ("pymises/io.py", r"^def plot_result", None),
    "ex_airfoil": ("pymises/examples.py", r'^AIRFOIL = """', None),
    "web_compact": ("pymises/webapi.py", r"^def compact", None),
    "web_run": ("pymises/webapi.py", r"^def run_config_json", None),
    "web_preview": ("pymises/webapi.py", r"^def blade_preview_json", None),
    "wk_init": ("worker.js", r"async function init", None),
    "wk_fetchcheck": ("worker.js", r"if \(!r.ok\) throw", None),
    "wk_data": ("worker.js", r"const DATA_FILES", None),
    "ix_linechart": ("index.html", r"function lineChart", None),
    "ix_cascade": ("index.html", r"function drawCascade", None),
    "ix_parse": ("index.html", r"function parseAirfoil", None),
    "ix_place": ("index.html", r"function placeAirfoil", None),
    "ix_toml": ("index.html", r"function toTOML", None),
    "ix_startworker": ("index.html", r"function startWorker", None),
    "ix_gooffline": ("index.html", r"function goOffline", None),
    "ix_boot": ("index.html", r"async function boot", None),
    "ix_keys": ("index.html", r"normalise case keys", None),
    "ix_eufam": ("index.html", r"function eulerFamily", None),
    "pre_fam": ("tools/precompute.py", r"^FAMILIES = ", None),
    "pre_euler": ("tools/precompute.py", r"^EULER_CASES", None),
    "pre_panel": ("tools/precompute.py", r"^def run_panel_library", None),
    # verification and tests
    "ver_mms": ("pymises/verification.py", r"^class ManufacturedCascade", None),
    "ver_close": ("pymises/verification.py", r"def _closing_crossflow", None),
    "ver_body": ("pymises/verification.py", r"    def body", None),
    "ver_pm": ("pymises/verification.py", r"^def verify_panel_manufactured", None),
    "ver_conv": ("pymises/verification.py", r"^def verify_panel_convergence", None),
    "ver_jouk": ("pymises/verification.py", r"^def verify_panel_joukowski", None),
    "ver_blas": ("pymises/verification.py", r"^def verify_bl_blasius", None),
    "ver_hiem": ("pymises/verification.py", r"^def verify_bl_hiemenz", None),
    "ver_turb": ("pymises/verification.py", r"^def verify_bl_turbulent", None),
    "ver_tr": ("pymises/verification.py", r"^def verify_bl_transition", None),
    "ver_incloss": ("pymises/verification.py", r"^def incompressible_mixed_out_loss", None),
    "ver_mix": ("pymises/verification.py", r"^def verify_loss_mixing", None),
    "ver_cons": ("pymises/verification.py", r"^def verify_loss_conservation", None),
    "ver_fs": ("pymises/verification.py", r"^def verify_euler_freestream", None),
    "ver_noz": ("pymises/verification.py", r"^def verify_euler_nozzle", None),
    "ver_evp": ("pymises/verification.py", r"^def verify_euler_vs_panel", None),
    "ver_tight": ("pymises/verification.py", r"eo = EulerOptions\(tol=1e-4", None),
    "ver_run": ("pymises/verification.py", r"^def run_all", None),
    "test_conftest": ("tests/conftest.py", r"--runslow", None),
    "test_selig": ("tests/test_airfoil.py", r"def test_coarse_selig_file_solves_like_fine", None),
    "test_lednicer": ("tests/test_airfoil.py", r"def test_lednicer_matches_selig", None),
}

_src_cache = {}


def _lines(path):
    if path not in _src_cache:
        _src_cache[path] = (ROOT / path).read_text().splitlines()
    return _src_cache[path]


def locate(key):
    path, start, end = REFS[key]
    lines = _lines(path)
    rx = re.compile(start)
    hits = [i for i, ln in enumerate(lines) if rx.search(ln)]
    if not hits:
        raise SystemExit(f"reference {key!r}: pattern {start!r} not found in {path}")
    a = hits[0] + 1
    b = None
    if end:
        rxe = re.compile(end)
        after = [i for i, ln in enumerate(lines) if i >= a - 1 and rxe.search(ln)]
        if not after:
            raise SystemExit(f"reference {key!r}: end pattern {end!r} not found in {path}")
        b = after[0] + 1
    return path, a, b


USED = {}


def ref_html(key):
    path, a, b = locate(key)
    USED[key] = (path, a, b)
    anchor = f"#L{a}" + (f"-L{b}" if b else "")
    url = f"{GITHUB}/blob/{SHA}/mises/{path}{anchor}"
    name = Path(path).name
    label = f"{name}:{a}" + (f"–{b}" if b else "")
    return f'<a class="loc" href="{url}" title="mises/{path}, commit {SHA_SHORT}">{label}</a>'


# ---------------------------------------------------------------------------
# SVG charts
# ---------------------------------------------------------------------------

def nice_ticks(lo, hi, n=5):
    if not math.isfinite(lo) or not math.isfinite(hi):
        return [0.0, 1.0], 1.0
    if hi - lo <= 0:
        d = abs(hi) * 0.1 or 1.0
        lo, hi = lo - d, hi + d
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        step = m * mag
        if (hi - lo) / step <= n:
            break
    t0 = math.floor(lo / step + 1e-9) * step
    ticks = []
    t = t0
    while t <= hi + 1e-9 * step:
        ticks.append(round(t, 12))
        t += step
    if ticks[-1] < hi - 1e-9 * step:
        ticks.append(round(t, 12))
    return ticks, step


def fmt_tick(v, step):
    if step >= 1:
        return f"{v:.0f}"
    d = max(0, min(6, -math.floor(math.log10(step) + 1e-9)))
    if abs(step * 10 ** d - round(step * 10 ** d)) > 1e-6:
        d += 1
    return f"{v:.{d}f}".replace("-", "−")


def chart(series, xlabel, ylabel, *, xlim=None, ylim=None, logx=False, logy=False, w=680,
          h=280, aria="", ref_line=None, max_hits=160, xticks=None, yzero=False):
    """series: list of dict(name, x, y, cls in s1|s2|s3|ink, dash, markers, width)."""
    xs, ys = [], []
    for s in series:
        for x, y in zip(s["x"], s["y"]):
            if x is None or y is None or not (math.isfinite(x) and math.isfinite(y)):
                continue
            if (logx and x <= 0) or (logy and y <= 0):
                continue
            xs.append(x)
            ys.append(y)
    tx = (lambda v: math.log10(v)) if logx else (lambda v: v)
    ty = (lambda v: math.log10(v)) if logy else (lambda v: v)

    def axis(vals, lim, log, custom=None, zero=False):
        if log and custom:
            lo, hi = math.log10(lim[0]), math.log10(lim[1])
            return [math.log10(t) for t in custom], (lo, hi), [f"{t:g}" for t in custom]
        if log:
            lo = math.floor(math.log10(min(vals)) + 1e-9) if lim is None else math.log10(lim[0])
            hi = math.ceil(math.log10(max(vals)) - 1e-9) if lim is None else math.log10(lim[1])
            if hi == lo:
                hi += 1
            ticks = list(range(int(lo), int(hi) + 1))
            return ticks, (lo, hi), [f"10{sup(t)}" for t in ticks]
        lo, hi = (min(vals), max(vals)) if lim is None else lim
        if lim is None:
            pad = 0.04 * (hi - lo or abs(hi) or 1.0)
            lo, hi = (0.0 if zero else lo - pad), hi + pad
        ticks, step = nice_ticks(lo, hi)
        if lim is None:
            lo, hi = ticks[0], ticks[-1]
        ticks = [t for t in ticks if lo - 1e-9 * step <= t <= hi + 1e-9 * step]
        return ticks, (lo, hi), [fmt_tick(t, step) for t in ticks]

    xt, (x0, x1), xl = axis(xs, xlim, logx, xticks)
    yt, (y0, y1), yl = axis(ys, ylim, logy, None, yzero)
    ml = 22 + 7.0 * max(len(s) for s in yl) + 8
    mr, mt, mb = 26, 10, 42

    def X(v):
        return ml + (tx(v) - x0) / (x1 - x0) * (w - ml - mr)

    def Y(v):
        return h - mb - (ty(v) - y0) / (y1 - y0) * (h - mt - mb)

    def Xt(t):
        return ml + (t - x0) / (x1 - x0) * (w - ml - mr)

    def Yt(t):
        return h - mb - (t - y0) / (y1 - y0) * (h - mt - mb)

    cid = f"clip{abs(hash((xlabel, ylabel, aria, len(xs)))) % 10 ** 8}"
    out = [f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(aria)}">',
           f'<defs><clipPath id="{cid}"><rect x="{ml}" y="{mt - 4}" width="{w - ml - mr}" '
           f'height="{h - mt - mb + 8}"/></clipPath></defs>']
    for t, lab in zip(yt, yl):
        y = Yt(t)
        out.append(f'<line class="grid" x1="{ml}" x2="{w - mr}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text class="tick" x="{ml - 7}" y="{y + 4:.1f}" text-anchor="end">{lab}</text>')
    for t, lab in zip(xt, xl):
        x = Xt(t)
        out.append(f'<text class="tick" x="{x:.1f}" y="{h - mb + 17}" text-anchor="middle">{lab}</text>')
    out.append(f'<line class="axis" x1="{ml}" x2="{w - mr}" y1="{h - mb}" y2="{h - mb}"/>')
    out.append(f'<text class="axlab" x="{(ml + w - mr) / 2:.1f}" y="{h - 6}" text-anchor="middle">'
               f'{xlabel}</text>')
    yc = (mt + h - mb) / 2
    if len(re.sub(r"<[^>]+>", "", ylabel)) <= 2:          # short symbols read better upright
        out.append(f'<text class="axlab" x="12" y="{yc:.1f}" text-anchor="middle">{ylabel}</text>')
    else:
        out.append(f'<text class="axlab" x="13" y="{yc:.1f}" text-anchor="middle" '
                   f'transform="rotate(-90 13 {yc:.1f})">{ylabel}</text>')
    g = [f'<g clip-path="url(#{cid})">']
    if ref_line:
        (ax_, ay_), (bx_, by_) = ref_line
        g.append(f'<line class="ln ref" x1="{X(ax_):.1f}" y1="{Y(ay_):.1f}" x2="{X(bx_):.1f}" '
                 f'y2="{Y(by_):.1f}"/>')
    hits = []
    for s in series:
        pts = []
        segs = []
        for x, y in zip(s["x"], s["y"]):
            ok = (x is not None and y is not None and math.isfinite(x) and math.isfinite(y)
                  and not (logx and x <= 0) and not (logy and y <= 0))
            if not ok:
                if pts:
                    segs.append(pts)
                pts = []
                continue
            pts.append((X(x), Y(y), x, y))
        if pts:
            segs.append(pts)
        cls = s.get("cls", "s1")
        extra = ' stroke-dasharray="6 4"' if s.get("dash") else ""
        wdt = s.get("width", 2)
        for seg in segs:
            if s.get("line", True) and len(seg) > 1:
                d = "M" + " L".join(f"{p[0]:.1f} {p[1]:.1f}" for p in seg)
                g.append(f'<path class="ln {cls}" d="{d}" stroke-width="{wdt}"{extra}/>')
            if s.get("markers"):
                for p in seg:
                    g.append(f'<circle class="mk {cls}" cx="{p[0]:.1f}" cy="{p[1]:.1f}" r="4"/>')
        allp = [p for seg in segs for p in seg]
        stride = max(1, len(allp) // max_hits)
        for p in allp[::stride]:
            hits.append(f'<circle class="hit" cx="{p[0]:.1f}" cy="{p[1]:.1f}" r="6"><title>'
                        f'{html.escape(s["name"])}: {g3(p[2])}, {g3(p[3])}</title></circle>')
    g.append("</g>")
    out += g + hits + ["</svg>"]
    return "".join(out)


def sup(n):
    table = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")
    return str(n).translate(table)


def g3(v):
    if v == 0:
        return "0"
    if abs(v) >= 1e4 or abs(v) < 1e-3:
        return f"{v:.3e}"
    return f"{v:.4g}"


def legend(series, extra=None):
    items = []
    for s in series:
        cls = s.get("cls", "s1")
        kind = "dash" if s.get("dash") else ("dot" if s.get("markers") and not s.get("line", True) else "")
        items.append(f'<span><i class="sw {cls} {kind}"></i>{html.escape(s["name"])}</span>')
    if extra:
        items += extra
    return f'<div class="legend">{"".join(items)}</div>'


def figure(fid, caption, body):
    return (f'<figure id="{fid}">{body}<figcaption><b>Figure {FIGNUM[fid]}.</b> {caption}'
            f'</figcaption></figure>')


FIGNUM = {}


def fig_id(fid):
    FIGNUM.setdefault(fid, len(FIGNUM) + 1)
    return fid


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

def load(name):
    return json.loads((ROOT / "data" / name).read_text())


VER = {c["name"]: c for c in load("verification.json")}
EUL = {c["id"]: c for c in load("euler.json")}
LIB = load("library.json")
for fam in LIB.values():
    fam["cases"] = {"|".join(str(float(t)) for t in k.split("|")): v for k, v in fam["cases"].items()}


def libcase(fam, beta, mach, re_):
    return LIB[fam]["cases"].get(f"{float(beta)}|{float(mach)}|{float(re_)}")


def unconverged(c):
    return any("did not fully converge" in w for w in c.get("warnings", []))


def sorted_xy(xc, y):
    o = sorted(range(len(xc)), key=lambda i: xc[i])
    return [xc[i] for i in o], [y[i] for i in o]


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------

def fig_architecture():
    fid = fig_id("fig-arch")
    W, H = 840, 300

    def box(x, y, w, h, title, sub="", cls="bx"):
        s = f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="5"/>'
        if sub:
            s += (f'<text class="bt" x="{x + w / 2}" y="{y + h / 2 - 3}" text-anchor="middle">{title}</text>'
                  f'<text class="bs" x="{x + w / 2}" y="{y + h / 2 + 12}" text-anchor="middle">{sub}</text>')
        else:
            s += f'<text class="bt" x="{x + w / 2}" y="{y + h / 2 + 4}" text-anchor="middle">{title}</text>'
        return s

    def arrow(x1, y1, x2, y2, both=False):
        m = ' marker-start="url(#ah)"' if both else ""
        return f'<line class="ar" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" marker-end="url(#ah)"{m}/>'

    p = [f'<svg class="diagram" viewBox="0 0 {W} {H}" role="img" aria-label="pymises module structure">',
         '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
         'orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" class="ahd"/></marker></defs>']
    p.append('<text class="lane" x="10" y="16">Inputs</text>')
    ins = [("Config file", "TOML · JSON · YAML"), ("MISES blade.xxx", ""), ("Selig / Lednicer .dat", ""),
           ("Python API", "Blade, CascadeSolver")]
    for i, (t, s) in enumerate(ins):
        p.append(box(10, 28 + i * 66, 170, 50, t, s, "bx in"))
    p.append('<text class="lane" x="215" y="16">Set-up</text>')
    p.append(box(215, 50, 150, 56, "config.py", "build_case, sweeps"))
    p.append(box(215, 170, 150, 56, "geometry.py", "Blade, repanelling"))
    p.append('<text class="lane" x="400" y="16">solver.py · CascadeSolver</text>')
    p.append('<rect class="grp" x="400" y="24" width="250" height="268" rx="7"/>')
    p.append(box(415, 36, 105, 56, "panel.py", "panel + K–T"))
    p.append(box(530, 36, 105, 56, "euler.py", "FV Euler, H-grid"))
    p.append(box(415, 132, 220, 56, "boundary_layer.py", "integral BL, eᴺ, Newton coupling"))
    p.append(box(415, 226, 220, 52, "losses.py", "mixed-out loss"))
    p.append(arrow(467, 92, 467, 132, both=True))
    p.append(arrow(582, 92, 582, 132, both=True))
    p.append('<text class="bs" x="474" y="116">uₑ, D ↔ m</text>')
    p.append('<text class="bs" x="589" y="116">q, D ↔ m</text>')
    p.append(arrow(525, 188, 525, 226))
    p.append('<text class="lane" x="690" y="16">Outputs</text>')
    outs = [("io.py", "JSON · CSV · plots"), ("cli.py", "run · verify · blade"),
            ("webapi.py", "JSON for the browser"), ("worker.js", "Pyodide + dashboard")]
    for i, (t, s) in enumerate(outs):
        p.append(box(690, 28 + i * 66, 140, 50, t, s, "bx out"))
    for i in range(4):
        p.append(arrow(180, 53 + i * 66, 215, 78 if i == 0 else 198))
    p.append(arrow(290, 106, 290, 170))
    p.append(arrow(365, 198, 400, 160))
    p.append(arrow(365, 78, 400, 64))
    for i in range(4):
        p.append(arrow(650, 158, 690, 53 + i * 66))
    p.append("</svg>")
    cap = ("Module structure of pymises and the flow of data through one analysis. "
           "Arrows between the inviscid solvers and the boundary layer carry the edge velocity "
           "and interaction matrix in one direction and the mass defect in the other.")
    return figure(fid, cap, f'<div class="scroll">{"".join(p)}</div>')


def fig_manufactured():
    fid = fig_id("fig-mms")
    P = VER["panel_manufactured"]["plot"]
    n = list(range(len(P["q"])))
    ser = [{"name": "exact", "x": n, "y": P["q_exact"], "cls": "s3", "width": 4},
           {"name": "panel method, 240 panels", "x": n, "y": P["q"], "cls": "s1", "dash": True}]
    body = legend(ser) + chart(ser, "node index (TE → upper surface → LE → lower surface → TE)",
                               "q / V₁", aria="Manufactured cascade surface speed")
    d = VER["panel_manufactured"]["details"]
    cap = (f"Surface speed on the manufactured cascade, exact against computed. The maximum "
           f"error is {VER['panel_manufactured']['value'] * 100:.2f} % of V₁, the RMS error "
           f"{d['rms_error'] * 100:.3f} %, and the exit angle differs by "
           f"{d['exit_angle_error_deg']:.4f}°. Source: {ref_html('ver_pm')}.")
    return figure(fid, cap, body)


def fig_convergence():
    fid = fig_id("fig-conv")
    P = VER["panel_convergence"]["plot"]
    ns, es = P["n"], P["rms_error"]
    ser = [{"name": "RMS error of q / V₁", "x": ns, "y": es, "cls": "s1", "markers": True}]
    a = (ns[-1], es[-1])
    b = (ns[0], es[-1] * (ns[-1] / ns[0]) ** 2)
    body = legend(ser, ['<span><i class="sw ref dash"></i>second order (slope −2)</span>']) + chart(
        ser, "number of panels", "RMS error", logx=True, logy=True, xlim=(45, 320),
        xticks=ns, ref_line=(b, a), aria="Panel method grid convergence", h=260)
    orders = VER["panel_convergence"]["details"]["orders"]
    cap = (f"Grid convergence of the panel method on the manufactured cascade. The observed "
           f"orders between successive grids are {orders[0]:.2f} and {orders[1]:.2f}. "
           f"Source: {ref_html('ver_conv')}.")
    return figure(fid, cap, body)


def fig_bl():
    fid = fig_id("fig-bl")
    P = VER["bl_blasius"]["plot"]
    s1 = [{"name": "Blasius", "x": P["x"], "y": P["theta_exact"], "cls": "s3", "width": 4},
          {"name": "pymises", "x": P["x"], "y": P["theta"], "cls": "s1", "dash": True}]
    T = VER["bl_turbulent_flatplate"]["plot"]
    s2 = [{"name": "Coles–Fernholz", "x": T["re_theta"], "y": T["cf_ref"], "cls": "s3", "width": 4},
          {"name": "pymises", "x": T["re_theta"], "y": T["cf"], "cls": "s1", "dash": True}]
    body = ('<div class="pair"><div>' + '<p class="sub">(a) Laminar flat plate, Re = 10⁶</p>'
            + legend(s1) + chart(s1, "x / L", "θ / L", aria="Blasius momentum thickness", w=420, h=250, xlim=(0, 1), yzero=True)
            + '</div><div><p class="sub">(b) Turbulent flat plate</p>' + legend(s2)
            + chart(s2, 'Re<tspan baseline-shift="sub" font-size="75%">θ</tspan>', 'C<tspan baseline-shift="sub" font-size="75%">f</tspan>', aria="Turbulent skin friction", w=420, h=250) + "</div></div>")
    cap = (f"Boundary-layer verification on flat plates. (a) Momentum thickness against the "
           f"Blasius solution (largest relative error in θ, C<sub>f</sub> and H: "
           f"{VER['bl_blasius']['value'] * 100:.2f} %). (b) Skin friction against the "
           f"Coles–Fernholz relation (largest error {VER['bl_turbulent_flatplate']['value'] * 100:.1f} %). "
           f"Sources: {ref_html('ver_blas')}, {ref_html('ver_turb')}.")
    return figure(fid, cap, body)


def fig_nozzle():
    fid = fig_id("fig-noz")
    P = VER["euler_nozzle_shock"]["plot"]
    ser = [{"name": "exact quasi-1-D", "x": P["x"], "y": P["p_exact"], "cls": "s3", "width": 4},
           {"name": "2-D Euler, 150 cells", "x": P["x"], "y": P["p"], "cls": "s1", "dash": True}]
    d = VER["euler_nozzle_shock"]["details"]
    body = legend(ser) + chart(ser, "x", "p / p₀", aria="Laval nozzle pressure", w=680, h=260)
    cap = (f"Static pressure in a Laval nozzle with a normal shock, computed with the Euler solver "
           f"through its streamtube-thickness term. Exact shock position x = {d['x_shock_exact']:.4f}, "
           f"computed {d['x_shock_euler']:.4f}; total-pressure ratio exact "
           f"{d['p0_ratio_exact']:.4f}, computed {d['p0_ratio_euler']:.4f}. "
           f"Source: {ref_html('ver_noz')}.")
    return figure(fid, cap, body)


def fig_euler_vs_panel():
    fid = fig_id("fig-evp")
    P = VER["euler_vs_panel"]["plot"]
    ser = []
    for side, cls in (("upper", "s1"), ("lower", "s2")):
        x, y = sorted_xy(P[f"xc_{side}_euler"], P[f"mis_{side}_euler"])
        ser.append({"name": f"Euler, {'suction' if side == 'upper' else 'pressure'} side", "x": x, "y": y,
                    "cls": cls})
    for side in ("upper", "lower"):
        x, y = sorted_xy(P[f"xc_{side}_panel"], P[f"mis_{side}_panel"])
        ser.append({"name": f"panel, {'suction' if side == 'upper' else 'pressure'} side", "x": x, "y": y,
                    "cls": "ink", "dash": True, "width": 1.5})
    body = legend(ser[:3]) + chart(ser, "x / c", "isentropic Mach number", xlim=(0, 1),
                                   aria="Euler against panel at Mach 0.2", h=270, yzero=True)
    d = VER["euler_vs_panel"]["details"]
    cap = (f"Inviscid surface Mach number at M₁ = 0.2 from the two independent inviscid solvers "
           f"(C4 compressor cascade, β₁ = 43°). RMS difference "
           f"{VER['euler_vs_panel']['value'] * 100:.2f} % of the mean, exit-angle difference "
           f"{d['exit_angle_difference_deg']:.3f}°, spurious Euler loss "
           f"{d['euler_numerical_loss'] * 100:.2f} % of the inlet dynamic head. "
           f"Dashed lines: panel method. Source: {ref_html('ver_evp')}.")
    return figure(fid, cap, body)


def fig_bucket():
    fid = fig_id("fig-bucket")
    fam = LIB["compressor"]
    betas = fam["grid"]["inlet_angle"]
    res = fam["grid"]["reynolds"]
    cls = ["s1", "s2", "s3"]
    labels = {250000.0: "Re = 2.5 × 10⁵", 500000.0: "Re = 5 × 10⁵", 1000000.0: "Re = 10⁶"}
    s_loss, s_xtr = [], []
    for r, c in zip(res, cls):
        xs, ys, xt = [], [], []
        for b in betas:
            case = libcase("compressor", b, 0.5, r)
            ok = case and "error" not in case and not unconverged(case)
            xs.append(b)
            ys.append(case["perf"]["omega"] if ok else None)
            xt.append(case["bl"]["upper"]["xtr"] if ok and case.get("bl") else None)
        s_loss.append({"name": labels[float(r)], "x": xs, "y": ys, "cls": c, "markers": True})
        s_xtr.append({"name": labels[float(r)], "x": xs, "y": xt, "cls": c, "markers": True})
    body = ('<div class="pair"><div><p class="sub">(a) Mixed-out loss ω</p>'
            + chart(s_loss, "inlet flow angle β₁ [deg]", "ω", aria="Loss bucket", w=420, h=260,
                    ylim=(0, 0.025))
            + '</div><div><p class="sub">(b) Suction-side transition</p>'
            + chart(s_xtr, "inlet flow angle β₁ [deg]", 'x<tspan baseline-shift="sub" font-size="75%">tr</tspan> / c', aria="Suction-side transition",
                    w=420, h=260, ylim=(0, 1))
            + "</div></div>" + legend(s_loss))
    cap = ("Incidence characteristics of the C4 compressor cascade (45°/15° metal angles, "
           "s/c = 0.9, 8 % thickness) at M₁ = 0.5 from the precomputed library "
           f"({ref_html('pre_fam')}). Points where the boundary-layer Newton iteration did not "
           "fully converge are left out. Loss falls with Reynolds number, and transition moves "
           "forward as incidence rises.")
    return figure(fid, cap, body)


def fig_viscous_euler():
    fid = fig_id("fig-visc")
    E = EUL["euler_m05"]
    pc = libcase("compressor", 43, 0.5, 5e5)
    ser = [{"name": "viscous Euler, suction", "x": E["surf"]["upper"]["xc"], "y": E["surf"]["upper"]["mis"], "cls": "s1"},
           {"name": "viscous Euler, pressure", "x": E["surf"]["lower"]["xc"], "y": E["surf"]["lower"]["mis"], "cls": "s2"},
           {"name": "panel + K–T, viscous", "x": pc["surf"]["upper"]["xc"], "y": pc["surf"]["upper"]["mis"], "cls": "ink", "dash": True, "width": 1.5},
           {"name": "panel + K–T (pressure)", "x": pc["surf"]["lower"]["xc"], "y": pc["surf"]["lower"]["mis"], "cls": "ink", "dash": True, "width": 1.5}]
    body = legend(ser[:3]) + chart(ser, "x / c", "isentropic Mach number", xlim=(0, 1),
                                   aria="Viscous Euler against panel at Mach 0.5", h=270, yzero=True)
    cap = (f"Viscous solutions at M₁ = 0.5, β₁ = 43°, Re = 5 × 10⁵ from both inviscid solvers. "
           f"Loss ω = {E['perf']['omega']:.4f} (Euler) and {pc['perf']['omega']:.4f} (panel); exit angle "
           f"{E['perf']['beta2']:.2f}° and {pc['perf']['beta2']:.2f}°. The dip at the trailing edge in the "
           f"Euler curve comes from the sharpened trailing edge of the H-grid ({ref_html('geo_axial')}).")
    return figure(fid, cap, body)


def compute_selig():
    from pymises import Blade, CascadeSolver, FlowConditions
    fl = FlowConditions(inlet_mach=0.3, inlet_angle=40.0, reynolds=5e5)
    out = {}
    for tag, npts in (("coarse", 35), ("fine", 241)):
        text = Blade.naca4("4412", pitch=1.0, n_points=npts).to_selig()
        b = Blade.from_selig(text, stagger=30.0, solidity=1.2)
        r = CascadeSolver(b, fl).solve()
        out[tag] = {"n": len(text.strip().splitlines()) - 1, "omega": r.performance["omega"],
                    "beta2": r.performance["beta2"], "xtr_u": r.performance["xtr_upper"],
                    "xtr_l": r.performance["xtr_lower"], "upper": (list(r.upper.xc), list(r.upper.mis)),
                    "lower": (list(r.lower.xc), list(r.lower.mis)), "warnings": r.warnings,
                    "stagger": b.stagger, "chord": b.chord, "tc": b.max_thickness}
    return out


def fig_selig(S):
    fid = fig_id("fig-selig")
    c, f = S["coarse"], S["fine"]
    ser = [{"name": f"{c['n']}-point file, suction", "x": sorted_xy(*c["upper"])[0], "y": sorted_xy(*c["upper"])[1], "cls": "s1"},
           {"name": f"{c['n']}-point file, pressure", "x": sorted_xy(*c["lower"])[0], "y": sorted_xy(*c["lower"])[1], "cls": "s2"},
           {"name": f"{f['n']}-point file", "x": sorted_xy(*f["upper"])[0], "y": sorted_xy(*f["upper"])[1], "cls": "ink", "dash": True, "width": 1.5},
           {"name": f"{f['n']}-point file (pressure)", "x": sorted_xy(*f["lower"])[0], "y": sorted_xy(*f["lower"])[1], "cls": "ink", "dash": True, "width": 1.5}]
    body = legend(ser[:3]) + chart(ser, "x / c", "isentropic Mach number", xlim=(0, 1),
                                   aria="Selig aerofoil cascade", h=260, yzero=True)
    cap = ("NACA 4412 cascade built from Selig coordinates (stagger 30°, solidity 1.2, "
           "M₁ = 0.3, β₁ = 40°, Re = 5 × 10⁵): a coarse file like a typical database entry against "
           f"a fine one. Recomputed when this report was built; see {ref_html('test_selig')} for "
           "the matching unit test.")
    return figure(fid, cap, body)


# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------

VER_ORDER = [("panel_manufactured", "ver_pm", "Exact periodic potential flow (manufactured)"),
             ("panel_convergence", "ver_conv", "Richardson analysis on the manufactured case"),
             ("panel_isolated_joukowski", "ver_jouk", "Exact Joukowski aerofoil, pitch 10⁴ c"),
             ("bl_blasius", "ver_blas", "Blasius flat plate"),
             ("bl_hiemenz", "ver_hiem", "Hiemenz stagnation flow"),
             ("bl_turbulent_flatplate", "ver_turb", "Coles–Fernholz skin friction"),
             ("bl_transition_michel", "ver_tr", "Michel transition criterion (validation)"),
             ("loss_mixing", "ver_mix", "Exact incompressible mixing analysis"),
             ("loss_conservation", "ver_cons", "Conservation of mass, momentum, energy"),
             ("euler_freestream", "ver_fs", "Free-stream preservation, skewed grid"),
             ("euler_nozzle_shock", "ver_noz", "Quasi-1-D Laval nozzle with a normal shock"),
             ("euler_vs_panel", "ver_evp", "Panel method at M₁ = 0.2 (code to code)")]


def sci(v):
    if v == 0:
        return "0"
    e = int(math.floor(math.log10(abs(v))))
    m = v / 10 ** e
    return f"{m:.2f} × 10{sup(e)}"


def table_verification():
    rows = []
    for name, key, refd in VER_ORDER:
        c = VER[name]
        tol = sci(c["tolerance"]) + (" (minimum)" if name == "panel_convergence" else "")
        rows.append(f"<tr><td><code>{name}</code><br><span class='muted'>{ref_html(key)}</span></td>"
                    f"<td>{refd}</td><td>{html.escape(c['metric'])}</td><td class='num'>{sci(c['value'])}</td>"
                    f"<td class='num'>{tol}</td><td>{'pass' if c['passed'] else 'FAIL'}</td></tr>")
    n = sum(VER[k]["passed"] for k, _, _ in VER_ORDER)
    return (f'<div class="scroll"><table><caption><b>Table 2.</b> Verification suite '
            f'({ref_html("ver_run")}); {n} of {len(VER_ORDER)} cases pass.</caption>'
            "<thead><tr><th>Case</th><th>Reference</th><th>Metric</th><th>Value</th><th>Tolerance</th>"
            "<th>Result</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


def module_rows():
    desc = {
        "geometry.py": "Blade sections: conventions, parametric generator, repanelling, TE closure, MISES and Selig I/O",
        "panel.py": "Periodic linear-vorticity panel method, source panels, interaction matrix",
        "boundary_layer.py": "Closures, discrete integral equations, transition, march and coupled Newton",
        "solver.py": "CascadeSolver: panel and Euler paths, Karman–Tsien map, performance",
        "euler.py": "Finite-volume Euler solver on a periodic H-grid with transpiration",
        "losses.py": "Mixed-out control-volume analysis",
        "gas.py": "Isentropic relations, Sutherland law, normal shock",
        "config.py": "TOML / JSON / YAML configuration, validation, sweeps",
        "verification.py": "Twelve verification cases and the report writer",
        "io.py": "JSON, CSV and matplotlib output",
        "cli.py": "Command line: run, verify, blade, example",
        "examples.py": "Example configurations and data files",
        "webapi.py": "JSON interface used by the browser worker",
    }
    rows = []
    total = 0
    for f, d in desc.items():
        n = len((ROOT / "pymises" / f).read_text().splitlines())
        total += n
        rows.append(f"<tr><td><code>{f}</code></td><td class='num'>{n}</td><td>{d}</td></tr>")
    return rows, total


def table_modules():
    rows, total = module_rows()
    return ('<div class="scroll"><table><caption><b>Table 1.</b> Modules of the <code>pymises</code> '
            f'package ({total:,} lines including docstrings).</caption><thead><tr><th>Module</th><th>Lines</th>'
            "<th>Content</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


def library_stats():
    out = {}
    for fid, fam in LIB.items():
        cs = list(fam["cases"].values())
        ok = [c for c in cs if "error" not in c]
        unc = sum(unconverged(c) for c in ok)
        kt = sum(any("Karman" in w for w in c.get("warnings", [])) for c in ok)
        its = sorted(c["convergence"]["bl_iterations"] for c in ok if "bl_iterations" in c["convergence"])
        secs = sorted(c["convergence"]["seconds"] for c in ok)
        out[fid] = dict(n=len(cs), err=len(cs) - len(ok), unc=unc, kt=kt, it_med=its[len(its) // 2],
                        it_max=its[-1], s_med=secs[len(secs) // 2], s_max=secs[-1], name=fam["name"])
    return out


def table_library(st):
    rows = []
    for fid, s in st.items():
        rows.append(f"<tr><td>{html.escape(s['name'])}</td><td class='num'>{s['n']}</td>"
                    f"<td class='num'>{s['n'] - s['err'] - s['unc']}</td><td class='num'>{s['unc']}</td>"
                    f"<td class='num'>{s['kt']}</td><td class='num'>{s['it_med']} / {s['it_max']}</td>"
                    f"<td class='num'>{s['s_med']:.1f} / {s['s_max']:.1f}</td></tr>")
    return ('<div class="scroll"><table><caption><b>Table 3.</b> Precomputed panel-method library '
            f'({ref_html("pre_panel")}). Iterations are global boundary-layer Newton iterations; '
            'times are wall-clock seconds per case with four worker processes.</caption>'
            "<thead><tr><th>Family</th><th>Cases</th><th>Converged</th><th>Not fully converged</th>"
            "<th>Peak M<sub>is</sub> &gt; 1</th><th>Iterations, median / max</th><th>Seconds, median / max</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


def table_euler():
    rows = []
    import math as _m
    from pymises.losses import uniform_state
    for cid in ("euler_m05", "euler_m065", "euler_m072_inv", "euler_turbine"):
        c = EUL[cid]
        p, cv = c["perf"], c["convergence"]
        visc = "dstar_te" in p
        inj = "–"
        if visc:
            rho1, V1, _, _ = uniform_state(p["M1_actual"], p["beta1"])
            md = rho1 * V1 * _m.cos(_m.radians(p["beta1"])) * c["blade"]["pitch"]
            rho2, V2, _, _ = uniform_state(p["M2"], p["beta2"])
            inj = f"{rho2 * V2 * p['dstar_te'] / md * 100:.1f} %"
        final = cv.get("euler_final_steps")
        rows.append(
            f"<tr><td>{html.escape(c['title'])}</td><td class='num'>{p['omega']:.4f}</td>"
            f"<td class='num'>{p['omega_inviscid']:.4f}</td><td class='num'>{p['omega_viscous']:.4f}</td>"
            f"<td class='num'>{p['beta2']:.2f}</td><td class='num'>{cv['euler_steps']}"
            f"{' + ' + str(final) if final else ''}</td>"
            f"<td class='num'>{cv['mass_imbalance'] * 100:.2f} %</td><td class='num'>{inj}</td>"
            f"<td class='num'>{c['seconds']:.0f}</td></tr>")
    return ('<div class="scroll"><table><caption><b>Table 4.</b> Stored Euler solutions '
            f'({ref_html("pre_euler")}). Steps are the initial run plus the final pass after '
            'coupling. The last two columns compare the stored inlet-to-exit mass difference with '
            'an estimate of the displacement mass injected by transpiration, ρ₂V₂δ*/ṁ.</caption>'
            "<thead><tr><th>Case</th><th>ω</th><th>ω inviscid</th><th>ω viscous</th><th>β₂ [°]</th>"
            "<th>Euler steps</th><th>Mass difference</th><th>Injected mass (est.)</th><th>Seconds</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


def table_selig(S):
    c, f = S["coarse"], S["fine"]
    rows = []
    for lab, k, fm in (("Points in the file", "n", "{:d}"), ("Chord after placement", "chord", "{:.4f}"),
                       ("Stagger after placement [°]", "stagger", "{:.3f}"), ("Maximum t/c", "tc", "{:.4f}"),
                       ("Loss ω", "omega", "{:.5f}"), ("Exit angle β₂ [°]", "beta2", "{:.3f}"),
                       ("Transition, suction x/c", "xtr_u", "{:.3f}"), ("Transition, pressure x/c", "xtr_l", "{:.3f}")):
        rows.append(f"<tr><td>{lab}</td><td class='num'>{fm.format(c[k])}</td><td class='num'>{fm.format(f[k])}</td></tr>")
    return ('<div class="scroll"><table><caption><b>Table 5.</b> The same NACA 4412 cascade from a '
            'coarse and a fine Selig file.</caption><thead><tr><th>Quantity</th><th>Coarse file</th>'
            "<th>Fine file</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


DEVLOG = [
    ("Panel method", "Surface speed reached 2.6 V₁ at a blunt trailing edge.",
     "Added the XFOIL trailing-edge gap panel; the remaining oscillation was removed by closing blunt trailing edges geometrically and keeping the thickness as base blockage in the loss.",
     ["pan_tegap", "geo_closed_te", "lo_cascade"]),
    ("Panel method", "A leading-edge suction peak looked suspicious.",
     "The manufactured solution showed it is physical; no change was needed.", ["ver_mms"]),
    ("Panel method", "The periodic part of the source-panel velocity was wrong by a factor of panel length.",
     "Corrected the quadrature sum of the smooth remainder.", ["pan_wp"]),
    ("Panel method", "The self-induced normal velocity of a source panel flipped sign with round-off.",
     "Forced the local normal coordinate to +0 on the panel so arctan2 always takes the inner side.", ["pan_selfterm"]),
    ("Boundary layer", "The station march converged to the lower H<sub>k</sub> limit.",
     "Replaced it by a bounded Newton iteration on (A, θ, H<sub>k</sub>) with an inverse (prescribed H<sub>k</sub>) fallback.", ["bl_newton", "bl_inverse"]),
    ("Coupling", "The global Newton iteration diverged near the stagnation point, where u<sub>e</sub> ≈ 0.",
     "A stagnation node without a boundary-layer station is used when the stagnation point lies close to a node.", ["bl_stagnode"]),
    ("Coupling", "The pressure form of the Karman–Tsien rule was clipped at high speed and broke the Jacobian.",
     "Switched to the smooth hodograph velocity form and its analytic derivative.", ["sol_kt", "bl_chain"]),
    ("Coupling", "Rows of the interaction matrix at a closed trailing edge were ill-conditioned.",
     "Dropped the trailing-edge nodes from the unknowns and folded their columns into the neighbours.", ["sol_closete"]),
    ("Coupling", "Transition jumped back and forth between two stations.",
     "Recorded visited locations and froze transition on a repeat.", ["bl_cycle"]),
    ("Coupling", "Separation bubbles and the transition station were inconsistent.",
     "The transition interval is split at the interpolated transition point into laminar and turbulent parts.", ["bl_trpoint", "bl_split"]),
    ("Coupling", "Poor initial guesses from the uncoupled march.",
     "Two quasi-simultaneous (Veldman) sweeps before the Newton iteration.", ["bl_qs"]),
    ("Coupling", "Transition drifted downstream one station per iteration before the solution settled.",
     "Transition moves only once the state has converged; downstream moves re-march the laminar part, and large moves re-march the turbulent part.", ["bl_gate", "bl_advlam", "bl_remarch"]),
    ("Performance", "One LU factorisation took 0.66 s because of OpenBLAS thread contention.",
     "Limited BLAS to one thread on import, which made it about 30 times faster.", ["init_threads"]),
    ("Euler", "Constant-coefficient residual smoothing was unstable on stretched cells.",
     "Martinelli's variable coefficients.", ["eu_irs"]),
    ("Euler", "Spurious loss of about 1.2 % of the inlet dynamic head.",
     "Wall clustering of the H-grid reduced it to about 0.2 %.", ["eu_wallcluster", "eu_wallcl"]),
    ("Euler", "The exit-pressure controller oscillated.",
     "Adaptive gain: halved on overshoot, steps clipped to 3 % of p₀.", ["eu_ctrl"]),
    ("Euler", "Total enthalpy drifted during convergence.",
     "Imposed uniform total enthalpy after each step (exact for steady adiabatic flow).", ["eu_iso"]),
    ("Euler", "A negative loss appeared when loss was referred to the ideal inlet state.",
     "The inviscid loss is the difference between inlet-plane and exit-plane mass-averaged p₀.", ["sol_omegainv", "eu_p0avg"]),
    ("Euler", "Transonic cases blew up during start-up.",
     "Positivity safeguard and a start from higher back pressure.", ["eu_positivity", "eu_init_bp"]),
    ("Euler", "An M₁ = 0.78 case could not reach its inlet Mach number.",
     "Choking is detected and reported as an error with the attainable Mach number.", ["eu_choke"]),
    ("Euler", "The turbine passage was unstable with strong wall clustering.",
     "Clustering is chosen from the blade camber (0.9 or 0.6).", ["eu_wallcl"]),
    ("Euler", "The default tolerance left up to 0.3 % of loss error; tighter defaults made viscous runs diverge.",
     "Defaults kept; the inviscid verification and M₁ = 0.72 cases use tight tolerances.", ["eu_tol", "ver_tight"]),
    ("Verification", "The manufactured body did not close.",
     "The cross-flow is solved for so that both stagnation points share a streamline.", ["ver_close"]),
    ("Verification", "Lieblein's formula disagreed with the mixed-out loss.",
     "Lieblein's formula is the first-order term; the exact incompressible mixing analysis is the reference.", ["ver_incloss", "lo_lieblein"]),
    ("Dashboard", "The live solver never started on GitHub Pages.",
     "Jekyll dropped __init__.py; the site now has a .nojekyll file, and the worker reports missing files.", ["wk_fetchcheck", "ix_gooffline"]),
    ("Dashboard", "The turbine Euler Mach field showed the compressor blade.",
     "Each Euler case now carries and draws its own blade.", ["ix_eufam"]),
    ("Aerofoil input", "Stagger after placement was 0.17° off for coarse files.",
     "The chord line uses the same spline leading edge as the Blade class.", ["geo_spline_le"]),
]


def table_devlog():
    rows = []
    for area, problem, fix, keys in DEVLOG:
        refs = ", ".join(ref_html(k) for k in keys)
        rows.append(f"<tr><td>{area}</td><td>{problem}</td><td>{fix}</td><td>{refs}</td></tr>")
    return ('<div class="scroll"><table class="log"><caption><b>Table 6.</b> Problems met during '
            'development and how they were resolved, in the order they were found.</caption>'
            "<thead><tr><th>Area</th><th>Observation</th><th>Resolution</th><th>Code</th></tr></thead>"
            "<tbody>" + "".join(rows) + "</tbody></table></div>")


def table_appendix():
    groups = {}
    for key, (path, a, b) in USED.items():
        groups.setdefault(path, set()).add((a, b, key))
    rows = []
    for path in sorted(groups):
        items = sorted(groups[path])
        links = " ".join(
            f'<a class="loc" href="{GITHUB}/blob/{SHA}/mises/{path}#L{a}{"-L" + str(b) if b else ""}">'
            f'{a}{"–" + str(b) if b else ""}</a>' for a, b, _ in items)
        rows.append(f"<tr><td><code>mises/{path}</code></td><td class='idx'>{links}</td></tr>")
    return ('<div class="scroll"><table><caption><b>Table A1.</b> Every source location cited in '
            f'this report, at commit <code>{SHA_SHORT}</code>.</caption><thead><tr><th>File</th>'
            "<th>Lines</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


def count_tests():
    r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"], cwd=ROOT,
                       capture_output=True, text=True)
    m = re.search(r"(\d+) tests? collected", r.stdout)
    return int(m.group(1)) if m else 0


# ---------------------------------------------------------------------------
# page
# ---------------------------------------------------------------------------

def build():
    S = compute_selig()
    st = library_stats()
    n_tests = count_tests()
    rows, total_lines = module_rows()
    lib_total = sum(s["n"] for s in st.values())
    lib_conv = sum(s["n"] - s["err"] - s["unc"] for s in st.values())
    frags = {
        "SHA": SHA_SHORT, "SHA_LINK": f'<a href="{GITHUB}/tree/{SHA}/mises">{SHA_SHORT}</a>',
        "N_TESTS": str(n_tests), "N_LINES": f"{total_lines:,}", "LIB_TOTAL": str(lib_total),
        "LIB_CONV": str(lib_conv), "LIB_PCT": f"{100 * lib_conv / lib_total:.0f}",
        "F_ARCH": fig_architecture(), "T_MODULES": table_modules(),
    }
    # figures are numbered in order of appearance: build them in that order
    frags["F_MMS"] = fig_manufactured()
    frags["F_CONV"] = fig_convergence()
    frags["F_BL"] = fig_bl()
    frags["F_NOZ"] = fig_nozzle()
    frags["F_EVP"] = fig_euler_vs_panel()
    frags["T_VER"] = table_verification()
    frags["F_BUCKET"] = fig_bucket()
    frags["T_LIB"] = table_library(st)
    frags["F_VISC"] = fig_viscous_euler()
    frags["T_EULER"] = table_euler()
    frags["F_SELIG"] = fig_selig(S)
    frags["T_SELIG"] = table_selig(S)
    frags["T_DEVLOG"] = table_devlog()
    for k in FIGNUM:
        frags["FIG:" + k] = f'<a href="#{k}">Figure {FIGNUM[k]}</a>'
    E = EUL
    frags.update({
        "EU_TURB_INV": f"{E['euler_turbine']['perf']['omega_inviscid']:.3f}",
        "EU_TURB_VISC": f"{E['euler_turbine']['perf']['omega_viscous']:.4f}",
        "EU_TURB_OM": f"{E['euler_turbine']['perf']['omega']:.3f}",
        "PAN_TURB_OM": f"{libcase('turbine', 30, 0.3, 5e5)['perf']['omega']:.3f}",
        "EU_M05_OM": f"{E['euler_m05']['perf']['omega']:.4f}",
        "PAN_M05_OM": f"{libcase('compressor', 43, 0.5, 5e5)['perf']['omega']:.4f}",
        "SEL_C_OM": f"{S['coarse']['omega']:.4f}", "SEL_F_OM": f"{S['fine']['omega']:.4f}",
        "SEL_DOM": f"{abs(S['coarse']['omega'] / S['fine']['omega'] - 1) * 100:.1f}",
        "SEL_DB2": f"{abs(S['coarse']['beta2'] - S['fine']['beta2']):.2f}",
        "VER_PASS": str(sum(c["passed"] for c in VER.values())), "VER_N": str(len(VER)),
        "DATE": git("log", "-1", "--format=%cd", "--date=format:%d %B %Y"),
    })
    template = TEMPLATE

    def repl(m):
        k = m.group(1)
        if k in frags:
            return frags[k]
        if k in REFS:
            return ref_html(k)
        raise SystemExit(f"unknown placeholder [[{k}]]")

    body = re.sub(r"\[\[([A-Za-z0-9_:\-]+)\]\]", repl, template)
    body = body.replace("@@APPENDIX@@", table_appendix())
    return body


HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
"""

TEMPLATE = (Path(__file__).with_name("report_template.html")).read_text() if (Path(__file__).with_name("report_template.html")).exists() else ""


def main():
    global TEMPLATE
    TEMPLATE = Path(__file__).with_name("report_template.html").read_text()
    body = build()
    full = HEAD + body.replace("<!--BODY-->", "", 1)
    full = full.replace("</style>\n", "</style>\n</head>\n<body>\n", 1) + "\n</body>\n</html>\n"
    (ROOT / "report.html").write_text(full)
    print(f"wrote {ROOT / 'report.html'} ({len(full) / 1024:.0f} kB, {len(USED)} code references, "
          f"{len(FIGNUM)} figures, commit {SHA_SHORT})")
    if "--fragment" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--fragment") + 1])
        out.write_text(body)
        print(f"wrote fragment {out}")


if __name__ == "__main__":
    main()
