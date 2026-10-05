"""Driver (the main script): run the selected rotor (and installation) noise models."""
from __future__ import annotations

from types import SimpleNamespace as NS

from .inputs import MCodeError, inputs, preprocess
from .models import BPRI_amiet, BRTE, BRTE_amiet, BRWI

__all__ = ["run_mcode", "MCodeError"]


def run_mcode(opt, base_dir=".", case_data=None, bl_data=None, wake_data=None, bl_ingestion=None,
            progress=None):
    """Run the MATLAB code with launch options ``opt`` (the MATLAB code names).  Returns a namespace with
    ``Spps`` (dict of spectra in the MATLAB code's layout), ``geom``, ``flow``, ``bl``, ``lists``, ``opt``
    and, for installation noise, ``p`` (the installation inputs)."""
    pre = preprocess(opt, base_dir, case_data=case_data, bl_data=bl_data, wake_data=wake_data)
    out = NS(Spps={}, geom=None, flow=None, bl=None, lists=None, opt=pre.opt, p=None, pre=pre)
    o = pre.opt
    if o.get("rotor_noise", True):
        geom, flow, opt2, bl, lists = inputs(pre)
        out.geom, out.flow, out.opt, out.bl, out.lists = geom, flow, opt2, bl, lists
        nt = opt2["noise_type"]
        amiet = bool(opt2.get("amiet"))
        if nt == "BRWI":
            if int(opt2["StageCount"]) == 1:
                raise MCodeError("Two rotors are needed to consider BRWI noise")
            out.Spps["BRWI"] = BPRI_amiet(geom, flow, opt2, lists) if amiet else BRWI(geom, flow, opt2, lists, progress)
            out.Spps["BRTE"] = 0                      # as the main script does
        elif nt == "BRTE":
            fn = BRTE_amiet if amiet else BRTE
            out.Spps["BRTE1"] = fn(geom, flow, opt2, bl, lists, 0, "BRTE", progress)
            if int(opt2["StageCount"]) == 2:
                out.Spps["BRTE2"] = fn(geom, flow, opt2, bl, lists, 1, "BRTE", progress)
            out.Spps["BRWI"] = 0                      # as the main script does
        elif nt == "BOTH":
            fn = BRTE_amiet if amiet else BRTE
            out.Spps["BRTE1"] = fn(geom, flow, opt2, bl, lists, 0, "BRTE", progress)
            out.Spps["BRTE2"] = fn(geom, flow, opt2, bl, lists, 1, "BRTE", progress)
            out.Spps["BRWI"] = BPRI_amiet(geom, flow, opt2, lists) if amiet else BRWI(geom, flow, opt2, lists, progress)
            out.Spps["tot"] = out.Spps["BRTE1"] + out.Spps["BRTE2"] + out.Spps["BRWI"][..., None] \
                if out.Spps["BRWI"].ndim == 3 else out.Spps["BRTE1"] + out.Spps["BRTE2"] + out.Spps["BRWI"]
    if o.get("installation_noise"):
        from .installation import run_installation
        run_installation(out, pre, base_dir, bl_ingestion=bl_ingestion, progress=progress)
    return out
