"""Launch options: defaults and a reader for ``launch.m`` files.

``parse_launch_file`` evaluates the ``opt.<name> = <value>;`` assignments of a
the MATLAB code launch script (numbers, true/false, 'strings', [arrays], {cells}, ranges
a:b:c, pi, + - * / ^ and their element-wise forms, and linspace/logspace/sqrt/
sin/cos/deg2rad).  Everything else in the script (paths, diary, preprocess and
the MATLAB code calls) is ignored.
"""
from __future__ import annotations

import math
import re

import numpy as np

__all__ = ["DEFAULTS", "OPTION_INFO", "parse_launch_file", "merged_options"]

# defaults: the values of examples/launch.m, plus options the MATLAB code reads but that file does not set
DEFAULTS = {
    "StageCount": 2, "LPC_inputs": False, "LPC2_folder": "./INPUT/LPC2/", "LPC2_inputs_file": "",
    "CaseInputs": "case.mat", "input_folder": "INPUT/", "output_folder": "OUTPUT/",
    "CFD_data": True, "Wake_data_file": "", "Wake_data_folder": "", "BL_folder": "", "bl_files": [],
    "baddata": "IGNORE",
    "rotor_noise": True, "noise_type": "BOTH",
    "uniform_inflow": True, "alphae": 0.0, "bpv": 0.0, "wpv": 0.0, "vpv": 0.0, "eoffset": 0.0,
    "installation_noise": False, "p_noise_type": "BPRI", "BPRI_correlation": False,
    "partial_loading": True, "wall": True, "dwall": 0.2486, "bl_height": 0.1,
    "bondary_layer_input_from_file": True, "boundary_layer_input_filepath": "",
    "ua": 1.0, "ut": 2.0, "la": 0.3, "lt": 0.1, "aniso_alpha": 1.0,
    "chapman": False, "emission_angle": False, "phi_sw": "RZ", "emp_corr": False, "Karman_spec": True,
    "aniso_spec": "Liep", "Uc": "DEL2", "lr": "SLZ", "L": 0.4, "amiet": False, "phi_num": 50,
    "spectral_study": True, "f_d": 2000.0, "f_l": 50.0, "f_h": 20000.0, "f_num": 50,
    "phi_obs_num": 1, "spectral_phi_obs": [0.0],
    "st_num": 5, "contraction_perc": 100, "r0": 2.54, "ScaleFactor": 1,
    "theta": list(np.arange(10.0, 171.0, 20.0) * np.pi / 180),
    "rotor_direction": "POSITIVE", "p_loc": 0.0,
}

OPTION_INFO = {
    "StageCount": "1 or 2 rotor stages",
    "LPC_inputs": "take Ux1/Ux2 from the case file (LPC2) instead of the velocity triangles",
    "CaseInputs": "geometry/condition .mat file (geom, cond structs) under INPUT/",
    "CFD_data": "boundary layers and wakes from files (true) - Xfoil (false) is not available here",
    "Wake_data_file": ".mat with bw, wrms_bg, wrms_wake, L_bg, L_wake (one value per strip)",
    "BL_folder": "folder of the boundary-layer files",
    "bl_files": "BL files: front top, front bottom, rear top, rear bottom (13 columns, one row per strip)",
    "baddata": "strips flagged in the discard column: REPLACE, DISCARD or IGNORE",
    "noise_type": "BRWI, BRTE or BOTH",
    "phi_sw": "wall-pressure model: WA, CH, GY, KG, RZ",
    "Uc": "convection velocity: 0.8, DEL, GLB, DEL2",
    "lr": "spanwise correlation length: COR, ROG, LGL, RGS, CORL, EFP, SLZ",
    "L": "wake integral length scale: number C (L = C * L_file), 'BW' (0.42 bw) or 'Pope'",
    "amiet": "Amiet's simplified rotational model (true) or the full model (false)",
    "chapman": "Chapman mean-flow correction",
    "emission_angle": "results in emission co-ordinates",
    "theta": "observer polar angles (rad, Airbus convention theta* = 0 upstream)",
    "f_l": "lowest frequency [Hz]", "f_h": "highest frequency [Hz]", "f_num": "number of frequencies",
    "st_num": "number of radial strips", "r0": "observer radius [m]",
}

_FUNCS = {
    "linspace": lambda a, b, n=100: np.linspace(a, b, int(n)) if int(n) != 1 else np.array([b]),
    "logspace": lambda a, b, n=50: 10.0 ** np.linspace(a, b, int(n)),
    "sqrt": np.sqrt, "sin": np.sin, "cos": np.cos, "deg2rad": np.deg2rad, "abs": np.abs,
}

_TOK = re.compile(r"\s*(?:(\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?)|('(?:[^']|'')*')|"
                  r"(\.\*|\./|\.\^|[-+*/^():,;\[\]{}])|([A-Za-z_]\w*))")


class _Parser:
    def __init__(self, text):
        self.toks = []
        pos = 0
        text = text.strip()
        while pos < len(text):
            m = _TOK.match(text, pos)
            if not m or m.end() == pos:
                if text[pos].isspace():
                    pos += 1
                    continue
                raise ValueError(f"cannot parse {text!r}")
            num, s, op, name = m.groups()
            pre_space = m.start(1 if num else 2 if s else 3 if op else 4) > pos
            self.toks.append(("num", float(num), pre_space) if num else ("str", s[1:-1].replace("''", "'"), pre_space)
                             if s else ("op", op, pre_space) if op else ("name", name, pre_space))
            pos = m.end()
        self.i = 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None, False)

    def take(self, val=None):
        t = self.peek()
        if val is not None and t[1] != val:
            raise ValueError(f"expected {val!r}")
        self.i += 1
        return t

    def parse(self):
        v = self.range_()
        if self.i != len(self.toks):
            raise ValueError("trailing input")
        return v

    def range_(self):
        a = self.add()
        if self.peek()[1] == ":":
            self.take(":")
            b = self.add()
            if self.peek()[1] == ":":
                self.take(":")
                c = self.add()
                return np.arange(a, c + b * 1e-9, b)
            return np.arange(a, b + 1e-9)
        return a

    def add(self, in_list=False):
        v = self.mul()
        while self.peek()[1] in ("+", "-"):
            if in_list and self.peek()[2] and not (self.i + 1 < len(self.toks) and self.toks[self.i + 1][2]):
                break                      # "[1 -2]" is two elements in MATLAB
            op = self.take()[1]
            r = self.mul()
            v = v + r if op == "+" else v - r
        return v

    def mul(self):
        v = self.unary()
        while self.peek()[1] in ("*", "/", ".*", "./"):
            op = self.take()[1]
            r = self.unary()
            v = v * r if op in ("*", ".*") else v / r
        return v

    def unary(self):
        if self.peek()[1] in ("-", "+"):
            op = self.take()[1]
            v = self.unary()
            return -v if op == "-" else v
        return self.power()

    def power(self):
        v = self.atom()
        while self.peek()[1] in ("^", ".^"):
            self.take()
            v = v ** self.atom()
        return v

    def atom(self):
        kind, val, _ = self.take()
        if kind == "num":
            return val
        if kind == "str":
            return val
        if kind == "name":
            if val == "pi":
                return math.pi
            if val in ("true", "false"):
                return val == "true"
            if val in _FUNCS and self.peek()[1] == "(":
                self.take("(")
                args = [self.range_()]
                while self.peek()[1] == ",":
                    self.take(",")
                    args.append(self.range_())
                self.take(")")
                return _FUNCS[val](*args)
            raise ValueError(f"unknown name {val!r}")
        if val == "(":
            v = self.range_()
            self.take(")")
            return v
        if val in ("[", "{"):
            close = "]" if val == "[" else "}"
            items = []
            while self.peek()[1] != close:
                if self.peek()[1] in (",", ";"):
                    self.take()
                    continue
                start = self.i
                item = self.add(in_list=True)
                if self.peek()[1] == ":":
                    self.i = start
                    item = self.range_()
                items.append(item)
            self.take(close)
            if val == "{":
                return list(items)
            flat = []
            for it in items:
                flat.extend(np.atleast_1d(it).tolist())
            return np.array(flat, float)
        raise ValueError(f"unexpected {val!r}")


def _strip_comment(line):
    out, q = [], False
    for ch in line:
        if ch == "'":
            q = not q
        if ch == "%" and not q:
            break
        out.append(ch)
    return "".join(out)


def parse_launch_file(text, defaults=True):
    """Options of a launch script (``launch.m``) as a dict, on top of the defaults."""
    opt = dict(DEFAULTS) if defaults else {}
    lines = [_strip_comment(l) for l in text.splitlines()]
    joined = []
    buf = ""
    for l in lines:
        if l.rstrip().endswith("..."):
            buf += l.rstrip()[:-3] + " "
            continue
        joined.append(buf + l)
        buf = ""
    for line in joined:
        for stmt in _split_statements(line):
            m = re.match(r"\s*opt\.(\w+)\s*=\s*(.+?)\s*$", stmt)
            if not m:
                continue
            name, expr = m.groups()
            try:
                val = _Parser(expr).parse()
            except Exception as exc:                          # noqa: BLE001
                raise ValueError(f"launch file: cannot read opt.{name} = {expr}: {exc}") from None
            opt[name] = val.tolist() if isinstance(val, np.ndarray) else val
    return opt


def _split_statements(line):
    out, cur, depth, q = [], "", 0, False
    for ch in line:
        if ch == "'":
            q = not q
        if not q:
            if ch in "[{(":
                depth += 1
            elif ch in "]})":
                depth -= 1
            elif ch == ";" and depth == 0:
                out.append(cur)
                cur = ""
                continue
        cur += ch
    if cur.strip():
        out.append(cur)
    return out


def merged_options(*sources):
    opt = dict(DEFAULTS)
    for s in sources:
        if s:
            opt.update(s)
    return opt
