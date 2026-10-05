"""Write the MATLAB code options back as a launch.m-style script (opt.* lines)."""
from __future__ import annotations

import math

__all__ = ["launch_text"]

_SECTIONS = [
    ("LPC2 inputs & geometry", ["StageCount", "LPC_inputs", "LPC2_folder", "LPC2_inputs_file", "CaseInputs"]),
    ("CFD data", ["CFD_data", "Wake_data_file", "BL_folder", "bl_files", "baddata"]),
    ("Rotor noise", ["rotor_noise", "noise_type"]),
    ("Uniform inflow", ["uniform_inflow", "alphae"]),
    ("Installation noise", ["installation_noise", "p_noise_type", "BPRI_correlation", "partial_loading", "wall",
                            "dwall", "bl_height", "bondary_layer_input_from_file", "boundary_layer_input_filepath",
                            "ua", "ut", "la", "lt"]),
    ("Noise model options", ["chapman", "emission_angle", "phi_sw", "emp_corr", "Karman_spec", "aniso_spec", "Uc",
                             "lr", "L", "amiet", "phi_num"]),
    ("Spectral study options", ["spectral_study", "f_d", "f_l", "f_h", "f_num", "phi_obs_num", "spectral_phi_obs"]),
    ("General parameters", ["st_num", "contraction_perc", "r0", "ScaleFactor", "theta"]),
]


def _fmt(v, key=None):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    if isinstance(v, (list, tuple)):
        if v and all(isinstance(x, str) for x in v):
            return "{ " + ", ".join(_fmt(x) for x in v) + " }"
        if key == "theta":
            return "[" + " ".join(f"{x * 180 / math.pi:.10g}" for x in v) + "]*pi/180"
        return "[" + " ".join(f"{float(x):.10g}" for x in v) + "]"
    if isinstance(v, float):
        if key == "theta":
            return f"[{v * 180 / math.pi:.10g}]*pi/180"
        return f"{v:.10g}"
    return str(v)


def launch_text(opt):
    lines = ["%% Launch options (written by bbnoise; run with the MATLAB code or with `bbnoise mcode`)", ""]
    done = set()
    for title, keys in _SECTIONS:
        lines.append("%" + "-" * 74)
        lines.append(f"% {title}")
        for k in keys:
            if k in opt:
                lines.append(f"opt.{k} = {_fmt(opt[k], k)};")
                done.add(k)
    rest = [k for k in opt if k not in done]
    if rest:
        lines.append("%" + "-" * 74)
        lines.append("% Other options")
        for k in rest:
            lines.append(f"opt.{k} = {_fmt(opt[k], k)};")
    return "\n".join(lines) + "\n"
