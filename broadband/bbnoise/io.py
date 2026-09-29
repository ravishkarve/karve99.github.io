"""Loading case files (TOML / JSON) and writing results (CSV, JSON, PNG)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from .model import CaseResult, third_octave

__all__ = ["load_case", "save_case", "write_results"]


def load_case(path):
    p = Path(path)
    text = p.read_text()
    if p.suffix.lower() == ".json":
        return json.loads(text)
    if p.suffix.lower() == ".toml":
        try:
            import tomllib
        except ModuleNotFoundError:  # Python < 3.11
            import tomli as tomllib
        return tomllib.loads(text)
    raise ValueError(f"unsupported case file {p.name} (use .toml or .json)")


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
