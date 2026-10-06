"""Results: one-sided PSDs per hertz, directivity, sound power and strip contributions."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .levels import P_REF, W_REF, sound_power, third_octave

__all__ = ["Curve", "Result", "build"]

WP_NAMES = {"WA": "Willmarth-Roos-Amiet", "CH": "Chase-Howe", "GY": "Goody", "KG": "Kim-George",
            "RZ": "Rozenberg", "VKI": "VKI (GEP)"}
UC_NAMES = {"0.8": "U_c = 0.8 U", "GLB": "Gliebe U_c", "DEL": "del Alamo U_c", "DEL2": "del Alamo fit U_c"}
LR_NAMES = {"COR": "Corcos l_y", "CORL": "Corcos/delta l_y", "ROG": "Roger l_y", "LGL": "Roger(delta) l_y",
            "RGS": "Roger (A = 1.10) l_y", "EFP": "Efimtsov l_y", "SLZ": "Salze l_y"}


@dataclass
class Curve:
    key: str                     # interaction | self_front | self_rear | ingestion_total | ...
    source: str                  # interaction | self | ingestion
    rotor: str                   # front | rear
    label: str
    model: str
    psd: np.ndarray              # [theta, f]  one-sided, Pa^2/Hz
    pwl: np.ndarray | None = None        # [f] sound power spectral density, W/Hz
    strips: dict | None = None           # r [m], psd [strip, f] at the first observer angle
    in_total: bool = True

    def oaspl(self, f):
        return np.array([10 * math.log10(max(np.trapezoid(p, f), 1e-300) / P_REF ** 2) for p in self.psd])

    def to_dict(self, f):
        d = {"key": self.key, "source": self.source, "rotor": self.rotor, "label": self.label,
             "model": self.model, "psd": self.psd.tolist(), "oaspl": self.oaspl(f).tolist(),
             "in_total": self.in_total}
        if self.pwl is not None:
            d["pwl"] = self.pwl.tolist()
            d["pwl_total_db"] = 10 * math.log10(max(np.trapezoid(self.pwl, f), 1e-300) / W_REF)
        if self.strips is not None:
            d["strips"] = {"r": self.strips["r"].tolist(), "psd": self.strips["psd"].tolist()}
        fc, band = third_octave(f, self.psd[0])
        d["third_octave"] = {"fc": fc.tolist(), "spl": (10 * np.log10(np.maximum(band, 1e-300) / P_REF ** 2)).tolist()}
        return d


@dataclass
class Result:
    f: np.ndarray
    theta_deg: np.ndarray
    curves: list = field(default_factory=list)
    rotors: dict = field(default_factory=dict)
    raw: list = field(default_factory=list)          # (purpose, solver output)

    def total(self):
        """Energy sum of the curves marked in_total, [theta, f]."""
        sel = [c.psd for c in self.curves if c.in_total]
        return np.sum(sel, axis=0) if sel else None

    def to_dict(self):
        tot = self.total()
        out = {"f": self.f.tolist(), "theta_deg": self.theta_deg.tolist(),
               "curves": [c.to_dict(self.f) for c in self.curves], "rotors": self.rotors}
        if tot is not None:
            out["total"] = {"psd": tot.tolist(),
                            "oaspl": [10 * math.log10(max(np.trapezoid(p, self.f), 1e-300) / P_REF ** 2) for p in tot]}
        return out

    def summary(self):
        lines = []
        for c in self.curves:
            o = c.oaspl(self.f)
            lines.append(f"  {c.label:58s} OASPL {o[0]:6.1f} dB at theta* = {self.theta_deg[0]:g} deg"
                         + (f"   PWL {10 * math.log10(max(np.trapezoid(c.pwl, self.f), 1e-300) / W_REF):6.1f} dB"
                            if c.pwl is not None else ""))
        tot = self.total()
        if tot is not None and len(self.curves) > 1:
            o = 10 * math.log10(max(np.trapezoid(tot[0], self.f), 1e-300) / P_REF ** 2)
            lines.append(f"  {'total':58s} OASPL {o:6.1f} dB")
        return "\n".join(lines)


def _psd(S, st, g=0):
    S = np.asarray(S)
    S = S[..., None] if S.ndim == 3 else S
    return 4 * math.pi * np.abs(S[:, :, st, g]).T, 4 * math.pi * np.abs(S[:, 0, :st, g]).T


def _rotor_info(out):
    g, fl, o = out.geom, out.flow, out.opt
    st = int(o["st_num"])
    info = {}
    for rot, name in enumerate(["front", "rear"][:int(o["StageCount"])]):
        U = fl.U_X2[:, 0] if (rot == 1 and np.any(fl.U_X2)) else fl.Ux[:, rot, 0]
        info[name] = {"blades": float(g.B[rot]), "rpm": float(g.OM[rot] * 30 / math.pi),
                      "bpf_hz": float(g.B[rot] * g.OM[rot] / (2 * math.pi)),
                      "strips": [{"r": float(g.rj[j, rot]), "chord": float(g.C[j, rot]),
                                  "stagger_deg": float(np.degrees(g.alpha[j, rot])), "U": float(U[j]),
                                  "M": float(U[j] / fl.c0)} for j in range(st)]}
    return info


def build(case, outs):
    nm = case.get("noise_model", {})
    sel = nm.get("self_noise", [])
    sel = ["front", "rear"] if sel is True else ([sel] if isinstance(sel, str) else list(sel or []))
    res = None
    for purpose, out in outs:
        o = out.opt
        lists = out.lists if out.lists is not None else out.p.lists
        f = np.asarray(lists.omega, float) / (2 * math.pi) / lists.scale
        if res is None:
            res = Result(f=f, theta_deg=np.round(np.degrees(np.atleast_1d(np.asarray(o["theta"], float))), 6))
        res.raw.append((purpose, out))
        st = int(o["st_num"])
        if out.geom is not None:
            res.rotors.update(_rotor_info(out))
            g = out.geom
            if isinstance(out.Spps.get("BRWI"), np.ndarray):
                psd, strips = _psd(out.Spps["BRWI"], st)
                P1 = sound_power(out.lists, o, g, out.flow, np.asarray(out.Spps["BRWI"]))
                spec = "von Karman" if o.get("Karman_spec", True) else "Liepmann"
                res.curves.append(Curve("interaction", "interaction", "rear",
                                        "rear rotor: rotor-wake interaction (BRWI)", f"{spec} spectrum",
                                        psd, 4 * math.pi * np.abs(P1[:, st]) * lists.scale ** 3,
                                        {"r": g.rj[:, 1].copy(), "psd": strips}))
            for key, rot, name in (("BRTE1", 0, "front"), ("BRTE2", 1, "rear")):
                if isinstance(out.Spps.get(key), np.ndarray) and name in sel:
                    S = np.asarray(out.Spps[key])
                    psd, strips = _psd(S, st)
                    P1 = sound_power(out.lists, o, g, out.flow, S[..., 0])
                    form = "simplified" if o.get("amiet") else "full"
                    model = f"{WP_NAMES[o['phi_sw']]}, {UC_NAMES[o['Uc']]}, {LR_NAMES[o['lr']]}, {form}"
                    res.curves.append(Curve(f"self_{name}", "self", name,
                                            f"{name} rotor: trailing-edge noise (BRTE)", model, psd,
                                            4 * math.pi * np.abs(P1[:, st]) * lists.scale ** 3,
                                            {"r": g.rj[:, rot].copy(), "psd": strips}))
        if out.p is not None:
            S = {k: out.Spps[k] for k in ("BPRI", "BPRINW", "BPRIC1", "BPRIC2", "BPRIA")}
            az = np.degrees(np.atleast_1d(np.asarray(out.p.lists.offset_list, float)))
            spec = "von Karman" if o.get("Karman_spec", True) else "Liepmann"
            for gi in range(az.size):
                suffix = "" if az.size == 1 else f" (azimuth {az[gi]:g} deg)"
                for k, var in (("BPRI", "total"), ("BPRINW", "no wall"), ("BPRIC1", "interference C1"),
                               ("BPRIC2", "interference C2"), ("BPRIA", "image source")):
                    psd, strips = _psd(S[k], st, gi)
                    res.curves.append(Curve(f"ingestion_{k[4:].lower() or 'total'}{'' if gi == 0 else f'_{gi}'}",
                                            "ingestion", "front", f"BL ingestion: {var}{suffix}",
                                            f"{spec} spectrum, simplified", psd, None,
                                            {"r": out.p.geom.rj[:, 1].copy(), "psd": strips},
                                            in_total=(k == "BPRI" and gi == 0)))
    return res
