"""Solver driver: run the selected rotor and installation noise models."""
from __future__ import annotations

from types import SimpleNamespace as NS

from .inputs import SolverError, inputs, preprocess
from .models import BPRI_amiet, BRTE, BRTE_amiet, BRWI

__all__ = ["solve", "SolverError"]


def solve(opt, case_data, bl_data=None, wake_data=None, bl_ingestion=None, progress=None):
    """Run the solver with options ``opt`` (see :data:`bbn.defaults.DEFAULTS`).  Returns a namespace
    with ``Spps`` (dict of spectra ``[omega, theta, strip(+sum), observer]``), ``geom``, ``flow``,
    ``bl``, ``lists``, ``opt`` and, for installation noise, ``p`` (the installation inputs).
    :func:`bbn.config.run` builds all of this from the three input sections."""
    pre = preprocess(opt, case_data, bl_data=bl_data, wake_data=wake_data)
    out = NS(Spps={}, geom=None, flow=None, bl=None, lists=None, opt=pre.opt, p=None, pre=pre)
    o = pre.opt
    if o.get("rotor_noise", True):
        geom, flow, opt2, bl, lists = inputs(pre)
        out.geom, out.flow, out.opt, out.bl, out.lists = geom, flow, opt2, bl, lists
        nt = opt2["noise_type"]
        amiet = bool(opt2.get("amiet"))
        if nt == "BRWI":
            if int(opt2["StageCount"]) == 1:
                raise SolverError("interaction noise needs two rotors")
            out.Spps["BRWI"] = BPRI_amiet(geom, flow, opt2, lists) if amiet else BRWI(geom, flow, opt2, lists, progress)
            out.Spps["BRTE"] = 0
        elif nt == "BRTE":
            fn = BRTE_amiet if amiet else BRTE
            out.Spps["BRTE1"] = fn(geom, flow, opt2, bl, lists, 0, "BRTE", progress)
            if int(opt2["StageCount"]) == 2:
                out.Spps["BRTE2"] = fn(geom, flow, opt2, bl, lists, 1, "BRTE", progress)
            out.Spps["BRWI"] = 0
        elif nt == "BOTH":
            fn = BRTE_amiet if amiet else BRTE
            out.Spps["BRTE1"] = fn(geom, flow, opt2, bl, lists, 0, "BRTE", progress)
            out.Spps["BRTE2"] = fn(geom, flow, opt2, bl, lists, 1, "BRTE", progress)
            out.Spps["BRWI"] = BPRI_amiet(geom, flow, opt2, lists) if amiet else BRWI(geom, flow, opt2, lists, progress)
            out.Spps["tot"] = out.Spps["BRTE1"] + out.Spps["BRTE2"] + out.Spps["BRWI"][..., None] \
                if out.Spps["BRWI"].ndim == 3 else out.Spps["BRTE1"] + out.Spps["BRTE2"] + out.Spps["BRWI"]
    if o.get("installation_noise"):
        from .installation import run_installation
        run_installation(out, pre, bl_ingestion=bl_ingestion, progress=progress)
    return out
