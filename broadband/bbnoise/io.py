"""Loading case files (TOML / JSON) and writing results (CSV, JSON, PNG)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from .model import CaseResult, third_octave

__all__ = ["load_case", "save_case", "write_results"]


def load_case(path):
    """Load a TOML or JSON case.  Table files it references (``rotors[i].blade_file``,
    ``self_noise.boundary_layer.path``) are resolved relative to the case file."""
    p = Path(path)
    text = p.read_text()
    if p.suffix.lower() == ".json":
        case = json.loads(text)
    elif p.suffix.lower() == ".toml":
        try:
            import tomllib
        except ModuleNotFoundError:  # Python < 3.11
            import tomli as tomllib
        case = tomllib.loads(text)
    else:
        raise ValueError(f"unsupported case file {p.name} (use .toml or .json)")
    return resolve_paths(case, p.resolve().parent)


def resolve_paths(case, base):
    base = Path(base)

    def fix(v):
        q = Path(v)
        return str(q if q.is_absolute() else (base / q).resolve())

    for r in case.get("rotors", []) or []:
        if r.get("blade_file"):
            r["blade_file"] = fix(r["blade_file"])
    sn = case.get("self_noise") or {}
    for bl in [sn.get("boundary_layer") or {}] + list((sn.get("boundary_layers") or {}).values()):
        if bl.get("path"):
            bl["path"] = fix(bl["path"])
    return case


def save_case(case, path):
    Path(path).write_text(json.dumps(case, indent=2))
    return str(path)


def _slug(s):
    return "".join(ch if ch.isalnum() else "_" for ch in s).strip("_")[:60] or "case"


def write_results(res: CaseResult, outdir, plots=True):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    stem = _slug(res.case.get("key", res.name))
    files = []
    header, rows = res.table()
    p = out / f"{stem}_psd.csv"
    with p.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow([f"{v:.6g}" for v in r])
    files.append(str(p))
    # 1/3 octave bands
    p = out / f"{stem}_third_octave.csv"
    bands = [third_octave(res.f, c.G) for c in res.curves]
    if bands:
        with p.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["fc_Hz"] + [c.label for c in res.curves])
            for i, fc in enumerate(bands[0][0]):
                w.writerow([f"{fc:.1f}"] + [f"{b[1][i]:.2f}" for b in bands])
        files.append(str(p))
    strip_curves = [c for c in res.curves if c.strips is not None]
    if strip_curves:
        p = out / f"{stem}_strips.csv"
        with p.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["curve", "r_m", "dr_m", "chord_m", "U_m_s", "oaspl_dB", "energy_share"])
            for c in strip_curves:
                G = np.asarray(c.strips["G"])
                e = np.trapezoid(G, res.f, axis=1)
                for k in range(G.shape[0]):
                    w.writerow([c.label, f"{c.strips['r'][k]:.5g}", f"{c.strips['dr'][k]:.5g}",
                                f"{c.strips['chord'][k]:.5g}", f"{c.strips['U'][k]:.5g}",
                                f"{10 * np.log10(max(e[k], 1e-30) / 4e-10):.2f}", f"{e[k] / max(e.sum(), 1e-300):.4f}"])
        files.append(str(p))
        p = out / f"{stem}_strip_psd.csv"
        with p.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["curve", "r_m"] + [f"{f:.6g}" for f in res.f])
            for c in strip_curves:
                for k, g in enumerate(np.asarray(c.strips["G"])):
                    w.writerow([c.label, f"{c.strips['r'][k]:.5g}"]
                               + [f"{v:.2f}" for v in 10 * np.log10(np.maximum(g, 1e-30) / 4e-10)])
        files.append(str(p))
    p = out / f"{stem}.json"
    p.write_text(json.dumps(res.to_dict(), indent=1))
    files.append(str(p))
    if plots:
        try:
            files += _plot(res, out, stem)
        except ImportError:
            pass
    return files


def _plot(res, out, stem):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    files = []
    fig, ax = plt.subplots(figsize=(8, 5))
    for c in res.curves:
        ax.semilogx(res.f, 10 * np.log10(np.maximum(c.G, 1e-30) / 4e-10), label=c.label,
                    ls="-" if c.formulation in ("full", "stationary") else "--")
    ax.set_xlabel("Frequency [Hz]")
    ax.set_ylabel("PSD [dB re 20 uPa / Hz]")
    ax.set_title(res.name, fontsize=10)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=7)
    fig.tight_layout()
    p = out / f"{stem}_psd.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    files.append(str(p))
    strip_curves = [c for c in res.curves if c.strips is not None]
    if strip_curves:
        loud = max(strip_curves, key=lambda c: np.trapezoid(c.G, res.f))
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 5.2 + 0.12 * len(strip_curves)))
        for c in strip_curves:
            e = np.trapezoid(np.asarray(c.strips["G"]), res.f, axis=1)
            a1.plot(c.strips["r"], 10 * np.log10(np.maximum(e, 1e-30) / 4e-10), marker="o", label=c.label,
                    ls="-" if c.formulation == "full" else "--")
        a1.set_xlabel("Strip radius r [m]")
        a1.set_ylabel("Strip OASPL [dB]")
        a1.set_title("Contribution of each radial strip", fontsize=10)
        a1.grid(True, alpha=0.3)
        a1.legend(fontsize=6, loc="upper left", bbox_to_anchor=(0.0, -0.14), ncol=2, frameon=False)
        G = 10 * np.log10(np.maximum(np.asarray(loud.strips["G"]), 1e-30) / 4e-10)
        r = np.asarray(loud.strips["r"])
        dr = np.asarray(loud.strips["dr"])
        edges = np.concatenate([r - dr / 2, [r[-1] + dr[-1] / 2]])
        fe = np.sqrt(res.f[:-1] * res.f[1:])
        fedges = np.concatenate([[res.f[0] ** 2 / fe[0]], fe, [res.f[-1] ** 2 / fe[-1]]])
        m = a2.pcolormesh(fedges, edges, G, cmap="Blues", vmin=G.max() - 40, vmax=G.max(), shading="flat")
        a2.set_xscale("log")
        a2.set_xlabel("Frequency [Hz]")
        a2.set_ylabel("Strip radius r [m]")
        a2.set_title(f"Strip PSD: {loud.label}", fontsize=9)
        fig.colorbar(m, ax=a2, label="PSD [dB re (20 uPa)^2/Hz]")
        fig.tight_layout()
        p = out / f"{stem}_strips.png"
        fig.savefig(p, dpi=130)
        plt.close(fig)
        files.append(str(p))
    dirs = [c for c in res.curves if c.directivity]
    if dirs:
        fig, ax = plt.subplots(figsize=(7, 4.5))
        for c in dirs:
            o = np.argsort(c.directivity["theta"])
            ax.plot(np.asarray(c.directivity["theta"])[o], np.asarray(c.directivity["oaspl"])[o], marker="o",
                    label=c.label, ls="-" if c.formulation in ("full", "stationary") else "--")
        ax.set_xlabel("Polar angle [deg]")
        ax.set_ylabel("OASPL [dB]")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=7)
        fig.tight_layout()
        p = out / f"{stem}_directivity.png"
        fig.savefig(p, dpi=130)
        plt.close(fig)
        files.append(str(p))
    return files
