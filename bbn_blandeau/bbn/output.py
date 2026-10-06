"""Write results as CSV tables and JSON."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .levels import P_REF, W_REF

__all__ = ["write"]


def _db(x, ref):
    return 10 * np.log10(np.maximum(np.asarray(x, float), 1e-300) / ref)


def write(res, folder):
    """results.json, spectra.csv (PSD dB/Hz at every observer angle), directivity.csv (OASPL),
    sound_power.csv (PWL dB/Hz), strips_<key>.csv (strip PSDs at the first angle). Returns the paths."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    f, th = res.f, res.theta_deg
    curves = list(res.curves)
    tot = res.total()
    written = []

    def w(name, text):
        p = folder / name
        p.write_text(text)
        written.append(str(p))

    w("results.json", json.dumps(res.to_dict(), indent=1, allow_nan=False))
    cols, data = ["f_hz"], [f]
    for c in curves:
        for t, psd in zip(th, c.psd):
            cols.append(f"{c.key}@{t:g}deg")
            data.append(_db(psd, P_REF ** 2))
    if tot is not None:
        for t, psd in zip(th, tot):
            cols.append(f"total@{t:g}deg")
            data.append(_db(psd, P_REF ** 2))
    w("spectra.csv", "# PSD [dB re (20 uPa)^2/Hz], one-sided\n" + ",".join(cols) + "\n" +
      "\n".join(",".join(f"{v:.6g}" for v in row) for row in np.column_stack(data)) + "\n")
    rows = [[t] + [c.oaspl(f)[i] for c in curves] for i, t in enumerate(th)]
    w("directivity.csv", "# OASPL [dB re 20 uPa]\ntheta_deg," + ",".join(c.key for c in curves) + "\n" +
      "\n".join(",".join(f"{v:.6g}" for v in r) for r in rows) + "\n")
    pw = [c for c in curves if c.pwl is not None]
    if pw:
        w("sound_power.csv", "# PWL [dB re 1 pW/Hz]\nf_hz," + ",".join(c.key for c in pw) + "\n" +
          "\n".join(",".join(f"{v:.6g}" for v in r) for r in np.column_stack([f] + [_db(c.pwl, W_REF) for c in pw]))
          + "\n")
    for c in curves:
        if c.strips is None:
            continue
        r = c.strips["r"]
        w(f"strips_{c.key}.csv", f"# strip PSD [dB/Hz] at theta* = {th[0]:g} deg\nf_hz," +
          ",".join(f"r={v:.4g}m" for v in r) + "\n" +
          "\n".join(",".join(f"{v:.6g}" for v in row) for row in
                    np.column_stack([f] + [_db(p, P_REF ** 2) for p in c.strips["psd"]])) + "\n")
    return written
