"""Thesis eqs. 3.18 / 5.7, thesis wall-pressure models and the thesis cases."""
import numpy as np
import pytest

from bbnoise import cli
from bbnoise.airfoil import te_response
from bbnoise.boundarylayer import flat_plate
from bbnoise.cases import CASES, get_case
from bbnoise.model import run_case
from bbnoise.rotor import Rotor
from bbnoise.thesis import eq318_spectrum, eq57_spectrum, l_te
from bbnoise.wallpressure import WPS_MODELS, BoundaryLayer, coles_pi, wps_normalised


def _rotor():
    return Rotor(B=2, r_tip=1.0, r_hub=0.9, chord=0.1, rpm=1948.0, Ux=0.0, n_strips=1), \
        (lambda s: flat_plate(s.chord, s.U))


def test_eq318_matches_eq57_at_high_frequency():
    rot, blf = _rotor()
    w = 2 * np.pi * np.array([2000.0, 6000.0])
    for th in (40, 140):
        a = eq318_spectrum(rot, blf, "goody", w, 50.0, th)
        b = eq57_spectrum(rot, blf, "goody", w, 50.0, th)
        assert np.all(np.abs(10 * np.log10(a / b)) < 0.3)


def test_eq318_per_strip_sums_and_gauss_convergence():
    rot = Rotor(B=3, r_tip=0.6, r_hub=0.2, chord=0.05, rpm=4000.0, Ux=30.0, n_strips=3)
    blf = lambda s: flat_plate(s.chord, s.U)
    w = 2 * np.pi * np.array([500.0, 3000.0])
    tot, parts = eq318_spectrum(rot, blf, "goody", w, 10.0, 60, per_strip=True)
    assert np.allclose(tot, sum(parts))
    hi = eq318_spectrum(rot, blf, "goody", w, 10.0, 60, n_gauss=8)
    assert np.all(np.abs(10 * np.log10(hi / tot)) < 0.05)


def test_l_te_thesis_denominator_is_finite_at_zero_theta_b():
    kX = np.array([100.0, 100.0])
    L = l_te(kX, -kX, 0.05, 0.3, 0.24)
    assert np.all(np.isfinite(L)) and np.all(np.abs(L) > 0)


def test_te_response_subcritical_is_bounded():
    M, K = 0.5, 30.0
    mub = K * M / (1 - M * M)
    ky = np.geomspace(1.01, 100.0, 50) * mub * np.sqrt(1 - M * M)
    I = te_response(np.full_like(ky, K), 1 / 0.7, ky, M, 0.3 * K, True)
    assert np.all(np.isfinite(I)) and np.all(np.abs(I) < 1.0)


def test_thesis_wall_pressure_models():
    assert {"kim_george", "rozenberg_2010"} <= set(WPS_MODELS)
    zpg = BoundaryLayer(Ue=50.0, delta_star=0.002, delta=0.016, H=1.3, beta_c=0.0, Pi=0.2).complete()
    w = np.geomspace(0.05, 5.0, 20)
    assert np.all(np.abs(10 * np.log10(wps_normalised("rozenberg_2010", w, zpg) /
                                       wps_normalised("goody", w, zpg))) < 0.5)
    # adverse pressure gradient raises the thesis Rozenberg spectrum at low/mid frequency
    apg = BoundaryLayer(Ue=50.0, delta_star=0.002, delta=0.016, H=1.6, beta_c=3.0).complete()
    lo = np.geomspace(0.05, 0.5, 5)
    assert np.all(wps_normalised("rozenberg_2010", lo, apg) > wps_normalised("rozenberg_2010", lo, zpg))
    assert coles_pi(apg) > coles_pi(zpg)


def test_garcia_sagrado_model_ranking():
    c = get_case("garcia_sagrado_naca0012")
    c["frequency"]["n"] = 12
    res = run_case(c).to_dict()
    oa = {cv["variant"]: cv["oaspl"] for cv in res["curves"] if cv["category"] == "self"}
    # thesis p. 93: Kim-George over-predicts mid/high frequencies relative to the other models
    assert oa["kim_george"] > max(oa["goody"], oa["rozenberg_2010"]) + 2.0


@pytest.mark.parametrize("cond", ["takeoff", "cruise", "approach"])
def test_thesis_cror_cases_run(cond):
    c = get_case(f"blandeau_cror_{cond}")
    c["frequency"]["n"] = 6
    c["observers"]["theta_deg"] = [60]
    c["options"] = {"sound_power": False}
    c["formulations"] = ["eq3.18", "full"]
    res = run_case(c).to_dict()
    forms = {cv["formulation"] for cv in res["curves"]}
    assert forms == {"eq3.18", "full"}
    # the thesis formulation gives self noise only; its totals pair it with the full interaction noise
    assert all(cv["category"] == "self" for cv in res["curves"] if cv["formulation"] == "eq3.18")
    labels = [t["label"] for t in res["totals"]]
    assert any("eq. 3.18" in lab and "full interaction" in lab for lab in labels)
    for cv in res["curves"] + res["totals"]:
        assert np.all(np.isfinite(cv["psd_db"])) and cv["oaspl"] < 150


def test_thesis_cases_registered_and_cli_accepts_thesis_forms(tmp_path, capsys):
    for k in ("garcia_sagrado_naca0012", "blandeau_cror_takeoff", "blandeau_cror_cruise", "blandeau_cror_approach"):
        assert k in CASES
    rc = cli.main(["case", "blandeau_joseph_2011", "--formulation", "eq3.18", "--formulation", "eq5.7",
                   "--set", "frequency.n=5", "--set", "observers.theta_deg=[60]", "-q", "--no-plots"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "eq. 3.18" in out and "eq. 5.7" in out
