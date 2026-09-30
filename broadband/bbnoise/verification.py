"""Verification suite: analytic limits, identities and results from the literature.

Each check returns a :class:`Check` with the quantity compared, the value
obtained, the tolerance and the source of the expectation.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, asdict

import numpy as np
from scipy.integrate import quad

from .airfoil import amiet_qbar, le_response, te_response
from .boundarylayer import bpm, flat_plate
from .model import run_case
from .rotor import Rotor, full_spectrum, observer_position, simplified_spectrum
from .sources import LESource, TESource
from .special import Estar
from .thesis import SPECTRAL_FACTOR as THESIS_SPECTRAL_FACTOR, UC_OVER_UX, ZETA2, eq318_spectrum, eq57_spectrum
from .turbulence import HomogeneousTurbulence, Liepmann, VonKarman, WakeTurbulence
from .wallpressure import BoundaryLayer, wps_normalised

__all__ = ["Check", "run_all", "write_report"]


@dataclass
class Check:
    name: str
    description: str
    reference: str
    metric: str
    value: float
    tolerance: float
    passed: bool
    seconds: float = 0.0
    details: str = ""


def _check(name, description, reference, metric, value, tol, details="", mode="abs"):
    ok = bool(abs(value) <= tol) if mode == "abs" else bool(value >= tol)
    return Check(name, description, reference, metric, float(value), float(tol), ok, 0.0, details)


# ---------------------------------------------------------------------------
# individual checks
# ---------------------------------------------------------------------------

def check_spectrum_normalisation():
    err = 0.0
    for S in (VonKarman(2.0, 0.05), Liepmann(2.0, 0.05)):
        k = np.sinh(np.linspace(-14, 14, 4001)) / 0.05
        err = max(err, abs(np.trapezoid(S.phi_1d(k), k) / 4.0 - 1.0))
    return _check("turbulence_normalisation", "Double wavenumber integral of Phi_ww equals w_rms^2 "
                  "(von Karman and Liepmann)", "Amiet (1975); Blandeau (2011) ch. 2",
                  "max relative error", err, 2e-3)


def check_wake_energy():
    w = WakeTurbulence(B1=12, Omega_rel=1200.0, w_c=10.0, Lw_over_s=0.08)
    m, E2 = w.envelope_coefficients(0.25)
    err = abs(E2.sum() / w.mean_square(0.25) - 1.0)
    return _check("wake_envelope_energy", "Periodic Gaussian wake envelope: sum |E_m|^2 equals the "
                  "passage-averaged mean square w_c^2 (Lw/s) sqrt(pi/ln2)",
                  "Jurdic, Joseph & Antoni (2009); Blandeau (2011) ch. 5", "relative error", err, 1e-9)


def check_fresnel():
    err = 0.0
    for x in (0.3, 2.0, 17.0):
        re = quad(lambda t: np.cos(t) / np.sqrt(2 * np.pi * t), 0, x, limit=400)[0]
        im = -quad(lambda t: np.sin(t) / np.sqrt(2 * np.pi * t), 0, x, limit=400)[0]
        err = max(err, abs(Estar(x) - (re + 1j * im)))
    return _check("fresnel_integral", "E*(x) against direct quadrature", "Abramowitz & Stegun 7.3",
                  "max abs error", err, 1e-8)


def check_te_chord_integral():
    """Closed-form I1 = int_{-2}^{0} P1(X) e^{-iCX} dX - 1/(iC) (incident field in the wake)."""
    M, K, alpha = 0.2, 5.0, 1 / 0.7
    err = 0.0
    for xs in (0.0, 0.5, -0.7):
        mub = K * M / (1 - M * M)
        q = mub * (M - xs)
        B = alpha * K + mub * M + mub
        C = alpha * K + q
        f = lambda X: ((1 + 1j) * Estar(-X * B) - 1) * np.exp(-1j * C * X)
        num = quad(lambda X: f(X).real, -2, 0, limit=400)[0] + 1j * quad(lambda X: f(X).imag, -2, 0, limit=400)[0]
        num -= 1.0 / (1j * C)
        cf = te_response(K, alpha, 0.0, M, q, backscatter=False)
        err = max(err, abs(cf - num) / abs(num))
    return _check("te_radiation_integral", "Roger & Moreau closed-form I1 equals the chordwise integral of "
                  "Amiet's scattered pressure plus the incident field continued into the wake",
                  "Amiet (1976); Roger & Moreau (2005) JSV 286", "max relative error", err, 1e-6)


def check_le_low_frequency():
    """Sears limit and continuity of Amiet's two LE branches (jump < 2 dB)."""
    M = 0.3
    L = abs(le_response(np.array([1e-4]), 0.0, M, np.array([0.0]), "low"))[0]
    lim = 1.0 / np.sqrt(1 - M * M)
    # continuity of the high/low frequency branches at Amiet's switch (mubar = pi/4)
    Kx = np.pi / 4 * (1 - M * M) / M
    worst = 0.0
    for xs in (-0.5, 0.0, 0.5):
        q = amiet_qbar(np.array([Kx * M]), M, xs)
        lo = abs(le_response(np.array([Kx]), 0.0, M, q, "low"))[0] ** 2
        hi = abs(le_response(np.array([Kx]), 0.0, M, q, "high"))[0] ** 2
        worst = max(worst, abs(10 * np.log10(hi / lo)))
    return _check("le_response_limits", "Leading-edge response: |L| -> 1/beta (compressible Sears) as K -> 0; "
                  "high/low-frequency branches within 2 dB at Amiet's switch",
                  "Amiet (1975) JSV 41; Sears (1941)", "max of |L|beta-1 and dB jump/2 - 1",
                  max(abs(L / lim - 1.0), max(worst / 2.0 - 1.0, 0.0)), 1e-3,
                  details=f"|L|beta = {L / lim:.5f}, branch jump = {worst:.2f} dB")


def check_gep_vs_goody():
    bl = bpm(0.3048, 71.3)["suction"]
    w = np.geomspace(0.2, 5.0, 30)
    d = 10 * np.log10(wps_normalised("dominique_gep", w, bl) / wps_normalised("goody", w, bl))
    return _check("gep_zero_pressure_gradient", "VKI GEP model reproduces Goody's ZPG spectrum at mid "
                  "frequencies (0.2 < omega delta*/Ue < 5)", "Dominique et al. (2021) JSV 506; Goody (2004)",
                  "max |dB difference|", float(np.max(np.abs(d))), 2.0)


def check_rozenberg_goody():
    bl = BoundaryLayer(Ue=50.0, delta_star=0.002, delta=0.016, H=1.3, beta_c=0.0, Pi=0.2).complete()
    w = np.geomspace(0.05, 1.0, 20)
    d = 10 * np.log10(wps_normalised("rozenberg", w, bl) / wps_normalised("goody", w, bl))
    return _check("rozenberg_zpg_limit", "Rozenberg's model reduces to Goody's at zero pressure gradient "
                  "(Delta = 8, low/mid frequency)", "Rozenberg, Robert & Moreau (2012) AIAA J 50",
                  "max |dB difference|", float(np.max(np.abs(d))), 1.5)


def check_le_velocity_scaling():
    oa = []
    Us = (40.0, 165.0)
    for U in Us:
        case = {"type": "airfoil_le", "airfoil": {"chord": 0.23, "span": 0.53, "U": U},
                "turbulence": {"spectrum": "vonkarman", "intensity": 0.044, "Lambda": 0.031},
                "observers": {"R": 2.25, "theta_deg": [90]}, "frequency": {"f_min": 20, "f_max": 40000, "n": 80}}
        r = run_case(case).to_dict()
        oa.append(r["curves"][0]["oaspl"])
    slope = (oa[1] - oa[0]) / np.log10(Us[1] / Us[0])
    return _check("le_velocity_scaling", "Leading-edge noise of the Paterson & Amiet airfoil scales as "
                  "U^5 - U^6 (50-60 dB per decade)", "Paterson & Amiet (1976) NASA CR-2733",
                  "deviation of the slope from [50, 60] dB/decade", max(0.0, 50 - slope, slope - 60), 0.0,
                  details=f"slope = {slope:.1f} dB/decade")


def check_te_velocity_scaling():
    oa = []
    Us = (31.7, 71.3)
    for U in Us:
        case = {"type": "airfoil_te", "airfoil": {"chord": 0.3048, "span": 0.4572, "U": U},
                "self_noise": {"models": "goody", "boundary_layer": {"method": "bpm"}},
                "observers": {"R": 1.22, "theta_deg": [90]}, "frequency": {"f_min": 50, "f_max": 40000, "n": 80}}
        oa.append(run_case(case).to_dict()["curves"][0]["oaspl"])
    slope = (oa[1] - oa[0]) / np.log10(Us[1] / Us[0])
    return _check("te_velocity_scaling", "Trailing-edge noise of the BPM airfoil scales close to U^5 "
                  "(45-55 dB per decade)", "Ffowcs Williams & Hall (1970); Brooks, Pope & Marcolini (1989)",
                  "deviation of the slope from [45, 55] dB/decade", max(0.0, 45 - slope, slope - 55), 0.0,
                  details=f"slope = {slope:.1f} dB/decade")


class _PowerLaw:
    def __init__(self, a):
        self.a = a

    def force_spectrum(self, strip, w, q, ky):
        return (w / 1000.0) ** self.a


def check_doppler_kinematics():
    rot = Rotor(B=1, r_tip=1.0, r_hub=0.9, chord=1e-4, rpm=1948.0, Ux=0.0, n_strips=1)
    f = np.array([1000.0, 3000.0, 10000.0])
    worst = 0.0
    for a in (0, -2, -4):
        for th in (30, 60, 80):
            x = observer_position(100.0, th)
            d = 10 * np.log10(full_spectrum(rot, _PowerLaw(a), 2 * np.pi * f, x) /
                              simplified_spectrum(rot, _PowerLaw(a), 2 * np.pi * f, x, n_psi=720))
            worst = max(worst, float(np.max(np.abs(d))))
    return _check("doppler_kinematics", "Compact rotating dipole with power-law spectra: the simplified "
                  "formulation with the (w_s/w)^2 Doppler factor (reception-time observer) reproduces the "
                  "exact Bessel-series result for w >> Omega", "Blandeau & Joseph (2011) AIAA J 49; "
                  "Sinayoko, Kingan & Agarwal (2013) Proc. R. Soc. A 469", "max |dB difference|", worst, 0.25)


def check_full_vs_simplified():
    worst = 0.0
    rows = []
    for Ux in (0.0, 80.0):
        rot = Rotor(B=2, r_tip=1.0, r_hub=0.9, chord=0.1, rpm=1948.0, Ux=Ux, n_strips=1)
        for src in (LESource(HomogeneousTurbulence("vonkarman", 0.05, 0.05)),
                    TESource(lambda s: flat_plate(0.1, s.U))):
            f = np.array([500.0, 1000.0, 3000.0, 8000.0])
            for th in (30, 60, 120, 150):
                x = observer_position(50.0, th)
                d = 10 * np.log10(full_spectrum(rot, src, 2 * np.pi * f, x) /
                                  simplified_spectrum(rot, src, 2 * np.pi * f, x, n_psi=240))
                worst = max(worst, float(np.max(np.abs(d))))
                rows.append(f"Ux={Ux:g} {src.name[:14]} theta={th}: " + " ".join(f"{v:+.2f}" for v in d))
    return _check("full_vs_simplified", "Rotating flat plate at relative Mach 0.6: full and simplified (Amiet) "
                  "formulations agree above ~15 shaft orders for LE and TE noise, static and in flight",
                  "Blandeau & Joseph (2011) AIAA J 49(5); Blandeau (2011) ch. 3-4", "max |dB difference|",
                  worst, 0.5, details="; ".join(rows))


def check_low_frequency_departure():
    rot = Rotor(B=2, r_tip=1.0, r_hub=0.9, chord=0.1, rpm=1948.0, Ux=0.0, n_strips=1)
    src = TESource(lambda s: flat_plate(0.1, s.U))
    f = rot.shaft_frequency * np.linspace(1.0, 3.0, 25)   # K = omega b/U >= k_min
    x = observer_position(50.0, 80)
    d = np.abs(10 * np.log10(full_spectrum(rot, src, 2 * np.pi * f, x) /
                             simplified_spectrum(rot, src, 2 * np.pi * f, x)))
    ok = 0.1 < d.max() < 6.0
    return _check("low_frequency_departure", "Below ~3 shaft orders the formulations differ by a bounded "
                  "amount (0.1-6 dB): the simplified model is not exact there, and the full model stays "
                  "smooth (no hydrodynamic-coincidence spikes from evanescent modes)",
                  "Blandeau & Joseph (2011) AIAA J 49(5)", "max |dB difference| inside (0.1, 6)",
                  0.0 if ok else float(d.max()), 0.0, details=f"max |dB| = {d.max():.2f}")


def check_blade_count_linearity():
    base = Rotor(B=2, r_tip=0.5, r_hub=0.2, chord=0.05, rpm=3000.0, Ux=20.0, n_strips=3)
    dbl = Rotor(B=4, r_tip=0.5, r_hub=0.2, chord=0.05, rpm=3000.0, Ux=20.0, n_strips=3)
    src = LESource(HomogeneousTurbulence("liepmann", 0.05, 0.05))
    f = 2 * np.pi * np.array([500.0, 2000.0])
    x = observer_position(5.0, 70)
    d = 10 * np.log10(full_spectrum(dbl, src, f, x) / full_spectrum(base, src, f, x)) - 10 * np.log10(2)
    return _check("blade_count", "Uncorrelated blades: doubling B adds 3.01 dB", "Blandeau (2011) ch. 4",
                  "max |dB error|", float(np.max(np.abs(d))), 1e-6)


def _thesis_rotor(Ux):
    rot = Rotor(B=2, r_tip=1.0, r_hub=0.9, chord=0.1, rpm=1948.0, Ux=Ux, n_strips=1)
    return rot, (lambda s: flat_plate(s.chord, s.U))


def check_thesis_318_vs_57():
    rot, blf = _thesis_rotor(0.0)
    w = 2 * np.pi * np.array([1000.0, 3000.0, 8000.0])
    worst, rows = 0.0, []
    for th in (30, 60, 80, 100, 120, 150):
        d = 10 * np.log10(eq318_spectrum(rot, blf, "goody", w, 50.0, th) /
                          eq57_spectrum(rot, blf, "goody", w, 50.0, th))
        worst = max(worst, float(np.max(np.abs(d))))
        rows.append(f"theta={th}: " + " ".join(f"{v:+.3f}" for v in d))
    return _check("thesis_eq318_vs_eq57", "Thesis eq. 3.18 (exact BRTE) and eq. 5.7 (Amiet's approximate "
                  "model) agree above ~15 shaft orders, as concluded in the thesis' chapter 5",
                  "Blandeau (2011) eqs. 3.18, 5.7 and ch. 5; Blandeau & Joseph (2011) AIAA J 49(5)",
                  "max |dB difference|", worst, 0.3, details="; ".join(rows))


def check_thesis_318_vs_full():
    rot, blf = _thesis_rotor(0.0)
    src = TESource(blf, model="goody", Uc_over_Ue=UC_OVER_UX, b_c=ZETA2, backscatter=False, k_min=0.0)
    w = 2 * np.pi * np.array([1000.0, 3000.0, 8000.0])
    worst, rows = 0.0, []
    for th in (30, 60, 80, 100, 120, 150):     # not 90: a flat unstaggered blade is silent in its plane
        a = eq318_spectrum(rot, blf, "goody", w, 50.0, th, doppler_sign=-1.0) * THESIS_SPECTRAL_FACTOR
        m = full_spectrum(rot, src, w, observer_position(50.0, 180.0 - th), spanwise=False) * src.spectral_factor
        d = 10 * np.log10(a / m)
        worst = max(worst, float(np.max(np.abs(d))))
        rows.append(f"theta={th}: " + " ".join(f"{v:+.2f}" for v in d))
    return _check("thesis_eq318_vs_full", "Thesis eq. 3.18 with the Doppler shift paired as omega - l Omega "
                  "agrees with the independent full formulation (same Corcos scale, Uc, no back-scattering); "
                  "the residual comes from the thesis' 1/(b|kX| + b|kappa|) chordwise factor",
                  "Blandeau (2011) eqs. 3.15-3.20", "max |dB difference|", worst, 1.5, details="; ".join(rows))


def check_rozenberg2010_goody():
    bl = BoundaryLayer(Ue=50.0, delta_star=0.002, delta=0.016, H=1.3, beta_c=0.0, Pi=0.2).complete()
    w = np.geomspace(0.05, 5.0, 25)
    d = 10 * np.log10(wps_normalised("rozenberg_2010", w, bl) / wps_normalised("goody", w, bl))
    return _check("rozenberg2010_zpg_limit", "Thesis eq. 3.27 (Rozenberg 2010) reduces to Goody's model at "
                  "zero pressure gradient with delta = 8 delta*", "Blandeau (2011) eq. 3.27; Goody (2004)",
                  "max |dB difference|", float(np.max(np.abs(d))), 0.5)


def check_te_subcritical():
    M, K = 0.5, 20.0
    mub = K * M / (1 - M * M)
    fr = np.concatenate([[1 - 1e-4, 1 + 1e-4], np.geomspace(1.01, 50.0, 40)])
    ky = fr * mub * np.sqrt(1 - M * M)
    with np.errstate(all="ignore"):
        I = te_response(np.full_like(fr, K), 1 / 0.7, ky, M, 0.3 * K, True)
    db = 20 * np.log10(np.abs(I))
    ok = np.all(np.isfinite(db)) and np.all(db[2:] < db[1] + 1.0)      # finite and bounded by the peak
    jump = float(abs(db[1] - db[0])) if ok else 1e9
    return _check("te_subcritical_gusts", "Trailing-edge response stays finite and continuous for subcritical "
                  "gusts (ky > mubar beta, reached by the full formulation in flight): no jump across the "
                  "critical gust and no growth beyond it", "Roger & Moreau (2005) JSV 286",
                  "|dB jump| across ky = mubar beta", jump, 1.5, details=f"{db[0]:.2f} / {db[1]:.2f} dB")


def check_thesis_273_vs_full():
    """Eq. 2.73 in the limit of overlapping wakes (homogeneous turbulence) against the full model."""
    from .thesis import WAKE_A, eq273_spectrum
    rear = Rotor(B=9, r_tip=1.2, r_hub=1.0, chord=0.3, rpm=900.0, Ux=150.0, n_strips=1, flight_speed=0.0)
    B1, Om1, w_rms, L = 10, 90.0, 5.0, 0.05
    r = rear.strips()[0].r
    bW = 3.0 * 2 * np.pi * r / B1                    # sigma ~ 0.06: only the m = 0 wake harmonic
    w_eff = w_rms * bW * B1 / (2 * np.pi * r) * np.sqrt(np.pi / WAKE_A)
    src = LESource(HomogeneousTurbulence("vonkarman", Lambda=L, w_rms=w_eff))
    w = 2 * np.pi * np.array([200.0, 1000.0, 3000.0, 8000.0])
    worst, rows = 0.0, []
    for th in (30, 60, 90, 120, 150):
        S = eq273_spectrum(rear, lambda x: (w_rms, L, bW), B1, Om1, w, 50.0, th, doppler_sign=-1.0)
        m = full_spectrum(rear, src, w, observer_position(50.0, 180.0 - th), spanwise=False)
        d = 10 * np.log10(S * THESIS_SPECTRAL_FACTOR * 2 * np.pi / (m * src.spectral_factor))
        worst = max(worst, float(np.max(np.abs(d))))
        rows.append(f"theta={th}: " + " ".join(f"{v:+.2f}" for v in d))
    return _check("thesis_eq273_vs_full", "Thesis eq. 2.73 (simplified BRWI) with overlapping wakes, the Doppler "
                  "pairing mirrored and the result multiplied by 2 pi, reproduces the independent full "
                  "formulation; as printed it is 2 pi (8 dB) lower",
                  "Blandeau (2011) eqs. 2.12-2.15, 2.50, 2.73-2.74", "max |dB difference|", worst, 1.0,
                  details="; ".join(rows))


CHECKS = [check_spectrum_normalisation, check_wake_energy, check_fresnel, check_te_chord_integral,
          check_le_low_frequency, check_gep_vs_goody, check_rozenberg_goody, check_le_velocity_scaling,
          check_te_velocity_scaling, check_doppler_kinematics, check_full_vs_simplified,
          check_low_frequency_departure, check_blade_count_linearity, check_thesis_318_vs_57,
          check_thesis_318_vs_full, check_thesis_273_vs_full, check_rozenberg2010_goody, check_te_subcritical]


def run_all(progress=None):
    out = []
    for fn in CHECKS:
        t0 = time.time()
        c = fn()
        c.seconds = time.time() - t0
        out.append(c)
        if progress:
            progress(c)
    return out


def write_report(results, path):
    import json
    from pathlib import Path
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    (p / "verification.json").write_text(json.dumps([asdict(r) for r in results], indent=1))
    lines = ["# bbnoise verification", "", "| check | metric | value | tolerance | result | reference |",
             "|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r.name} | {r.metric} | {r.value:.3g} | {r.tolerance:.3g} | "
                     f"{'PASS' if r.passed else 'FAIL'} | {r.reference} |")
    (p / "verification.md").write_text("\n".join(lines) + "\n")
    return [str(p / "verification.json"), str(p / "verification.md")]
