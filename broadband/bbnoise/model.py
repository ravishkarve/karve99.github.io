"""Case description, execution and results.

A *case* is a plain dictionary (loaded from TOML/JSON, built by the web
interface, or taken from :mod:`bbnoise.cases`).  Three case types exist:

``airfoil_le``  stationary flat plate in homogeneous turbulence (Amiet 1975)
``airfoil_te``  stationary flat plate trailing-edge noise (Amiet 1976)
``rotor``       one or two rotors with any of the mechanisms
                  * ``self_noise``          trailing-edge noise (full / simplified)
                  * ``ingestion``           homogeneous turbulence ingestion (full / simplified)
                  * ``rwi``                 rear-rotor / front-rotor-wake interaction (CROR)

Every combination of formulation (full / simplified), turbulence spectrum
(von Karman / Liepmann) and wall-pressure model requested produces one curve.
Spectra are returned as one-sided PSDs per hertz in dB re (20 uPa)^2/Hz,
together with 1/3-octave band levels, OASPL and (for rotors) directivity and
sound power.
"""
from __future__ import annotations

import copy
import math
import time
from dataclasses import dataclass, field

import numpy as np

from .boundarylayer import make_boundary_layers
from .rotor import Rotor, Strip, observer_position, rotor_spectrum, stationary_spectrum
from .sources import LESource, TESource
from .turbulence import HomogeneousTurbulence, WakeTurbulence

P_REF = 20e-6
W_REF = 1e-12

__all__ = ["run_case", "CaseResult", "third_octave", "frequencies", "DEFAULTS"]

DEFAULTS = {
    "fluid": {"c0": 340.0, "rho": 1.225, "nu": 1.5e-5},
    "frequency": {"f_min": 50.0, "f_max": 20000.0, "n": 40},
    "options": {"n_psi": 72, "doppler_exponent": 2.0, "le_method": "auto", "second_order": True,
                "backscatter": True, "spanwise": True, "directivity": True, "n_theta": 13,
                "sound_power": False},
}


# ---------------------------------------------------------------------------
# utilities
# ---------------------------------------------------------------------------

def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def frequencies(spec):
    if isinstance(spec, (list, tuple, np.ndarray)):
        return np.asarray(spec, float)
    n = int(spec.get("n", 40))
    if spec.get("spacing", "log") == "linear":
        return np.linspace(spec["f_min"], spec["f_max"], n)
    return np.geomspace(spec["f_min"], spec["f_max"], n)


def third_octave(f, G, f_min=None, f_max=None):
    """Integrate a one-sided PSD G(f) [Pa^2/Hz] into 1/3-octave bands (base-10 centres)."""
    f = np.asarray(f, float)
    G = np.asarray(G, float)
    f_min = f_min or f[0]
    f_max = f_max or f[-1]
    idx = np.arange(np.ceil(10 * np.log10(f_min * 2 ** (1 / 6))), np.floor(10 * np.log10(f_max / 2 ** (1 / 6))) + 1)
    fc = 10 ** (idx / 10)
    ok = G > 0
    if ok.sum() < 2:
        return fc, np.full_like(fc, np.nan)
    lf = np.log(f[ok])
    lg = np.log(G[ok])
    out = []
    for c in fc:
        lo, hi = c / 2 ** (1 / 6), c * 2 ** (1 / 6)
        ff = np.geomspace(lo, hi, 24)
        gg = np.exp(np.interp(np.log(ff), lf, lg))
        out.append(np.trapezoid(gg, ff))
    out = np.asarray(out)
    return fc, 10 * np.log10(np.maximum(out, 1e-30) / P_REF ** 2)


def _db_psd(G):
    return 10 * np.log10(np.maximum(G, 1e-30) / P_REF ** 2)


def _oaspl(f, G):
    return float(10 * np.log10(max(np.trapezoid(G, f), 1e-30) / P_REF ** 2))


@dataclass
class Curve:
    label: str
    mechanism: str
    formulation: str
    variant: str
    rotor: str
    theta_deg: float
    G: np.ndarray                    # one-sided PSD [Pa^2/Hz] at the main observer
    directivity: dict | None = None  # {'theta': [...], 'oaspl': [...]}
    pwl: np.ndarray | None = None    # sound power PSD [W/Hz]


@dataclass
class CaseResult:
    name: str
    case: dict
    f: np.ndarray
    curves: list = field(default_factory=list)
    info: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    seconds: float = 0.0

    def to_dict(self, digits=5):
        def r(a):
            a = np.asarray(a, float)
            return [None if not np.isfinite(v) else float(f"{v:.{digits}g}") for v in a.ravel()]
        out = {"name": self.name, "info": self.info, "warnings": self.warnings,
               "seconds": round(self.seconds, 3), "f": r(self.f), "curves": []}
        for c in self.curves:
            fc, band = third_octave(self.f, c.G)
            d = {"label": c.label, "mechanism": c.mechanism, "formulation": c.formulation,
                 "variant": c.variant, "rotor": c.rotor, "theta_deg": c.theta_deg,
                 "psd_db": r(_db_psd(c.G)), "oaspl": round(_oaspl(self.f, c.G), 2),
                 "third_octave": {"fc": r(fc), "spl": r(band)}}
            if c.directivity:
                d["directivity"] = {"theta": r(c.directivity["theta"]), "oaspl": r(c.directivity["oaspl"])}
            if c.pwl is not None:
                d["pwl_db"] = r(10 * np.log10(np.maximum(c.pwl, 1e-40) / W_REF))
                d["pwl_total"] = round(float(10 * np.log10(max(np.trapezoid(c.pwl, self.f), 1e-40) / W_REF)), 2)
            out["curves"].append(d)
        return out

    def summary(self):
        lines = [f"{self.name}  ({len(self.curves)} curves, {self.seconds:.1f} s)"]
        for c in self.curves:
            lines.append(f"  {c.label:60s} OASPL {_oaspl(self.f, c.G):6.1f} dB  (theta = {c.theta_deg:g} deg)")
        for w in self.warnings:
            lines.append(f"  warning: {w}")
        return "\n".join(lines)

    def table(self):
        """Columns: f, PSD dB/Hz of each curve (for CSV output)."""
        header = ["f_Hz"] + [c.label for c in self.curves]
        rows = np.column_stack([self.f] + [_db_psd(c.G) for c in self.curves])
        return header, rows


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------

NICE = {"vonkarman": "von Karman", "liepmann": "Liepmann", "amiet": "Amiet WPS", "chase_howe": "Chase-Howe",
        "goody": "Goody", "rozenberg": "Rozenberg", "kamruzzaman": "Kamruzzaman", "lee": "Lee",
        "dominique_gep": "VKI GEP"}


def _nice(var):
    for k, v in NICE.items():
        var = var.replace(k, v) if var.startswith(k) else var
    return var


def _as_list(v):
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def build_rotor(spec, fluid):
    return Rotor(B=int(spec["B"]), r_tip=float(spec["r_tip"]), r_hub=float(spec.get("r_hub", 0.2 * spec["r_tip"])),
                 chord=spec["chord"], rpm=float(spec["rpm"]), Ux=spec.get("Ux", 0.0),
                 flight_speed=spec.get("flight_speed"), n_strips=int(spec.get("n_strips", 10)),
                 c0=fluid["c0"], rho=fluid["rho"], name=spec.get("name", "rotor"),
                 strip_edges=spec.get("strip_edges"))


def _te_source(bl_spec, model, opts, fluid, sn):
    def bls(strip):
        return make_boundary_layers(bl_spec, strip.chord, strip.U, fluid["rho"], fluid["nu"], fluid["c0"])
    return TESource(bls, model=model, Uc_over_Ue=sn.get("Uc_over_Ue", 0.7), b_c=sn.get("b_c", 1.47),
                    backscatter=opts["backscatter"], sides=tuple(sn.get("sides", ("suction", "pressure"))),
                    k_min=float(sn.get("k_min", 0.05)))


def _wake_turbulence(rwi, front: Rotor, rear: Rotor, spectrum, fluid):
    wake = rwi.get("wake", {})
    Om_rel = front.Omega + rear.Omega if rwi.get("counter_rotating", True) else abs(front.Omega - rear.Omega)

    def prop(key, default):
        v = wake.get(key, default)
        return lambda r: _prop_at(v, r, front)

    tu = prop("tu_c", 0.08)
    lw = prop("Lw_over_s", 0.08)
    lam = wake.get("Lambda")
    lam_ratio = wake.get("Lambda_over_Lw", 0.42)
    from .rotor import _interp_prop

    def w_c(r):
        if r > front.r_tip or r < front.r_hub:
            return 0.0
        Ux1 = _interp_prop(front.Ux, r, front.r_hub, front.r_tip)
        U1 = math.hypot(front.Omega * r, Ux1)
        return tu(r) * U1

    return WakeTurbulence(B1=front.B, Omega_rel=Om_rel, w_c=w_c, Lw_over_s=lw,
                          Lambda=(lambda r: _prop_at(lam, r, front)) if lam is not None else None,
                          Lambda_over_Lw=lam_ratio, spectrum=spectrum,
                          model=wake.get("model", "periodic"), m_max=int(wake.get("m_max", 60)))


def _prop_at(v, r, rotor):
    from .rotor import _interp_prop
    return _interp_prop(v, r, rotor.r_hub, rotor.r_tip)


# ---------------------------------------------------------------------------
# runners
# ---------------------------------------------------------------------------

def _airfoil_observer(obs, theta):
    """Observer in the airfoil mid-span plane at angle theta from the downstream chord line."""
    th = np.radians(theta)
    R = obs.get("R", 1.0)
    return (R * np.cos(th), 0.0, R * np.sin(th))


def _run_airfoil(case, res, f, opts, fluid, progress):
    af = case["airfoil"]
    U = float(af["U"])
    strip = Strip(0, 0.0, float(af["span"]), float(af["chord"]), 0.0, U, fluid["c0"], fluid["rho"])
    # a stationary strip: U must be the free stream, so fake it through Ux with Omega = 0
    obs = case.get("observers", {"R": 1.0, "theta_deg": [90.0]})
    thetas = _as_list(obs.get("theta_deg", [90.0]))
    th0 = thetas[0]
    omega = 2 * np.pi * f
    res.info.update({"chord": strip.chord, "span": strip.dr, "U": U, "M": strip.M})
    variants = []
    if case["type"] == "airfoil_le":
        tb = case["turbulence"]
        for spec in _as_list(tb.get("spectrum", "vonkarman")):
            src = LESource(HomogeneousTurbulence(spec, tb.get("intensity", 0.05), tb.get("Lambda", 0.03)),
                           method=opts["le_method"], second_order=opts["second_order"])
            variants.append(("leading-edge (Amiet 1975)", spec, src))
    else:
        sn = case.get("self_noise", {})
        bl_spec = sn.get("boundary_layer", {"method": "bpm"})
        for model in _as_list(sn.get("models", "goody")):
            src = _te_source(bl_spec, model, opts, fluid, sn)
            variants.append(("trailing-edge (Amiet 1976)", model, src))
            if "boundary_layers" not in res.info:
                bls = src.bls(strip)
                res.info["boundary_layers"] = {k: _bl_info(v) for k, v in bls.items()}
    for mech, var, src in variants:
        if progress:
            progress(f"{mech}: {var}")
        S = stationary_spectrum(strip, src, omega, _airfoil_observer(obs, th0))
        G = S * src.spectral_factor
        direc = None
        if opts.get("directivity", True) and len(thetas) > 1:
            direc = {"theta": np.asarray(thetas, float), "oaspl": np.array([
                _oaspl(f, stationary_spectrum(strip, src, omega, _airfoil_observer(obs, t)) * src.spectral_factor)
                for t in thetas])}
        res.curves.append(Curve(f"{mech} - {_nice(var)}", mech, "stationary", var, "airfoil", th0, G, direc))


def _bl_info(bl):
    d = bl.as_dict()
    keep = ("Ue", "delta", "delta_star", "theta", "H", "cf", "tau_w", "beta_c", "Pi", "Rt", "RT_star",
            "Delta", "u_tau", "mach")
    return {k: float(d[k]) for k in keep}


def _run_rotor(case, res, f, opts, fluid, progress):
    rotors = {spec.get("name", f"rotor{i}"): build_rotor(spec, fluid) for i, spec in enumerate(case["rotors"])}
    res.info["rotors"] = {k: r.summary() for k, r in rotors.items()}
    obs = case.get("observers", {"R": 10.0, "theta_deg": [90.0]})
    R = float(obs.get("R", 10.0))
    thetas = _as_list(obs.get("theta_deg", [90.0]))
    th0 = float(thetas[0])
    formulations = _as_list(case.get("formulations", ["full", "simplified"]))
    omega = 2 * np.pi * f
    jobs = []   # (mechanism, variant, rotor_name, source)

    sn = case.get("self_noise")
    if sn and sn.get("enabled", True):
        bl_spec = sn.get("boundary_layer", {"method": "bpm"})
        for rname in _as_list(sn.get("rotors", list(rotors))):
            for model in _as_list(sn.get("models", "goody")):
                jobs.append(("self noise (TE)", model, rname, _te_source(bl_spec, model, opts, fluid, sn)))
        # boundary layer info at mid-span of every rotor
        for rname in _as_list(sn.get("rotors", list(rotors))):
            st = rotors[rname].strips()
            mid = st[len(st) // 2]
            bls = make_boundary_layers(bl_spec, mid.chord, mid.U, fluid["rho"], fluid["nu"], fluid["c0"])
            res.info.setdefault("boundary_layers", {})[rname] = {k: _bl_info(v) for k, v in bls.items()}

    ing = case.get("ingestion")
    if ing and ing.get("enabled", True):
        for rname in _as_list(ing.get("rotors", list(rotors)[:1])):
            for spec in _as_list(ing.get("spectrum", "vonkarman")):
                tb = HomogeneousTurbulence(spec, ing.get("intensity", 0.02), ing.get("Lambda", 0.1),
                                           ing.get("U_ref"))
                jobs.append(("turbulence ingestion (LE)", spec, rname,
                             LESource(tb, opts["le_method"], opts["second_order"])))

    rwi = case.get("rwi")
    if rwi and rwi.get("enabled", True):
        names = list(rotors)
        front = rotors[rwi.get("front", names[0])]
        rear_name = rwi.get("rear", names[-1])
        rear = rotors[rear_name]
        wake_models = _as_list(rwi.get("wake", {}).get("model", "periodic"))
        for spec in _as_list(rwi.get("spectrum", "vonkarman")):
            for wm in wake_models:
                r2 = copy.deepcopy(rwi)
                r2.setdefault("wake", {})["model"] = wm
                wt = _wake_turbulence(r2, front, rear, spec, fluid)
                var = spec if len(wake_models) == 1 else f"{spec}, {wm} wakes"
                jobs.append(("rotor-wake interaction (LE)", var, rear_name,
                             LESource(wt, opts["le_method"], opts["second_order"])))
        res.info["wake_passing_hz"] = front.B * (front.Omega + rear.Omega) / (2 * np.pi)

    x0 = observer_position(R, th0)
    kw = {"n_psi": int(opts["n_psi"]), "doppler_exponent": float(opts["doppler_exponent"]),
          "spanwise": bool(opts.get("spanwise", True))}
    for mech, var, rname, src in jobs:
        rot = rotors[rname]
        for form in formulations:
            if progress:
                progress(f"{rname}: {mech}, {var}, {form}")
            G = rotor_spectrum(rot, src, omega, x0, form, **kw) * src.spectral_factor
            direc = None
            if opts.get("directivity", True) and len(thetas) > 1:
                vals = []
                for t in thetas:
                    Gt = G if float(t) == th0 else rotor_spectrum(rot, src, omega, observer_position(R, float(t)),
                                                                  form, **kw) * src.spectral_factor
                    vals.append(_oaspl(f, Gt))
                direc = {"theta": np.asarray(thetas, float), "oaspl": np.asarray(vals)}
            pwl = None
            if opts.get("sound_power", False):
                from .rotor import sound_power
                pwl = sound_power(rot, src, omega, form, R=R, n_theta=int(opts.get("n_theta", 13)),
                                  **kw) * src.spectral_factor
            label = f"{rname}: {mech} - {_nice(var)} - {form}"
            res.curves.append(Curve(label, mech, form, var, rname, th0, G, direc, pwl))


def run_case(case: dict, progress=None) -> CaseResult:
    """Run a case dictionary and return a :class:`CaseResult`."""
    t0 = time.time()
    case = _merge({k: v for k, v in DEFAULTS.items()}, case)
    fluid = case["fluid"]
    opts = case["options"]
    f = frequencies(case["frequency"])
    res = CaseResult(case.get("name", "case"), case, f)
    res.info["description"] = case.get("description", "")
    res.info["reference"] = case.get("reference", "")
    ctype = case.get("type", "rotor")
    if ctype in ("airfoil_le", "airfoil_te"):
        _run_airfoil(case, res, f, opts, fluid, progress)
    elif ctype == "rotor":
        _run_rotor(case, res, f, opts, fluid, progress)
    else:
        raise ValueError(f"unknown case type {ctype!r}")
    for c in res.curves:
        if not np.all(np.isfinite(c.G)):
            res.warnings.append(f"non-finite values in {c.label}")
            c.G = np.nan_to_num(c.G, nan=0.0, posinf=0.0)
    res.seconds = time.time() - t0
    return res
