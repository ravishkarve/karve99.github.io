"""Test cases from the literature.

Geometries and operating conditions are taken from the cited publications.
Measured spectra are not bundled; each case lists what the prediction is
expected to reproduce (trends, the full-vs-simplified comparison, or model
cross-checks), and :mod:`bbnoise.verification` checks those expectations.
The CROR cases are representative of the 1/5-scale open-rotor rigs used in
Blandeau's thesis and in Blandeau, Joseph, Kingan & Parry (2013); their blade
geometry and wake parameters are illustrative, not rig data.
"""
from __future__ import annotations

import copy

CASES = {}


def _add(key, case):
    case["key"] = key
    CASES[key] = case


# ---------------------------------------------------------------------------
# Stationary airfoils
# ---------------------------------------------------------------------------

_add("paterson_amiet_1976", {
    "name": "Paterson & Amiet (1976): NACA 0012 in a turbulent jet",
    "type": "airfoil_le",
    "reference": "R. W. Paterson & R. K. Amiet, 'Acoustic radiation and surface pressure characteristics "
                 "of an airfoil due to incident turbulence', NASA CR-2733 / AIAA Paper 76-571 (1976).",
    "description": "Chord 0.23 m, span 0.53 m, U = 120 m/s, turbulence intensity 4.4 %, integral scale "
                   "0.031 m, microphone 2.25 m above the airfoil.  Amiet's flat-plate leading-edge model "
                   "with von Karman and Liepmann spectra.  Expected: peak near 1 kHz, level rising "
                   "roughly as U^5-U^6; Liepmann is higher than von Karman at high frequency.",
    "airfoil": {"chord": 0.23, "span": 0.53, "U": 120.0},
    "turbulence": {"spectrum": ["vonkarman", "liepmann"], "intensity": 0.044, "Lambda": 0.031},
    "observers": {"R": 2.25, "theta_deg": [90, 30, 45, 60, 75, 105, 120, 135, 150]},
    "frequency": {"f_min": 100.0, "f_max": 20000.0, "n": 50},
})

_add("bpm_naca0012_te", {
    "name": "Brooks, Pope & Marcolini (1989): NACA 0012 trailing-edge noise",
    "type": "airfoil_te",
    "reference": "T. F. Brooks, D. S. Pope & M. A. Marcolini, 'Airfoil self-noise and prediction', "
                 "NASA RP-1218 (1989).",
    "description": "Chord 0.3048 m, span 0.4572 m, U = 71.3 m/s, tripped boundary layer at zero incidence, "
                   "observer 1.22 m at 90 deg.  Boundary layer from the BPM correlations; all wall-pressure "
                   "models, including the VKI GEP model, feed Amiet's TE model with back-scattering.",
    "airfoil": {"chord": 0.3048, "span": 0.4572, "U": 71.3},
    "brte": {"models": ["amiet", "chase_howe", "goody", "rozenberg", "kamruzzaman", "lee",
                              "dominique_gep"],
                   "boundary_layer": {"method": "bpm", "alpha_deg": 0.0, "tripped": True}},
    "observers": {"R": 1.22, "theta_deg": [90, 30, 45, 60, 120, 135, 150]},
    "frequency": {"f_min": 200.0, "f_max": 20000.0, "n": 50},
})

_add("rozenberg_apg_te", {
    "name": "Adverse pressure gradient TE noise (Rozenberg-type APG boundary layer)",
    "type": "airfoil_te",
    "reference": "Y. Rozenberg, G. Robert & S. Moreau, 'Wall-pressure spectral model including the adverse "
                 "pressure gradient effects', AIAA J. 50(10) (2012); M. Kamruzzaman et al., Wind Energy 18 "
                 "(2015); S. Lee, AIAA J. 56(5) (2018); J. Dominique et al., JSV 506 (2021).",
    "description": "Same airfoil as the BPM case with a suction-side boundary layer at beta_C = 3 (H = 1.8): "
                   "the pressure-gradient-aware models (Rozenberg, Kamruzzaman, Lee, GEP) raise the "
                   "low/mid-frequency levels relative to Goody.",
    "airfoil": {"chord": 0.3048, "span": 0.4572, "U": 71.3},
    "brte": {"models": ["goody", "rozenberg", "kamruzzaman", "lee", "dominique_gep"],
                   "boundary_layer": {"method": "bpm", "alpha_deg": 4.0, "tripped": True,
                                      "H": [1.8, 1.4], "beta_c": [3.0, 0.0]}},
    "observers": {"R": 1.22, "theta_deg": [90]},
    "frequency": {"f_min": 200.0, "f_max": 20000.0, "n": 50},
})

# ---------------------------------------------------------------------------
# Rotating blades
# ---------------------------------------------------------------------------

_add("blandeau_joseph_2011", {
    "name": "Blandeau & Joseph (2011): validity of Amiet's model for propeller TE noise",
    "type": "rotor",
    "reference": "V. P. Blandeau & P. F. Joseph, 'Validity of Amiet's model for propeller trailing-edge "
                 "noise', AIAA J. 49(5), 1057-1066 (2011); V. P. Blandeau, PhD thesis, ISVR, University of "
                 "Southampton (2011), ch. 3.",
    "description": "Single blade element (R = 1 m, chord 0.1 m, span 0.1 m, 2 blades) at a relative Mach "
                   "number of 0.6, static.  Expected: full and simplified formulations agree (< 1 dB) for "
                   "frequencies above a few shaft orders at all angles; differences grow at low frequency "
                   "and close to the rotor plane.",
    "rotors": [{"name": "propeller", "B": 2, "r_tip": 1.0, "r_hub": 0.9, "chord": 0.1,
                "rpm": 1948.0, "Ux": 0.0, "n_strips": 1}],
    "brte": {"models": ["goody"], "boundary_layer": {"method": "flat_plate"}},
    "formulations": ["full", "simplified"],
    "observers": {"R": 10.0, "theta_deg": [45, 15, 30, 60, 75, 90, 105, 120, 135, 150, 165]},
    "frequency": {"f_min": 20.0, "f_max": 10000.0, "n": 40},
})

_add("rotor_turbulence_ingestion", {
    "name": "Rotor ingesting homogeneous turbulence (Amiet 1977 / Paterson & Amiet 1979 type)",
    "type": "rotor",
    "reference": "R. K. Amiet, 'Noise produced by turbulent flow into a propeller or helicopter rotor', "
                 "AIAA J. 15(3) (1977); R. W. Paterson & R. K. Amiet, NASA CR-3213 (1979).",
    "description": "Two-bladed model rotor (R = 0.76 m) in isotropic turbulence (intensity 5 %, "
                   "Lambda = 0.1 m), 25 m/s axial flow.  Compares the full and simplified formulations "
                   "and the von Karman and Liepmann spectra.  Illustrative geometry.",
    "rotors": [{"name": "rotor", "B": 2, "r_tip": 0.76, "r_hub": 0.15, "chord": 0.076, "rpm": 1800.0,
                "Ux": 25.0, "n_strips": 8}],
    "ingestion": {"spectrum": ["vonkarman", "liepmann"], "intensity": 0.05, "Lambda": 0.1, "U_ref": 25.0},
    "formulations": ["full", "simplified"],
    "observers": {"R": 5.0, "theta_deg": [45, 15, 30, 60, 75, 90, 105, 120, 135, 150, 165]},
    "frequency": {"f_min": 20.0, "f_max": 10000.0, "n": 40},
})

_CROR = {
    "type": "rotor",
    "reference": "V. P. Blandeau, 'Aerodynamic broadband noise from contra-rotating open rotors', PhD "
                 "thesis, ISVR, University of Southampton (2011); V. P. Blandeau & P. F. Joseph, AIAA J. "
                 "48(11) (2010); V. P. Blandeau, P. F. Joseph, M. J. Kingan & A. B. Parry, Int. J. "
                 "Aeroacoustics 12(3), 245-282 (2013).",
    "rotors": [
        {"name": "front", "B": 12, "r_tip": 0.35, "r_hub": 0.105, "rpm": 6000.0, "Ux": 70.0,
         "chord": {"r_over_R": [0.3, 0.7, 1.0], "value": [0.050, 0.060, 0.040]}, "n_strips": 10},
        {"name": "rear", "B": 10, "r_tip": 0.315, "r_hub": 0.105, "rpm": 6000.0, "Ux": 80.0,
         "chord": {"r_over_R": [0.3, 0.7, 1.0], "value": [0.050, 0.055, 0.040]}, "n_strips": 10},
    ],
    "brte": {"models": ["goody"], "boundary_layer": {"method": "bpm", "tripped": True}},
    "brwi": {"front": "front", "rear": "rear", "spectrum": ["vonkarman", "liepmann"],
            "wake": {"tu_c": 0.05, "Lw_over_s": 0.08, "Lambda_over_Lw": 0.42, "model": "periodic"}},
    "formulations": ["full", "simplified"],
    "observers": {"R": 10.0, "theta_deg": [90, 20, 40, 60, 75, 105, 120, 140, 160]},
    "frequency": {"f_min": 100.0, "f_max": 20000.0, "n": 40},
}

_add("cror_takeoff", dict(copy.deepcopy(_CROR), **{
    "name": "Contra-rotating open rotor at take-off (12 x 10, 1/5 scale, illustrative)",
    "description": "Front 12 blades / rear 10 blades, 0.7 m diameter, clipped rear rotor (90 %), "
                   "6000 rpm each, Mach 0.2.  Rotor-wake interaction on the rear rotor (periodic Gaussian "
                   "wakes, von Karman and Liepmann) and trailing-edge self noise of both rotors, each with "
                   "the full and the simplified (Amiet) formulation.  Expected: RWI dominates at mid "
                   "frequency; periodic wakes produce humps at multiples of the wake-passing frequency "
                   "B1 (Omega1 + Omega2)/(2 pi) = 2.4 kHz in the full model."}))

_add("cror_wake_models", dict(copy.deepcopy(_CROR), **{
    "name": "CROR rotor-wake interaction: periodic vs passage-averaged wake turbulence",
    "description": "Rear-rotor RWI noise with the periodic (cyclostationary) wake description and with the "
                   "passage-averaged homogeneous equivalent (Blandeau's simplified wake model). Both have "
                   "the same mean-square upwash; the periodic model redistributes energy into humps at "
                   "the wake-passing harmonics.",
    "brte": {"enabled": False},
    "formulations": ["full"],
}))
CASES["cror_wake_models"]["brwi"] = {"front": "front", "rear": "rear", "spectrum": ["vonkarman"],
                                    "wake": {"tu_c": 0.05, "Lw_over_s": 0.08, "Lambda_over_Lw": 0.42,
                                             "model": ["periodic", "averaged"]}}


_add("custom_cror", {
    "name": "Custom CROR: radially varying chord and stagger (BRWI + BRTE)",
    "type": "rotor",
    "reference": "Template for user rotors; models after V. P. Blandeau, PhD thesis, ISVR (2011), chs. 2-4.",
    "description": "A starting point for your own rotors. Chord and stagger vary strongly along both blades "
                   "(stagger measured from the rotor axis, as in the thesis); leave the stagger blank to align "
                   "the blades with the relative inflow, and give U_X to set the chordwise speed directly. "
                   "The rear-rotor strips (chord, stagger, chordwise speed) drive the rotor-wake interaction "
                   "noise (BRWI) with the front-rotor wakes given by TKE and integral length scale; both "
                   "rotors radiate trailing-edge noise (BRTE). Computed with the full formulation and the "
                   "thesis' eqs. 2.73 / 3.18. Where the stagger differs from the inflow angle the strip "
                   "table shows the angle of attack; the flat-plate models use the chordwise component of "
                   "the inflow.",
    "fluid": {"c0": 340.0},
    "rotors": [
        {"name": "front", "B": 10, "r_tip": 2.0, "r_hub": 0.7, "rpm": 812.0, "Ux": 85.0, "flight_speed": 85.0,
         "n_strips": 10,
         "chord": {"r_over_R": [0.35, 0.5, 0.7, 0.85, 1.0], "value": [0.30, 0.42, 0.45, 0.38, 0.22]},
         "stagger_deg": {"r_over_R": [0.35, 0.5, 0.7, 0.85, 1.0], "value": [30.0, 42.0, 52.0, 58.0, 62.0]}},
        {"name": "rear", "B": 9, "r_tip": 1.8, "r_hub": 0.7, "rpm": 902.0, "Ux": 95.0, "flight_speed": 85.0,
         "n_strips": 10,
         "chord": {"r_over_R": [0.39, 0.55, 0.75, 0.9, 1.0], "value": [0.32, 0.46, 0.44, 0.33, 0.20]},
         "stagger_deg": {"r_over_R": [0.39, 0.55, 0.75, 0.9, 1.0], "value": [26.0, 40.0, 50.0, 56.0, 60.0]}},
    ],
    "brte": {"models": ["rozenberg_2010", "goody"], "boundary_layer": {"method": "bpm", "tripped": True}},
    "brwi": {"front": "front", "rear": "rear", "spectrum": ["vonkarman"],
             "wake": {"tke_c": {"r_over_R": [0.35, 0.6, 0.9, 1.0], "value": [20.0, 45.0, 60.0, 80.0]},
                      "Lambda": {"r_over_R": [0.35, 0.6, 0.9, 1.0], "value": [0.008, 0.017, 0.019, 0.024]},
                      "Lw_over_s": {"r_over_R": [0.35, 0.6, 0.9, 1.0], "value": [0.036, 0.042, 0.032, 0.036]},
                      "model": "periodic"}},
    "formulations": ["full", "eq3.18", "eq2.73"],
    "observers": {"R": 50.0, "theta_deg": [90, 45, 135]},
    "frequency": {"f_min": 20.0, "f_max": 20000.0, "n": 30},
    "options": {"sound_power": False},
})

# ---------------------------------------------------------------------------
# Blandeau (2011) thesis cases
# ---------------------------------------------------------------------------

from .thesis_cases import baseline_cror, garcia_sagrado  # noqa: E402

_add("garcia_sagrado_naca0012", garcia_sagrado(20.0, 0.0))
for _cond in ("takeoff", "cruise", "approach"):
    _add(f"blandeau_cror_{_cond}", baseline_cror(_cond))


# ---------------------------------------------------------------------------
# BoB 3.5 port (synthetic inputs)
# ---------------------------------------------------------------------------

from .bob.synthetic import bob_example_cases  # noqa: E402

for _k, _c in bob_example_cases().items():
    _add(_k, _c)


def get_case(key):
    if key not in CASES:
        raise KeyError(f"unknown case {key!r}; available: {', '.join(CASES)}")
    return copy.deepcopy(CASES[key])


def list_cases():
    return [(k, c["name"]) for k, c in CASES.items()]
