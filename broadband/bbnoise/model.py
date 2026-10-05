"""Case description, execution and results.

A *case* is a plain dictionary (loaded from TOML/JSON, built by the web
interface, or taken from :mod:`bbnoise.cases`).  Three case types exist:

``airfoil``     stationary flat plate: leading-edge noise in homogeneous turbulence
                (Amiet 1975, section ``turbulence``) and/or trailing-edge noise
                (Amiet 1976, section ``brte``); ``airfoil_le`` and ``airfoil_te``
                are accepted aliases
``rotor``       one or two rotors with any of the mechanisms
                  * ``brte``   broadband rotor trailing-edge (self) noise
                  * ``ingestion``  homogeneous turbulence ingestion
                  * ``brwi``   broadband rotor-wake/rotor interaction noise of the rear rotor (CROR)
                The section names follow the thesis (BRTE, BRWI); the earlier ``self_noise`` and
                ``rwi`` are still accepted (:func:`normalise_case`).  Each rotor may have radial
                chord, stagger (``stagger_deg``) and chordwise speed (``U_X``) distributions.

Every combination of formulation (full / simplified), turbulence spectrum
(von Karman / Liepmann) and wall-pressure model requested produces one curve.
Spectra are returned as one-sided PSDs per hertz in dB re (20 uPa)^2/Hz,
together with 1/3-octave band levels, OASPL and (for rotors) directivity and
sound power.  Every curve is tagged ``interaction`` (leading-edge mechanisms)
or ``self`` (trailing edge); ``totals`` add, for each formulation, the first
listed variant of every mechanism: interaction total, self-noise total and
their sum.

Turbulence levels (``turbulence``, ``ingestion``) are given by ``tke`` [m^2/s^2]
(isotropic, w_rms = sqrt(2 k/3)), ``w_rms`` [m/s] or ``intensity`` (w_rms/U).
Front-rotor wakes (``brwi.wake``) are given by the centreline TKE ``tke_c``, the
passage-averaged TKE ``tke_mean`` or the centreline intensity ``tu_c`` (of the
front-blade relative velocity), with the integral length scale ``Lambda`` [m] or
``Lambda_over_Lw``.  These may vary with radius as {"r_over_R": [...], "value": [...]}.
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
from .turbulence import LN2, HomogeneousTurbulence, WakeTurbulence, w_rms_from_tke
from .wallpressure import wps

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
    category: str = ""               # interaction, self or total
    strips: dict | None = None       # per-strip PSDs at the main observer: r, dr, chord, G (n_strips x n_f)


@dataclass
class CaseResult:
    name: str
    case: dict
    f: np.ndarray
    curves: list = field(default_factory=list)
    totals: list = field(default_factory=list)
    info: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    seconds: float = 0.0

    def to_dict(self, digits=5):
        def r(a):
            a = np.asarray(a, float)
            return [None if not np.isfinite(v) else float(f"{v:.{digits}g}") for v in a.ravel()]
        out = {"name": self.name, "info": self.info, "warnings": self.warnings,
               "seconds": round(self.seconds, 3), "f": r(self.f), "curves": [], "totals": []}
        for c in self.curves + self.totals:
            fc, band = third_octave(self.f, c.G)
            d = {"label": c.label, "category": c.category, "mechanism": c.mechanism, "formulation": c.formulation,
                 "variant": c.variant, "rotor": c.rotor, "theta_deg": c.theta_deg,
                 "psd_db": r(_db_psd(c.G)), "oaspl": round(_oaspl(self.f, c.G), 2),
                 "third_octave": {"fc": r(fc), "spl": r(band)}}
            if c.directivity:
                d["directivity"] = {"theta": r(c.directivity["theta"]), "oaspl": r(c.directivity["oaspl"])}
            if c.strips is not None:
                Gs = np.asarray(c.strips["G"])
                e = np.trapezoid(Gs, self.f, axis=1)
                tot = max(float(e.sum()), 1e-300)
                d["strips"] = {"r": r(c.strips["r"]), "dr": r(c.strips["dr"]), "chord": r(c.strips["chord"]),
                               "U": r(c.strips["U"]),
                               "oaspl": r(10 * np.log10(np.maximum(e, 1e-30) / P_REF ** 2)),
                               "share": r(e / tot),
                               "psd_db": [r(_db_psd(g)) for g in Gs]}
            if c.pwl is not None:
                d["pwl_db"] = r(10 * np.log10(np.maximum(c.pwl, 1e-40) / W_REF))
                d["pwl_total"] = round(float(10 * np.log10(max(np.trapezoid(c.pwl, self.f), 1e-40) / W_REF)), 2)
            out["totals" if c.category == "total" else "curves"].append(d)
        return out

    def summary(self):
        lines = [f"{self.name}  ({len(self.curves)} curves, {self.seconds:.1f} s)"]
        for c in self.curves + self.totals:
            lines.append(f"  {c.label:60s} OASPL {_oaspl(self.f, c.G):6.1f} dB  (theta = {c.theta_deg:g} deg)")
        for w in self.warnings:
            lines.append(f"  warning: {w}")
        return "\n".join(lines)

    def table(self):
        """Columns: f, PSD dB/Hz of each curve (for CSV output)."""
        cs = self.curves + self.totals
        header = ["f_Hz"] + [c.label for c in cs]
        rows = np.column_stack([self.f] + [_db_psd(c.G) for c in cs])
        return header, rows


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------

NICE = {"vonkarman": "von Karman", "liepmann": "Liepmann", "amiet": "Amiet WPS", "chase_howe": "Chase-Howe",
        "goody": "Goody", "rozenberg": "Rozenberg", "kamruzzaman": "Kamruzzaman", "lee": "Lee",
        "dominique_gep": "VKI GEP", "kim_george": "Kim-George", "rozenberg_2010": "Rozenberg (2010, thesis)"}


def _nice(var):
    for k in sorted(NICE, key=len, reverse=True):       # longest key first (rozenberg_2010 before rozenberg)
        if var.startswith(k):
            return NICE[k] + var[len(k):]
    return var


def _as_list(v):
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def build_rotor(spec, fluid):
    """Rotor from a case entry.  The chord (and optionally Ux, stagger_deg and U_X) may come from a
    blade table: ``blade_file`` (path) or ``blade_table`` (text), see :mod:`bbnoise.tables`."""
    chord, Ux = spec.get("chord"), spec.get("Ux", 0.0)
    stagger, UX = spec.get("stagger_deg"), spec.get("U_X")
    if spec.get("blade_table") or spec.get("blade_file"):
        from pathlib import Path
        from .tables import blade_from_table
        text = spec.get("blade_table") or Path(spec["blade_file"]).read_text()
        blade = blade_from_table(text, float(spec["r_tip"]))
        chord = blade["chord"]
        Ux = blade.get("Ux", Ux)
        stagger = blade.get("stagger_deg", stagger)
        UX = blade.get("U_X", UX)
    if chord is None:
        raise ValueError(f"rotor {spec.get('name', '')!r}: give a chord or a blade table")
    return Rotor(B=int(spec["B"]), r_tip=float(spec["r_tip"]), r_hub=float(spec.get("r_hub", 0.2 * spec["r_tip"])),
                 chord=chord, rpm=float(spec["rpm"]), Ux=Ux,
                 flight_speed=spec.get("flight_speed"), n_strips=int(spec.get("n_strips", 10)),
                 c0=fluid["c0"], rho=fluid["rho"], name=spec.get("name", "rotor"),
                 strip_edges=spec.get("strip_edges"), stagger_deg=_blank_none(stagger), U_X=_blank_none(UX))


def _blank_none(v):
    return None if v is None or v == "" else v


def _te_source(bl_spec, model, opts, fluid, sn, r_tip=None):
    def bls(strip):
        return make_boundary_layers(bl_spec, strip.chord, strip.U, fluid["rho"], fluid["nu"], fluid["c0"],
                                    r_over_R=None if r_tip is None else strip.r / r_tip, r_tip=r_tip)
    return TESource(bls, model=model, Uc_over_Ue=sn.get("Uc_over_Ue", 0.7), b_c=sn.get("b_c", 1.47),
                    backscatter=opts["backscatter"], sides=tuple(sn.get("sides", ("suction", "pressure"))),
                    k_min=float(sn.get("k_min", 0.05)))


def _homogeneous(tb, spectrum, default_intensity, default_Lambda):
    """Homogeneous turbulence from 'tke' [m^2/s^2], 'w_rms' [m/s] or 'intensity'."""
    w = None
    if tb.get("tke") is not None:
        w = w_rms_from_tke(tb["tke"])
    elif tb.get("w_rms") is not None:
        w = float(tb["w_rms"])
    return HomogeneousTurbulence(spectrum, float(tb.get("intensity", default_intensity)),
                                 float(tb.get("Lambda", default_Lambda)), tb.get("U_ref"), w)


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

    tke_c = wake.get("tke_c")
    tke_mean = wake.get("tke_mean")

    def w_c(r):
        if r > front.r_tip or r < front.r_hub:
            return 0.0
        if tke_c is not None:
            return w_rms_from_tke(_prop_at(tke_c, r, front))
        if tke_mean is not None:
            # passage mean w^2 = w_c^2 (Lw/s) sqrt(pi/ln2)
            wm2 = w_rms_from_tke(_prop_at(tke_mean, r, front)) ** 2
            return math.sqrt(wm2 / (lw(r) * math.sqrt(math.pi / LN2)))
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


def _enabled(sec, default=True):
    return bool(sec) and sec.get("enabled", default)


def _wps_info(bls, models, f):
    """One-sided point spectra (dB re (20 uPa)^2/Hz) of the wall-pressure models for a BL pair."""
    return {side: {m: _db_psd(wps(m, 2 * np.pi * f, bl) * 2 * np.pi).tolist() for m in models}
            for side, bl in bls.items()}


def _run_airfoil(case, res, f, opts, fluid, progress):
    af = case["airfoil"]
    U = float(af["U"])
    # a stationary strip: Omega = 0 and the free stream enters through the axial speed
    strip = Strip(0, 0.0, float(af["span"]), float(af["chord"]), 0.0, U, fluid["c0"], fluid["rho"])
    obs = case.get("observers", {"R": 1.0, "theta_deg": [90.0]})
    thetas = _as_list(obs.get("theta_deg", [90.0]))
    th0 = thetas[0]
    omega = 2 * np.pi * f
    res.info.update({"chord": strip.chord, "span": strip.dr, "U": U, "M": strip.M})
    variants = []
    tb = case.get("turbulence")
    if _enabled(tb, case.get("type") != "airfoil_te"):
        for spec in _as_list(tb.get("spectrum", "vonkarman")):
            ht = _homogeneous(tb, spec, 0.05, 0.03)
            src = LESource(ht, method=opts["le_method"], second_order=opts["second_order"])
            variants.append(("leading-edge (Amiet 1975)", spec, src, "interaction"))
        w = ht.level(U)
        res.info["turbulence"] = {"w_rms": w, "tke": 1.5 * w * w, "Lambda": ht.Lambda, "intensity": w / U}
    sn = case.get("brte")
    if _enabled(sn, case.get("type") != "airfoil_le"):
        bl_spec = sn.get("boundary_layer", {"method": "bpm"})
        models = _as_list(sn.get("models", "goody"))
        for model in models:
            src = _te_source(bl_spec, model, opts, fluid, sn)
            variants.append(("trailing-edge (Amiet 1976)", model, src, "self"))
        bls = make_boundary_layers(bl_spec, strip.chord, U, fluid["rho"], fluid["nu"], fluid["c0"])
        res.info["boundary_layers"] = {"airfoil": {k: _bl_info(v) for k, v in bls.items()}}
        res.info["wall_pressure"] = {"airfoil": _wps_info(bls, models, f)}
    for mech, var, src, cat in variants:
        if progress:
            progress(f"{mech}: {var}")
        S = stationary_spectrum(strip, src, omega, _airfoil_observer(obs, th0))
        G = S * src.spectral_factor
        direc = None
        if opts.get("directivity", True) and len(thetas) > 1:
            direc = {"theta": np.asarray(thetas, float), "oaspl": np.array([
                _oaspl(f, stationary_spectrum(strip, src, omega, _airfoil_observer(obs, t)) * src.spectral_factor)
                for t in thetas])}
        res.curves.append(Curve(f"{mech} - {_nice(var)}", mech, "stationary", var, "airfoil", th0, G, direc,
                                category=cat))


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

    sn = case.get("brte")
    if _enabled(sn):
        models = _as_list(sn.get("models", "goody"))

        def bl_for(rname):
            # per-rotor specification (brte.boundary_layers.<rotor>) overrides the shared one
            return (sn.get("boundary_layers") or {}).get(rname) or sn.get("boundary_layer", {"method": "bpm"})

        for rname in _as_list(sn.get("rotors", list(rotors))):
            for model in models:
                jobs.append(("BRTE (trailing edge)", model, rname,
                             _te_source(bl_for(rname), model, opts, fluid, sn, rotors[rname].r_tip), "self"))
        # boundary layer and wall-pressure spectra at mid-span of every rotor
        for rname in _as_list(sn.get("rotors", list(rotors))):
            rot = rotors[rname]
            st = rot.strips()
            mid = st[len(st) // 2]
            bls = make_boundary_layers(bl_for(rname), mid.chord, mid.U, fluid["rho"], fluid["nu"], fluid["c0"],
                                       r_over_R=mid.r / rot.r_tip, r_tip=rot.r_tip)
            # radial distribution of the boundary layers used (trailing edge of every strip)
            dist = {"r": [], "chord": []}
            for st in rot.strips():
                b = make_boundary_layers(bl_for(rname), st.chord, st.U, fluid["rho"], fluid["nu"], fluid["c0"],
                                         r_over_R=st.r / rot.r_tip, r_tip=rot.r_tip)
                dist["r"].append(st.r)
                dist["chord"].append(st.chord)
                for side, bb in b.items():
                    for k, v in _bl_info(bb).items():
                        dist.setdefault(f"{side}_{k}", []).append(v)
            res.info.setdefault("bl_distribution", {})[rname] = dist
            res.info.setdefault("boundary_layers", {})[rname] = {k: _bl_info(v) for k, v in bls.items()}
            res.info.setdefault("wall_pressure", {})[rname] = _wps_info(bls, models, f)

    ing = case.get("ingestion")
    if _enabled(ing):
        for rname in _as_list(ing.get("rotors", list(rotors)[:1])):
            for spec in _as_list(ing.get("spectrum", "vonkarman")):
                tb = _homogeneous(ing, spec, 0.02, 0.1)
                jobs.append(("turbulence ingestion (LE)", spec, rname,
                             LESource(tb, opts["le_method"], opts["second_order"]), "interaction"))
        rot = rotors[_as_list(ing.get("rotors", list(rotors)[:1]))[0]]
        mid = rot.strips()[len(rot.strips()) // 2]
        w = tb.level(mid.U)
        res.info["turbulence"] = {"w_rms": w, "tke": 1.5 * w * w, "Lambda": tb.Lambda, "intensity": w / mid.U}

    rwi = case.get("brwi")
    if _enabled(rwi) and len(rotors) < 2:
        res.warnings.append("rotor-wake interaction needs a front and a rear rotor; skipped")
    elif _enabled(rwi):
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
                src = LESource(wt, opts["le_method"], opts["second_order"])
                src.front_rotor = front
                jobs.append(("BRWI (rotor-wake interaction)", var, rear_name, src, "interaction"))
        res.info["wake_passing_hz"] = front.B * (front.Omega + rear.Omega) / (2 * np.pi)
        rs = np.array([x.r for x in rear.strips()])
        prm = [wt.wake_params(x) for x in rs]
        res.info["wake"] = {"r": rs.tolist(), "s1": [p[0] for p in prm], "Lw": [p[1] for p in prm],
                            "Lambda": [p[2] for p in prm], "w_c": [p[3] for p in prm],
                            "tke_c": [1.5 * p[3] ** 2 for p in prm],
                            "tke_mean": [1.5 * wt.mean_square(x) for x in rs]}

    kw = {"n_psi": int(opts["n_psi"]), "doppler_exponent": float(opts["doppler_exponent"]),
          "spanwise": bool(opts.get("spanwise", True))}
    thesis_forms = [f for f in formulations if f in THESIS_FORMS + THESIS_RWI_FORMS]
    if thesis_forms and any(r.Mx > 1e-6 for r in rotors.values()):
        res.warnings.append("thesis eqs. 2.73 / 3.18 / 5.7 assume a medium at rest (as in the thesis); flight "
                            "convection is ignored for those curves")
    tsign = float(opts.get("thesis_doppler_sign", 1.0))

    def spec(form, rot, src, th_up, per_strip=False):
        """One spectrum (native convention) at polar angle th_up from the upstream axis."""
        if form in THESIS_FORMS:
            from . import thesis
            fn = thesis.eq318_spectrum if form == "eq3.18" else thesis.eq57_spectrum
            return fn(rot, src.bls, src.model, omega, R, 180.0 - th_up, per_strip=per_strip, doppler_sign=tsign)
        if form in THESIS_RWI_FORMS:
            from . import thesis
            wt, front = src.turbulence, src.front_rotor
            return thesis.eq273_spectrum(rot, _thesis_wake(wt), front.B, front.Omega, omega, R, 180.0 - th_up,
                                         per_strip=per_strip, doppler_sign=tsign, spectrum=wt.spectrum)
        return rotor_spectrum(rot, src, omega, observer_position(R, th_up), form, per_strip=per_strip, **kw)

    def factor(form, src):
        if form in THESIS_FORMS:
            from .thesis import SPECTRAL_FACTOR
            return SPECTRAL_FACTOR
        if form in THESIS_RWI_FORMS:
            from .thesis import SPECTRAL_FACTOR
            return SPECTRAL_FACTOR * (2 * np.pi if opts.get("thesis_brwi_2pi", False) else 1.0)
        return src.spectral_factor

    for mech, var, rname, src, cat in jobs:
        rot = rotors[rname]
        for form in formulations:
            if form in THESIS_FORMS and cat != "self":
                continue                     # eqs. 3.18 / 5.7 are for trailing-edge noise
            if form in THESIS_RWI_FORMS and not (cat == "interaction" and hasattr(src, "front_rotor")):
                continue                     # eq. 2.73 is for rotor-wake interaction noise
            if progress:
                progress(f"{rname}: {mech}, {var}, {form}")
            fac = factor(form, src)
            G, parts = spec(form, rot, src, th0, per_strip=True)
            G = G * fac
            sts = rot.strips()
            strips = {"r": [s.r for s in sts], "dr": [s.dr for s in sts], "chord": [s.chord for s in sts],
                      "U": [s.U for s in sts], "G": np.asarray(parts) * fac}
            direc = None
            if opts.get("directivity", True) and len(thetas) > 1:
                vals = [_oaspl(f, G if float(t) == th0 else spec(form, rot, src, float(t)) * fac) for t in thetas]
                direc = {"theta": np.asarray(thetas, float), "oaspl": np.asarray(vals)}
            pwl = None
            if opts.get("sound_power", False):
                n_th = int(opts.get("n_theta", 13))
                th = np.linspace(0.0, 180.0, n_th)
                th[0], th[-1] = 0.5, 179.5
                vals = np.array([spec(form, rot, src, t) for t in th]) * fac
                integrand = vals * np.sin(np.radians(th))[:, None]
                pwl = 2 * np.pi * R * R * np.trapezoid(integrand, np.radians(th), axis=0) / (rot.rho * rot.c0)
            label = f"{rname}: {mech} - {_nice(var)} - {FORM_LABEL.get(form, form)}"
            res.curves.append(Curve(label, mech, form, var, rname, th0, G, direc, pwl, category=cat,
                                    strips=strips))


THESIS_FORMS = ("eq3.18", "eq5.7")          # trailing-edge (self) noise, thesis ch. 3 and 5
THESIS_RWI_FORMS = ("eq2.73",)               # rotor-wake interaction noise, thesis ch. 2
FORM_LABEL = {"eq3.18": "thesis eq. 3.18", "eq5.7": "thesis eq. 5.7 (Amiet)", "eq2.73": "thesis eq. 2.73"}
# interaction noise paired with the thesis self-noise formulations in the totals
# (thesis eq. 2.73 when it was run, as in the thesis' chapter 4; otherwise full / simplified)
INTERACTION_FOR = {"eq3.18": "full", "eq5.7": "simplified"}


def _thesis_wake(wt):
    """wake(r) -> (w_rms, L, b_W) for thesis eq. 2.73 from a WakeTurbulence.

    The periodic wake model here uses the half-width Lw of w^2 at half maximum; the thesis'
    profile exp(-a eta^2 / b_W^2) (a = 0.637) on the velocity gives Lw = b_W sqrt(ln 2 / (2 a))."""
    from .thesis import WAKE_A
    ratio = np.sqrt(np.log(2.0) / (2.0 * WAKE_A))

    def wake(r):
        _, Lw, Lam, wc = wt.wake_params(r)
        return wc, Lam, Lw / ratio
    return wake


def _sum_curves(parts, label, formulation):
    G = np.sum([c.G for c in parts], axis=0)
    direc = None
    if all(c.directivity for c in parts):
        th = np.asarray(parts[0].directivity["theta"])
        if all(np.array_equal(np.asarray(c.directivity["theta"]), th) for c in parts):
            e = np.sum([10 ** (np.asarray(c.directivity["oaspl"]) / 10) for c in parts], axis=0)
            direc = {"theta": th, "oaspl": 10 * np.log10(e)}
    pwl = np.sum([c.pwl for c in parts], axis=0) if all(c.pwl is not None for c in parts) else None
    variant = ", ".join(dict.fromkeys(f"{c.rotor} {_nice(c.variant)}" for c in parts))
    return Curve(label, "total", formulation, variant, "all", parts[0].theta_deg, G, direc, pwl, category="total")


def compute_totals(res: CaseResult):
    """For each formulation: interaction total, self-noise total and their sum, using the
    first listed variant of every (rotor, mechanism)."""
    res.totals = []
    rotor = res.case.get("type", "rotor") in ("rotor", "bob")
    # thesis names for rotors; stationary airfoils keep interaction / self noise
    I, S, T = ("BRWI", "BRTE", "BRWI + BRTE") if rotor else ("interaction noise", "self noise", "interaction + self")
    inter_mechs = {c.mechanism for c in res.curves if c.category == "interaction"}
    if inter_mechs and all(m.startswith("BL ingestion") for m in inter_mechs):
        I, T = "BL ingestion", "BL ingestion + BRTE" if any(c.category == "self" for c in res.curves) else "BL ingestion"
    forms = list(dict.fromkeys(c.formulation for c in res.curves))
    thesis_rwi = next((f for f in forms if f in THESIS_RWI_FORMS), None)
    for form in forms:
        # the thesis TE equations only give self noise: pair them with the thesis (eq. 2.73), or else the
        # full / simplified, interaction noise
        if form in THESIS_RWI_FORMS and any(f in THESIS_FORMS for f in forms):
            continue
        iform = thesis_rwi if (form in THESIS_FORMS and thesis_rwi) else INTERACTION_FOR.get(form, form)
        first = {}
        for c in res.curves:
            if (c.category == "self" and c.formulation == form) or (c.category == "interaction" and c.formulation == iform):
                first.setdefault((c.rotor, c.mechanism), c)
        chosen = list(first.values())
        inter = [c for c in chosen if c.category == "interaction"]
        selfn = [c for c in chosen if c.category == "self"]
        iname = FORM_LABEL.get(iform, iform) if iform in THESIS_RWI_FORMS else iform
        name = FORM_LABEL.get(form, form) + (f" + {iname} BRWI" if iform != form and inter else "")
        if inter and selfn:
            res.totals.append(_sum_curves(inter, f"total {I} - {name}", form))
            res.totals.append(_sum_curves(selfn, f"total {S} - {name}", form))
        if inter or selfn:
            res.totals.append(_sum_curves(inter + selfn, f"total ({T}) - {name}", form))
    return res.totals


SECTION_ALIASES = {"self_noise": "brte", "rwi": "brwi"}


def normalise_case(case: dict) -> dict:
    """Rename the earlier section names (``self_noise`` -> ``brte``, ``rwi`` -> ``brwi``) in place."""
    for old, new in SECTION_ALIASES.items():
        if old in case:
            val = case.pop(old)
            case.setdefault(new, val)
    return case


def run_case(case: dict, progress=None) -> CaseResult:
    """Run a case dictionary and return a :class:`CaseResult`."""
    t0 = time.time()
    case = _merge({k: v for k, v in DEFAULTS.items()}, normalise_case(copy.deepcopy(case)))
    fluid = case["fluid"]
    opts = case["options"]
    f = frequencies(case["frequency"])
    res = CaseResult(case.get("name", "case"), case, f)
    res.info["description"] = case.get("description", "")
    res.info["reference"] = case.get("reference", "")
    ctype = case.get("type", "rotor")
    if ctype == "bob":
        from .bob.case import run_bob_case
        run_bob_case(case, res, progress)
        compute_totals(res)
        res.seconds = time.time() - t0
        return res
    if ctype in ("airfoil", "airfoil_le", "airfoil_te"):
        _run_airfoil(case, res, f, opts, fluid, progress)
    elif ctype == "rotor":
        _run_rotor(case, res, f, opts, fluid, progress)
    else:
        raise ValueError(f"unknown case type {ctype!r}")
    for c in res.curves:
        if not np.all(np.isfinite(c.G)):
            res.warnings.append(f"non-finite values in {c.label}")
            c.G = np.nan_to_num(c.G, nan=0.0, posinf=0.0)
    if not res.curves:
        res.warnings.append("no noise mechanism is enabled")
    compute_totals(res)
    res.seconds = time.time() - t0
    return res
