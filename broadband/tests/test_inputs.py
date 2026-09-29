"""User inputs: TKE / integral length scale for interaction noise, boundary layers for self noise,
combined totals."""
import json
import math

import numpy as np
import pytest

from bbnoise import webapi
from bbnoise.boundarylayer import make_boundary_layers
from bbnoise.cases import get_case
from bbnoise.model import run_case
from bbnoise.turbulence import LN2, w_rms_from_tke


def _airfoil(**over):
    c = {"type": "airfoil", "airfoil": {"chord": 0.2, "span": 0.5, "U": 60.0},
         "turbulence": {"enabled": True, "spectrum": ["vonkarman"], "tke": 1.5 * 1.8 ** 2, "Lambda": 0.02},
         "self_noise": {"enabled": True, "models": ["goody"],
                        "boundary_layer": {"method": "user", "both": {"delta_star_over_c": 0.008, "H": 1.5}}},
         "observers": {"R": 1.5, "theta_deg": [90, 45, 135]},
         "frequency": {"f_min": 100.0, "f_max": 8000.0, "n": 12}}
    c.update(over)
    return c


def test_tke_to_w_rms():
    assert abs(w_rms_from_tke(1.5 * 2.0 ** 2) - 2.0) < 1e-12


def test_tke_equals_intensity():
    a = run_case(_airfoil())
    b = _airfoil()
    b["turbulence"] = {"enabled": True, "spectrum": ["vonkarman"], "intensity": 1.8 / 60.0, "Lambda": 0.02}
    b = run_case(b)
    assert np.allclose(a.curves[0].G, b.curves[0].G, rtol=1e-12)
    assert abs(a.info["turbulence"]["tke"] - 1.5 * 1.8 ** 2) < 1e-9


def test_larger_length_scale_moves_peak_to_lower_frequency():
    peaks = []
    for L in (0.005, 0.05):
        c = _airfoil()
        c["self_noise"]["enabled"] = False
        c["turbulence"]["Lambda"] = L
        c["frequency"] = {"f_min": 50.0, "f_max": 20000.0, "n": 60}
        r = run_case(c)
        peaks.append(r.f[np.argmax(r.curves[0].G * r.f)])
    assert peaks[1] < peaks[0]


def test_airfoil_both_mechanisms_and_totals():
    r = run_case(_airfoil())
    cats = [c.category for c in r.curves]
    assert cats == ["interaction", "self"]
    tot = [t for t in r.totals if t.label.startswith("total (interaction + self)")][0]
    assert np.allclose(tot.G, r.curves[0].G + r.curves[1].G)
    e = 10 ** (r.curves[0].directivity["oaspl"] / 10) + 10 ** (r.curves[1].directivity["oaspl"] / 10)
    assert np.allclose(tot.directivity["oaspl"], 10 * np.log10(e))
    d = r.to_dict()
    assert len(d["totals"]) == 3 and all(c["category"] in ("interaction", "self") for c in d["curves"])


def test_disabled_sections_are_skipped():
    c = _airfoil()
    c["turbulence"]["enabled"] = False
    r = run_case(c)
    assert [x.category for x in r.curves] == ["self"]


def test_user_boundary_layer_values_and_radial_distribution():
    spec = {"method": "user", "suction": {"delta_star_over_c": {"r_over_R": [0.2, 1.0], "value": [0.02, 0.01]},
                                          "H": 1.6, "beta_c": 2.0, "cf": 0.002},
            "pressure": {"theta_over_c": 0.004, "H": 1.3}}
    bls = make_boundary_layers(spec, chord=0.1, U=100.0, r_over_R=0.6)
    s, p = bls["suction"], bls["pressure"]
    assert abs(s.delta_star - 0.1 * 0.015) < 1e-12
    assert s.H == 1.6 and s.beta_c == 2.0 and s.cf == 0.002
    assert abs(p.delta_star - 0.1 * 0.004 * 1.3) < 1e-12
    with pytest.raises(ValueError):
        make_boundary_layers({"method": "user", "both": {"H": 1.4}}, 0.1, 50.0)


def test_user_boundary_layer_changes_self_noise():
    thin, thick = _airfoil(), _airfoil()
    thick["self_noise"]["boundary_layer"]["both"]["delta_star_over_c"] = 0.02
    a, b = run_case(thin), run_case(thick)
    assert b.curves[1].G.sum() != pytest.approx(a.curves[1].G.sum())


def _cror():
    c = get_case("cror_takeoff")
    c["frequency"] = {"f_min": 300.0, "f_max": 6000.0, "n": 6}
    c["observers"]["theta_deg"] = [90]
    c["formulations"] = ["full"]
    c["self_noise"]["enabled"] = False
    c["rwi"]["spectrum"] = ["vonkarman"]
    for r in c["rotors"]:
        r["n_strips"] = 3
    return c


def test_wake_tke_centreline_and_mean_are_consistent():
    a, b = _cror(), _cror()
    a["rwi"]["wake"] = {"tke_c": 20.0, "Lw_over_s": 0.08, "Lambda": 0.004}
    b["rwi"]["wake"] = {"tke_mean": 20.0 * 0.08 * math.sqrt(math.pi / LN2), "Lw_over_s": 0.08, "Lambda": 0.004}
    ra, rb = run_case(a), run_case(b)
    assert np.allclose(ra.curves[0].G, rb.curves[0].G, rtol=1e-9)
    assert np.allclose(ra.info["wake"]["tke_c"][:2], 20.0)
    assert np.allclose(ra.info["wake"]["Lambda"], 0.004)


def test_rwi_scales_with_tke():
    a, b = _cror(), _cror()
    a["rwi"]["wake"] = {"tke_c": 10.0, "Lw_over_s": 0.08, "Lambda": 0.004}
    b["rwi"]["wake"] = {"tke_c": 40.0, "Lw_over_s": 0.08, "Lambda": 0.004}
    ra, rb = run_case(a), run_case(b)
    assert np.allclose(rb.curves[0].G / ra.curves[0].G, 4.0, rtol=1e-9)


def test_estimate_bl_api():
    r = json.loads(webapi.estimate_bl(json.dumps(get_case("cror_takeoff"))))
    assert r["ok"] and set(r["sides"]) == {"suction", "pressure"}
    assert 0 < r["sides"]["suction"]["delta_star_over_c"] < 0.05
