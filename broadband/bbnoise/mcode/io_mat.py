"""Write a output.mat-like file (Spps, results, lists, opt, geom, flow, p) with scipy."""
from __future__ import annotations

from pathlib import Path

import numpy as np

__all__ = ["save_mcode_output"]


def _ns(x):
    if x is None:
        return np.zeros((0, 0))
    if hasattr(x, "__dict__") and not isinstance(x, np.ndarray):
        return {k: _ns(v) for k, v in vars(x).items() if not k.startswith("_")}
    if isinstance(x, dict):
        return {str(k): _ns(v) for k, v in x.items() if v is not None}
    if isinstance(x, (list, tuple)) and x and all(isinstance(v, str) for v in x):
        return np.array(x, dtype=object)
    return x


def save_mcode_output(res, path, results=None):
    """``results`` (from :mod:`bbnoise.mcode.pp`) is saved too, as the driver script does."""
    from scipy.io import savemat
    data = {"Spps": {k: (np.asarray(v) if not np.isscalar(v) else float(v)) for k, v in res.Spps.items()},
            "opt": _ns(res.opt)}
    for k in ("lists", "geom", "flow"):
        v = getattr(res, k, None)
        if v is not None:
            data[k] = _ns(v)
    if getattr(res, "p", None) is not None:
        data["p"] = {k: _ns(getattr(res.p, k)) for k in ("geom", "flow", "opt", "lists")}
    if results is not None:
        data["results"] = {(k[:-3] + "total" if k.endswith("_tot") else k):        # pp.m names
                           (np.asarray(v) if not np.isscalar(v) else float(np.real(v)))
                           for k, v in results.items() if k != "warnings"}
    path = Path(path)
    savemat(str(path), data, long_field_names=True, oned_as="row")
    return str(path)
