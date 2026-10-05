"""Synthetic BoB inputs (made-up 1/7-scale CROR) for the bundled example cases and tests.

All numbers here are invented for demonstration; they do not come from any rig.
"""
from __future__ import annotations

import numpy as np

__all__ = ["synthetic_inputs", "synthetic_bl_tables", "synthetic_wake", "synthetic_ingestion", "BL_HEADER"]

BL_HEADER = ("R Boundary_Layer_Thickness Displacement_Thickness Momentum_Thickness unused Tau_max dpdx "
             "Rho_wall U_inf Pi Nu_wall Tau_wall Discard")


def synthetic_inputs():
    """geom / cond structures in BoB's CaseInputs layout (radians, metres, rad/s)."""
    r1 = np.linspace(0.070, 0.250, 13)
    r2 = np.linspace(0.070, 0.230, 13)
    geom = {"scale": 1.0, "B1": 10.0, "B2": 8.0, "eta": 0.22,
            "r1": r1, "r2": r2,
            "c1": np.linspace(0.062, 0.044, 12), "c2": np.linspace(0.064, 0.046, 12),
            "alpha1": np.linspace(0.62, 1.16, 13), "alpha2": np.linspace(0.58, 1.08, 13),
            "s1": np.linspace(0.0, 0.005, 12), "s2": np.linspace(0.0, -0.004, 12), "c_pylon": 0.06}
    cond = {"Omega1": 300.0, "Omega2": 270.0, "Mx": 0.2, "c0": 340.0, "rho": 1.2,
            "Cd": np.linspace(0.008, 0.026, 20), "AoA1": np.linspace(0.01, 0.08, 20),
            "AoA2": np.linspace(0.02, 0.07, 20), "Ux1": np.full(32, 68.0), "Ux2": np.full(32, 70.0)}
    return {"geom": geom, "cond": cond}


def synthetic_bl_tables(st=5):
    """Four BoB boundary-layer tables (front top, front bottom, rear top, rear bottom), 13 columns."""
    r = np.linspace(0.088, 0.232, st)
    out = []
    for top, rot in ((True, 1), (False, 1), (True, 2), (False, 2)):
        d = np.linspace(2.6e-3, 1.7e-3, st) * (1.25 if top else 0.8) * (1.1 if rot == 2 else 1.0)
        ds = d * (0.32 if top else 0.22)
        th = ds / 1.45
        tauw = np.linspace(20, 44, st) * (0.8 if top else 1.1)
        taumax = tauw * (1.9 if top else 1.15)
        dpdx = np.linspace(2.2e4, 4.4e4, st) * (1 if top else -0.3)
        cols = [r, d, ds, th, np.zeros(st), taumax, dpdx, np.full(st, 1.2), np.linspace(100, 170, st),
                np.linspace(0.9, 0.6, st) * (1 if top else 0.3), np.full(st, 1.5e-5), tauw, np.zeros(st)]
        out.append(np.column_stack(cols))
    return out


def bl_text(table):
    return BL_HEADER + "\n" + "\n".join(" ".join(f"{v:.8e}" for v in row) for row in table) + "\n"


def synthetic_wake(st=5):
    return {"bw": np.linspace(0.0065, 0.0042, st), "wrms_wake": np.linspace(2.6, 1.7, st),
            "wrms_bg": np.linspace(0.6, 0.4, st), "L_wake": np.linspace(0.0042, 0.0031, st),
            "L_bg": np.linspace(0.010, 0.013, st)}


def synthetic_ingestion():
    z = np.linspace(0.01, 0.12, 12)
    return {"z": z, "ua": np.full(z.size, 1.0), "la": 0.30 - 0.01 * np.arange(z.size),
            "ut": np.full(z.size, 2.0), "lt": 0.15 - 0.005 * np.arange(z.size)}


def _lists(d):
    return {k: (np.asarray(v).tolist() if isinstance(v, np.ndarray) else v) for k, v in d.items()}


def bob_example_cases():
    """Dashboard / CLI example cases of type "bob" built from the synthetic inputs."""
    inp = synthetic_inputs()
    inputs = {"geom": _lists(inp["geom"]), "cond": _lists(inp["cond"])}
    common = {
        "type": "bob",
        "reference": "BoB 3.5 (ANTC / Airbus, University of Southampton), ported line by line; "
                     "models after V. P. Blandeau, PhD thesis, ISVR (2011).",
        "inputs": inputs,
    }
    cror = dict(common, **{
        "name": "BoB 3.5: CROR rotor noise, BRWI + BRTE (synthetic inputs)",
        "description": ("BoB's full rotational models for a made-up 10 x 8 CROR: BRWI of the rear rotor (wake and "
                        "background turbulence from a wake-data table) and BRTE of both rotors (boundary layers from "
                        "BoB boundary-layer files: R, delta, delta*, theta, tau_max, dp/dx, rho_w, U_inf, Pi, nu_w, "
                        "tau_w, discard; one row per strip). Rozenberg wall pressure, DEL2 convection, Salze "
                        "correlation length, as in BoB's launch_BoB.m. Results agree with BoB 3.5 (run in Octave) "
                        "to round-off."),
        "options": {"StageCount": 2, "CFD_data": True, "rotor_noise": True, "noise_type": "BOTH",
                    "installation_noise": False, "amiet": False, "chapman": False, "emission_angle": False,
                    "phi_sw": "RZ", "Uc": "DEL2", "lr": "SLZ", "L": 0.4, "Karman_spec": True, "baddata": "IGNORE",
                    "spectral_study": True, "f_l": 50.0, "f_h": 20000.0, "f_num": 16, "st_num": 5, "r0": 2.54,
                    "theta": (np.arange(30.0, 151.0, 30.0) * np.pi / 180).tolist()},
        "bl_files": [bl_text(t) for t in synthetic_bl_tables()],
        "wake": _lists(synthetic_wake()),
    })
    bli = dict(common, **{
        "name": "BoB 3.5: boundary-layer ingestion with a hard wall, BPRI_BL (synthetic inputs)",
        "description": ("BoB's installation model for a rotor ingesting a wall boundary layer (BPRI_BL): Amiet's "
                        "simplified rotational model with blade-to-blade correlation, partial loading inside the "
                        "boundary layer and the image source of a hard wall. The four contributions are shown: "
                        "free field (no wall), the two interference terms and the image source. Turbulence "
                        "(ua, la, ut, lt) varies with the wall distance z from a table."),
        "options": {"StageCount": 1, "CFD_data": False, "rotor_noise": False, "noise_type": "BRWI",
                    "installation_noise": True,
                    "p_noise_type": "BPRI_BL", "BPRI_correlation": True, "partial_loading": True, "wall": True,
                    "dwall": 0.27, "bl_height": 0.1, "bondary_layer_input_from_file": True,
                    "amiet": True, "phi_num": 24, "chapman": False, "emission_angle": False, "Karman_spec": True,
                    "spectral_study": True, "f_l": 300.0, "f_h": 3000.0, "f_num": 16, "st_num": 5, "r0": 2.54,
                    "theta": [120 * np.pi / 180]},
        "bl_ingestion": _lists(synthetic_ingestion()),
    })
    return {"bob_cror": cror, "bob_bl_ingestion": bli}
