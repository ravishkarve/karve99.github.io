"""Baseline contra-rotating open rotor of Blandeau's thesis (section 4.2).

10 x 9 blades, tip radii 2.0 m (front) and 1.8 m (rear), hub radius 0.67 m,
rotor-rotor gap 1 m, tip Mach number 0.5 for both rotors, equal torque split;
flight Mach number 0.25 (take-off, approach) and 0.7 (cruise), Table 4.1.

The spanwise distributions below were digitised by hand from the thesis figures
(accuracy of a few per cent of the plotted range):

* chord c_i(r), Fig. 4.4(a)
* chordwise relative velocity U_Xi(r), Fig. 4.4(c), converted to the axial
  velocity through each disc, Ux = sqrt(U_X^2 - (Omega r)^2)
* suction/pressure-side displacement thickness delta*/c, Fig. 4.5 (from XFOIL on a
  NACA 0012 in the thesis); the other boundary-layer parameters are not given and
  are estimated (H = 1.4, Ludwieg-Tillmann C_f, zero pressure gradient)
* front-rotor wake turbulence at the rear leading edge, w_rms(r) and integral scale
  L(r), Fig. 4.6(b)-(c); the wake half-width follows the thesis' L = 0.42 b_W
  (eq. 2.78) and w_rms is taken as the wake-centreline value.

Expected result (Fig. 4.7): at take-off the rotor-wake interaction noise is
comparable to the trailing-edge noise and dominates between about 600 Hz and
6 kHz; at cruise and approach the trailing-edge noise of each rotor dominates
the total broadband noise by more than 10 dB.  With the Fig. 4.6 values taken as
wake-centreline inputs to the periodic wake model of :mod:`bbnoise.turbulence`,
the trailing-edge noise here follows the thesis (peak near 250 Hz at take-off,
1-2 kHz at cruise and approach) but the interaction noise is 12-23 dB higher
relative to it than in Fig. 4.7; the thesis' own wake model (section 2.5,
eqs. 2.58-2.78) lies outside the pages used for this implementation.

At incidence only suction-side data are available for Garcia Sagrado's airfoil;
the pressure side is then estimated (delta* / 3, H = 1.4, zero pressure gradient).
"""
from __future__ import annotations

import math

R1, R2, RH = 2.0, 1.8, 0.67
C0 = 340.0
MT = 0.5
OMEGA1 = MT * C0 / R1
OMEGA2 = MT * C0 / R2
RPM1 = OMEGA1 * 30 / math.pi
RPM2 = OMEGA2 * 30 / math.pi

CHORD_FRONT = {"r": [0.72, 0.8, 1.0, 1.2, 1.4, 1.55, 1.65, 1.8, 1.9, 2.0],
               "c": [0.37, 0.38, 0.395, 0.41, 0.42, 0.42, 0.41, 0.37, 0.32, 0.255]}
CHORD_REAR = {"r": [0.72, 0.8, 0.9, 1.0, 1.1, 1.3, 1.45, 1.55, 1.65, 1.78],
              "c": [0.38, 0.40, 0.42, 0.44, 0.46, 0.465, 0.445, 0.40, 0.33, 0.23]}

# chordwise relative velocity U_X at the hub-side and tip-side ends of the plotted curves (Fig. 4.4c)
UX_REL = {  # condition: (front (r, U_X) pairs, rear (r, U_X) pairs), flight Mach
    "takeoff": ([(0.7, 108.0), (2.0, 188.0)], [(0.7, 128.0), (1.8, 222.0)], 0.25),
    "cruise": ([(0.7, 245.0), (2.0, 290.0)], [(0.7, 258.0), (1.8, 292.0)], 0.70),
    "approach": ([(0.7, 105.0), (2.0, 185.0)], [(0.7, 110.0), (1.8, 195.0)], 0.25),
}

# delta*/c in % (Fig. 4.5): (suction, pressure) along the radius
DSTAR = {
    "takeoff": {"front": ([0.7, 1.0, 1.4, 1.8, 1.95], [1.05, 1.03, 1.03, 1.15, 1.75], [0.33, 0.30, 0.30, 0.30, 0.35]),
                "rear": ([0.7, 0.8, 1.0, 1.2, 1.5, 1.65, 1.78], [1.10, 1.00, 0.95, 0.87, 0.90, 1.00, 1.25],
                         [0.20, 0.17, 0.12, 0.10, 0.12, 0.15, 0.20])},
    "cruise": {"front": ([0.7, 2.0], [0.30, 0.30], [0.22, 0.18]),
               "rear": ([0.7, 1.8], [0.27, 0.27], [0.22, 0.22])},
    "approach": {"front": ([0.7, 2.0], [0.33, 0.33], [0.28, 0.28]),
                 "rear": ([0.7, 1.8], [0.35, 0.40], [0.25, 0.25])},
}

# wake turbulence at the rear leading edge (Fig. 4.6): r [m], w_rms [m/s], L [m]
WAKE = {
    "takeoff": ([0.7, 0.8, 0.9, 1.0, 1.2, 1.4, 1.6, 1.8, 1.9],
                [3.7, 3.9, 4.4, 6.2, 6.6, 6.9, 7.0, 7.0, 7.7],
                [0.0065, 0.0068, 0.0083, 0.0165, 0.0185, 0.0195, 0.0198, 0.019, 0.026]),
    "cruise": ([0.7, 0.8, 0.9, 1.0, 1.2, 1.4, 1.6, 1.8, 1.9],
               [7.0, 6.0, 5.6, 5.3, 4.9, 4.7, 4.3, 3.9, 3.5],
               [0.0045, 0.0042, 0.0040, 0.0040, 0.0040, 0.0040, 0.0040, 0.0039, 0.0038]),
    "approach": ([0.7, 0.8, 0.9, 1.0, 1.2, 1.4, 1.6, 1.8, 1.9],
                 [2.0, 1.9, 1.8, 1.75, 1.7, 1.65, 1.6, 1.45, 1.3],
                 [0.0042, 0.0042, 0.0042, 0.0042, 0.0042, 0.0042, 0.0042, 0.0042, 0.0042]),
}

LABEL = {"takeoff": "take-off", "cruise": "cruise", "approach": "approach"}


def _axial(pairs, omega, r_tip):
    xs, ys = [], []
    for r, ux_rel in pairs:
        ut = omega * r
        xs.append(r / r_tip)
        ys.append(round(math.sqrt(max(ux_rel ** 2 - ut ** 2, 1.0)), 1))
    return {"r_over_R": xs, "value": ys}


def baseline_cror(condition="takeoff"):
    front_ux, rear_ux, mx = UX_REL[condition]
    ds = DSTAR[condition]
    wr, ww, wl = WAKE[condition]

    def bl(side_data, r_tip):
        r, s, p = side_data
        x = [v / r_tip for v in r]
        return {"method": "user",
                "suction": {"delta_star_over_c": {"r_over_R": x, "value": [v / 100 for v in s]}},
                "pressure": {"delta_star_over_c": {"r_over_R": x, "value": [v / 100 for v in p]}}}

    lw_over_s = [(L / 0.42) / (2 * math.pi * r / 10) for r, L in zip(wr, wl)]
    return {
        "name": f"Blandeau (2011) baseline 10 x 9 CROR, {LABEL[condition]} (thesis section 4.2)",
        "type": "rotor",
        "reference": "V. P. Blandeau, 'Aerodynamic broadband noise from contra-rotating open rotors', PhD thesis, "
                     "ISVR, University of Southampton (2011), section 4.2, Table 4.1 and Figs. 4.4-4.7.",
        "description": (f"Hypothetical full-scale CROR: 10 x 9 blades, R_t = 2.0 / 1.8 m, R_h = 0.67 m, tip Mach "
                        f"0.5, flight Mach {mx}. Chord, relative velocity, delta*/c and wake turbulence "
                        "(w_rms, L) digitised from Figs. 4.4-4.6; trailing-edge noise with thesis eq. 3.18 and "
                        "Rozenberg's model as in the thesis, rotor-wake interaction with the full and simplified "
                        "formulations. Expected (Fig. 4.7): " +
                        ("interaction noise comparable to trailing-edge noise, dominant between ~600 Hz and 6 kHz."
                         if condition == "takeoff" else "trailing-edge noise dominates by more than 10 dB.") +
                        " Note: with the Fig. 4.6 wake values taken as wake-centreline inputs, the interaction "
                        "noise computed here is 12-23 dB higher relative to the trailing-edge noise than in "
                        "Fig. 4.7 (the thesis' wake model, section 2.5, is not reproduced)."),
        "fluid": {"c0": C0},
        "rotors": [
            {"name": "front", "B": 10, "r_tip": R1, "r_hub": RH, "rpm": round(RPM1, 3), "n_strips": 10,
             "flight_speed": mx * C0, "Ux": _axial(front_ux, OMEGA1, R1),
             "chord": {"r_over_R": [r / R1 for r in CHORD_FRONT["r"]], "value": CHORD_FRONT["c"]}},
            {"name": "rear", "B": 9, "r_tip": R2, "r_hub": RH, "rpm": round(RPM2, 3), "n_strips": 10,
             "flight_speed": mx * C0, "Ux": _axial(rear_ux, OMEGA2, R2),
             "chord": {"r_over_R": [r / R2 for r in CHORD_REAR["r"]], "value": CHORD_REAR["c"]}},
        ],
        "self_noise": {"models": ["rozenberg_2010"],
                       "boundary_layers": {"front": bl(ds["front"], R1), "rear": bl(ds["rear"], R2)},
                       "boundary_layer": bl(ds["front"], R1)},
        "rwi": {"front": "front", "rear": "rear", "spectrum": ["vonkarman"],
                "wake": {"tke_c": {"r_over_R": [r / R1 for r in wr], "value": [round(1.5 * w * w, 3) for w in ww]},
                         "Lambda": {"r_over_R": [r / R1 for r in wr], "value": wl},
                         "Lw_over_s": {"r_over_R": [r / R1 for r in wr], "value": [round(v, 4) for v in lw_over_s]},
                         "model": "periodic"}},
        "formulations": ["eq3.18", "full", "simplified"],
        "observers": {"R": 50.0, "theta_deg": [90, 30, 60, 120, 150]},
        "frequency": {"f_min": 20.0, "f_max": 20000.0, "n": 30},
        "options": {"sound_power": True, "n_theta": 7},
    }


# Garcia Sagrado's NACA 0012 (thesis section 3.3): chord 0.3 m, tripped at 12.7 % chord.
# Suction-side values close to the trailing edge: delta* and C_f read from Figs. 3.3-3.4
# (measurements, x/c ~ 0.98), dp/dx measured (Table 3.1, 50-85 % chord).
GARCIA_SAGRADO = {  # (U [m/s], AoA [deg]) -> (delta* [m], C_f, dp/dx [Pa/m])
    (10.0, 0.0): (2.6e-3, 0.0033, 43.40),
    (20.0, 0.0): (2.25e-3, 0.0024, 181.87),
    (10.0, 6.25): (6.3e-3, 0.0015, 78.12),
    (20.0, 6.25): (5.6e-3, 0.0014, 327.36),
    (10.0, 8.0): (13.0e-3, 0.0005, 82.67),
    (20.0, 8.0): (9.0e-3, 0.0005, 367.04),
}


def garcia_sagrado(U=20.0, aoa=0.0):
    ds, cf, dpdx = GARCIA_SAGRADO[(float(U), float(aoa))]
    suction = {"delta_star": ds, "cf": cf, "dpdx": dpdx, "H": 1.5}
    # pressure-side data are not available at incidence; at 0 deg the airfoil is symmetric
    pressure = dict(suction) if aoa == 0 else {"delta_star": ds / 3, "H": 1.4}
    return {
        "name": f"Garcia Sagrado NACA 0012, U = {U:g} m/s, AoA = {aoa:g} deg (thesis section 3.3)",
        "type": "airfoil_te",
        "reference": "A. Garcia Sagrado, PhD thesis, University of Cambridge (2008); V. P. Blandeau, PhD thesis, "
                     "ISVR (2011), section 3.3, Table 3.1 and Figs. 3.3-3.6.",
        "description": (f"NACA 0012, chord 0.3 m, Re_c = {U / 10 * 2:g}e5, tripped.  Measured suction-side "
                        f"boundary layer near the trailing edge: delta* = {ds * 1e3:g} mm, C_f = {cf:g}, "
                        f"dp/dx = {dpdx:g} Pa/m (Table 3.1).  The thesis compares the wall-pressure models with "
                        "the measured surface-pressure spectrum (Fig. 3.6): see the wall-pressure panel of the "
                        "self-noise tab.  Expected (thesis p. 93): Rozenberg's model (eq. 3.27) gives the best "
                        "spectral shape; Kim-George agrees at low frequency but over-predicts the mid and high "
                        "frequencies; Amiet and Chase-Howe under-predict the low and over-predict the high "
                        "frequencies.  The far-field span (0.4 m) and observer (1.2 m) are "
                        "illustrative."),
        "fluid": {"nu": 1.5e-5},
        "airfoil": {"chord": 0.3, "span": 0.4, "U": float(U)},
        "self_noise": {"models": ["amiet", "chase_howe", "goody", "kim_george", "rozenberg_2010", "rozenberg"],
                       "boundary_layer": {"method": "user", "suction": suction, "pressure": pressure}},
        "observers": {"R": 1.2, "theta_deg": [90, 45, 135]},
        "frequency": {"f_min": 50.0, "f_max": 10000.0, "n": 40},
    }
