"""Result output: JSON, CSV tables, text summaries and (optional) matplotlib plots."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np


def _write_csv(path, header, rows):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow([f"{v:.8g}" if isinstance(v, (float, np.floating)) else v for v in r])


def surface_rows(result):
    rows = []
    for srf in (result.upper, result.lower):
        for i in range(srf.x.size):
            rows.append([srf.name, srf.x[i], srf.y[i], srf.xc[i], srf.s[i], srf.mis[i], srf.cp[i],
                         srf.q[i]])
    return ["side", "x", "y", "x_c", "s", "Mis", "Cp", "q_V1"], rows


def bl_rows(result):
    rows = []
    for bl in (result.bl_upper, result.bl_lower):
        if bl is None:
            continue
        for i in range(bl.xi.size):
            rows.append([bl.name, bl.x[i], bl.xc[i], bl.xi[i], bl.ue[i], bl.theta[i], bl.dstar[i],
                         bl.H[i], bl.Hk[i], bl.cf[i], bl.re_theta[i], bl.ampl[i],
                         int(bool(bl.turbulent[i]))])
    return ["side", "x", "x_c", "s", "ue_V1", "theta", "dstar", "H", "Hk", "Cf", "Re_theta",
            "N_or_sqrtCtau", "turbulent"], rows


PERF_COLUMNS = ["sweep_value", "beta1", "incidence", "M1", "M2", "beta2", "deviation", "turning",
                "omega", "omega_inviscid", "omega_viscous", "p2_p1", "diffusion_factor",
                "xtr_upper", "xtr_lower", "theta_te", "H_te_upper", "H_te_lower"]


def save_result(result, directory, stem="result", plots=True, json_out=True, csv_out=True):
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    files = []
    if json_out:
        p = d / f"{stem}.json"
        p.write_text(result.to_json(indent=1))
        files.append(p)
    if csv_out:
        h, r = surface_rows(result)
        p = d / f"{stem}_surface.csv"
        _write_csv(p, h, r)
        files.append(p)
        if result.bl_upper is not None:
            h, r = bl_rows(result)
            p = d / f"{stem}_boundary_layer.csv"
            _write_csv(p, h, r)
            files.append(p)
    p = d / f"{stem}_summary.txt"
    p.write_text(result.summary() + "\n")
    files.append(p)
    if plots:
        files += plot_result(result, d, stem)
    return files


def save_results(case, results, directory, plots=True, json_out=True, csv_out=True):
    """Save one result or a sweep of results; returns the list of written files."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    files = []
    if len(results) == 1 and case.sweep is None:
        return save_result(results[0], d, "result", plots, json_out, csv_out)
    for i, res in enumerate(results):
        files += save_result(res, d, f"point_{i:03d}", plots=False, json_out=json_out,
                             csv_out=csv_out)
    rows = [[res.performance.get(c, "") for c in PERF_COLUMNS] for res in results]
    p = d / "sweep.csv"
    _write_csv(p, PERF_COLUMNS, rows)
    files.append(p)
    if json_out:
        p = d / "sweep.json"
        p.write_text(json.dumps({"case": case.name, "parameter": case.sweep["parameter"],
                                 "points": [r.to_dict()["performance"] for r in results]},
                                indent=1))
        files.append(p)
    if plots:
        files += plot_sweep(case, results, d)
    return files


# ---------------------------------------------------------------------------
# plotting (matplotlib optional)
# ---------------------------------------------------------------------------

def _mpl():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return plt
    except Exception:  # pragma: no cover
        return None


def plot_result(result, directory, stem="result"):
    plt = _mpl()
    if plt is None:
        return []
    d = Path(directory)
    files = []
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for srf, st in ((result.upper, "-"), (result.lower, "--")):
        ax.plot(srf.xc, srf.mis, st, label=f"{srf.name} surface")
    ax.set_xlabel("x/c")
    ax.set_ylabel("isentropic Mach number")
    ax.set_title(f"{result.blade['name']}  M1={result.flow['inlet_mach']:.3f}  "
                 f"beta1={result.flow['inlet_angle']:.2f} deg")
    ax.grid(alpha=0.3)
    ax.legend()
    p = d / f"{stem}_mis.png"
    fig.tight_layout()
    fig.savefig(p, dpi=130)
    plt.close(fig)
    files.append(p)

    if result.bl_upper is not None:
        fig, axs = plt.subplots(2, 2, figsize=(9, 6), sharex=True)
        for bl, st in ((result.bl_upper, "-"), (result.bl_lower, "--")):
            axs[0, 0].plot(bl.xc, bl.dstar, st, label=bl.name)
            axs[0, 1].plot(bl.xc, bl.theta, st, label=bl.name)
            axs[1, 0].plot(bl.xc, bl.H, st, label=bl.name)
            axs[1, 1].plot(bl.xc, bl.cf, st, label=bl.name)
        for a, t in zip(axs.flat, ("delta*/c", "theta/c", "H", "Cf")):
            a.set_ylabel(t)
            a.grid(alpha=0.3)
        axs[1, 1].axhline(0, color="k", lw=0.6)
        cfs = np.concatenate([result.bl_upper.cf, result.bl_lower.cf])
        axs[1, 1].set_ylim(min(-0.002, float(np.percentile(cfs, 2)) * 1.2),
                           float(np.percentile(cfs, 95)) * 1.5)
        hs = np.concatenate([result.bl_upper.H, result.bl_lower.H])
        axs[1, 0].set_ylim(1.0, min(float(hs.max()) * 1.1, 8.0))
        axs[1, 0].set_xlabel("x/c")
        axs[1, 1].set_xlabel("x/c")
        axs[0, 0].legend()
        fig.tight_layout()
        p = d / f"{stem}_boundary_layer.png"
        fig.savefig(p, dpi=130)
        plt.close(fig)
        files.append(p)

    fig, ax = plt.subplots(figsize=(5, 5))
    x = np.asarray(result.blade["x"])
    y = np.asarray(result.blade["y"])
    s = result.blade["pitch"]
    for k in (-1, 0, 1):
        ax.fill(x, y + k * s, color="0.75", ec="0.3")
    ax.set_aspect("equal")
    ax.set_title("cascade geometry")
    p = d / f"{stem}_geometry.png"
    fig.tight_layout()
    fig.savefig(p, dpi=110)
    plt.close(fig)
    files.append(p)
    return files


def plot_sweep(case, results, directory):
    plt = _mpl()
    if plt is None:
        return []
    d = Path(directory)
    xs = [r.performance.get("sweep_value") for r in results]
    key = case.sweep["parameter"]
    fig, axs = plt.subplots(1, 2, figsize=(10, 4))
    axs[0].plot(xs, [r.performance["omega"] for r in results], "o-")
    axs[0].set_ylabel("loss coefficient omega")
    axs[1].plot(xs, [r.performance["beta2"] for r in results], "o-")
    axs[1].set_ylabel("exit flow angle beta2 [deg]")
    for a in axs:
        a.set_xlabel(key)
        a.grid(alpha=0.3)
    fig.suptitle(case.name)
    fig.tight_layout()
    p = d / "sweep.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return [p]
