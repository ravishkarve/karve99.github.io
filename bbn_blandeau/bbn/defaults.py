"""Internal solver options and their defaults.

:mod:`bbn.config` fills these from the three input sections; they can also be
passed straight to :func:`bbn.run.solve`.
"""
from __future__ import annotations

import numpy as np

__all__ = ["DEFAULTS"]

DEFAULTS = {
    # rotors and sources
    "StageCount": 2,                 # 1 = front rotor only, 2 = front and rear rotors
    "axial_velocity_tables": False,             # axial velocities from the rotor tables instead of the velocity triangles
    "rotor_noise": True,
    "noise_type": "BOTH",            # BRWI, BRTE or BOTH
    "installation_noise": False,
    "p_noise_type": "BPRI_BL",       # boundary-layer ingestion
    "amiet": False,                  # simplified (Amiet) rotational formulation instead of the full one
    "uniform_inflow": True, "alphae": 0.0, "bpv": 0.0, "wpv": 0.0, "vpv": 0.0, "eoffset": 0.0,
    # boundary-layer ingestion
    "BPRI_correlation": False, "partial_loading": True, "wall": True, "dwall": 0.2486, "bl_height": 0.1,
    "bl_turbulence_table": True, "ua": 1.0, "ut": 2.0, "la": 0.3, "lt": 0.1, "aniso_alpha": 1.0,
    # spectra
    "Karman_spec": True,             # von Karman (True) or Liepmann (False) turbulence spectrum
    "aniso_spec": "Liep",
    "phi_sw": "RZ",                  # wall-pressure model: WA, CH, GY, KG, RZ, VKI
    "Uc": "DEL2",                    # convection velocity: 0.8, GLB, DEL, DEL2
    "lr": "SLZ",                     # spanwise correlation length: COR, ROG, LGL, RGS, CORL, EFP, SLZ
    "L": 0.4,                        # wake length scale: factor C (L = C L_table), 'Pope' or 'BW'
    "baddata": "IGNORE",             # strips flagged in the discard column: IGNORE, REPLACE or DISCARD
    # discretisation, observers, frequencies
    "chapman": False, "emission_angle": False,
    "phi_num": 50, "st_num": 5, "contraction_perc": 100,
    "spectral_study": True, "f_d": 2000.0, "f_l": 50.0, "f_h": 20000.0, "f_num": 50,
    "phi_obs_num": 1, "spectral_phi_obs": [0.0],
    "r0": 2.54,
    "theta": list(np.arange(10.0, 171.0, 20.0) * np.pi / 180),   # theta* from the upstream axis [rad]
}
