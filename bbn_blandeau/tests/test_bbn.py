"""Tests: reference spectra through the three input sections, helpers, VKI model, CLI and web API."""
import json
import math

import numpy as np
import pytest
from scipy.special import erf

import bbn
from bbn import cli, webapi
from bbn.config import solver_runs
from bbn.examples import bl_text, default_case, synthetic_bl_tables, synthetic_ingestion, synthetic_wake, template
from bbn.models import _phi_vki
from bbn.numerics import erfz, interp_idx, linspace_end, root_from_start, round_away
from bbn.run import solve

from pathlib import Path

DATA = Path(__file__).parent / "data"


# --- helpers ---------------------------------------------------------------------------------

def test_round_away():
    assert round_away(np.array([0.5, 1.5, 2.5, -0.5, -2.5])).tolist() == [1, 2, 3, -1, -3]


def test_linspace_end():
    assert linspace_end(2.0, 7.0, 1).tolist() == [7.0]


def test_interp_idx():
    assert interp_idx(np.array([0.0, 10.0, 20.0]), np.array([1.0, 1.5, 3.0])).tolist() == [0.0, 5.0, 20.0]


def test_erfz():
    x = np.linspace(-2, 2, 9)
    assert np.allclose(erfz(x + 0j).real, erf(x), atol=1e-8)
    z = np.array([0.3 + 0.7j, 1.2 - 0.4j, 2.0 + 1.5j])
    assert np.allclose(erfz(np.conj(z)), np.conj(erfz(z)), rtol=1e-10)
    assert np.allclose(erfz(-z), -erfz(z), rtol=1e-10)


def test_root_from_start():
    assert root_from_start(lambda x: x ** 3 - 2.0, 5.0) == pytest.approx(2 ** (1 / 3), rel=1e-12)


# --- VKI wall-pressure model ----------------------------------------------------------------------

def test_vki_formula():
    ds, th, tw, dpdx, rho, ue, nu, c0 = 1.1e-3, 7.6e-4, 25.0, 2.5e4, 1.2, 120.0, 1.5e-5, 340.0
    om = np.geomspace(500, 1e5, 5)
    w = om * ds / ue
    cf = tw / (0.5 * rho * ue ** 2)
    bc = th / tw * dpdx
    rt = (ds / ue) / (nu / (tw / rho))
    one_sided = tw ** 2 * ds / ue * (5.41 + cf * (bc + 1) ** 5.41) * w / (
        w ** 2 + w + (bc + 1) * ue / c0 + (w + 3.6) * w ** 4.76 / (cf * rt ** 5.83))
    assert np.allclose(np.real(_phi_vki(om, ds, th, tw, dpdx, rho, ue, nu, c0)), 0.5 * one_sided, rtol=1e-12)


@pytest.mark.parametrize("formulation", ["full", "simplified"])
def test_vki_in_self_noise(formulation):
    case = default_case()
    case["noise_model"].update(interaction=False, self_noise=["front"], formulation=formulation,
                               frequency={"min": 200.0, "max": 8000.0, "n": 5}, azimuth_points=16)
    case["spectra"]["wall_pressure"].update(model="vki", convection="gliebe", correlation_length="corcos")
    res = bbn.run(case)
    psd = res.curves[0].psd
    assert np.all(np.isfinite(psd)) and np.all(psd > 0)
    case["spectra"]["wall_pressure"]["model"] = "rozenberg"
    ref = bbn.run(case).curves[0].psd
    assert np.all(np.abs(10 * np.log10(psd / ref)) < 20)


# --- reference spectra through the three input sections --------------------------------------------

def _reference_rotor():
    """The rotor of the reference runs (arrays of different lengths, resampled by position)."""
    r1, r2 = np.linspace(0.070, 0.250, 13), np.linspace(0.070, 0.230, 13)
    return {"stages": 2, "mach": 0.2, "c0": 340.0, "rho": 1.2, "gap": 0.22, "scale": 1.0,
            "front": {"blades": 10, "omega": 300.0,
                      "blade": {"r": r1.tolist(), "chord": np.linspace(0.062, 0.044, 12).tolist(),
                                "stagger_deg": np.degrees(np.linspace(0.62, 1.16, 13)).tolist()}},
            "rear": {"blades": 8, "omega": 270.0,
                     "blade": {"r": r2.tolist(), "chord": np.linspace(0.064, 0.046, 12).tolist(),
                               "stagger_deg": np.degrees(np.linspace(0.58, 1.08, 13)).tolist()}}}


def _reference_case(nm, spectra):
    bl = synthetic_bl_tables()
    base_nm = {"strips": 5, "frequency": {"min": 50.0, "max": 20000.0, "n": 12},
               "observers": {"theta_deg": [30, 60, 90, 120, 150], "radius": 2.54}}
    base_sp = {"interaction": {"turbulence": "von_karman", "length_scale": 0.4,
                               "wake": {k: v.tolist() for k, v in synthetic_wake().items()}},
               "wall_pressure": {"model": "rozenberg", "convection": "del_alamo_fit", "correlation_length": "salze",
                                 # the reference runs read these tables as text (9 significant digits)
                                 "boundary_layers": {k: bl_text(t) for k, t in
                                                     zip(["front_top", "front_bottom", "rear_top", "rear_bottom"], bl)}},
               "ingestion": {"turbulence": "von_karman",
                             "table": {k: np.asarray(v).tolist() for k, v in synthetic_ingestion().items()}}}
    for k, v in spectra.items():
        base_sp[k] = dict(base_sp[k], **v)
    return {"rotor": _reference_rotor(), "noise_model": dict(base_nm, **nm), "spectra": base_sp}


INGEST = {"strips": 5, "frequency": {"min": 50.0, "max": 20000.0, "n": 6}, "observers": {"theta_deg": [120],
          "radius": 2.54}, "azimuth_points": 24, "bl_ingestion": True,
          "ingestion": {"wall_distance": 0.27, "bl_height": 0.1, "hard_wall": True,
                        "observer_azimuth_deg": [0, 90, 180]}}

CASES = {
    "syn_both_full": ({"interaction": True, "self_noise": ["front", "rear"]}, {}),
    "syn_brte_amiet": ({"self_noise": ["front", "rear"], "formulation": "simplified", "azimuth_points": 24},
                       {"wall_pressure": {"convection": "gliebe", "correlation_length": "roger"}}),
    "syn_brte_amiet_gy_lgl": ({"self_noise": ["front", "rear"], "formulation": "simplified", "azimuth_points": 24},
                              {"wall_pressure": {"model": "goody", "convection": "constant",
                                                 "correlation_length": "roger_delta"}}),
    "syn_brte_gy_lgl": ({"self_noise": ["front", "rear"]},
                        {"wall_pressure": {"model": "goody", "convection": "del_alamo",
                                           "correlation_length": "roger_delta"}}),
    "syn_brwi_liep": ({"interaction": True}, {"interaction": {"turbulence": "liepmann", "length_scale": "pope"}}),
    "syn_bpri_bl": (dict(INGEST, ingestion=dict(INGEST["ingestion"], partial_loading=True, blade_correlation=True)), {}),
    "syn_bpri_bl_nocorr": (dict(INGEST, ingestion=dict(INGEST["ingestion"], partial_loading=False,
                                                       blade_correlation=False)), {}),
}

KEYS = {"BRWI": "interaction", "BRTE1": "self_front", "BRTE2": "self_rear", "BPRI": "ingestion_total",
        "BPRINW": "ingestion_nw", "BPRIC1": "ingestion_c1", "BPRIC2": "ingestion_c2", "BPRIA": "ingestion_a"}


@pytest.mark.parametrize("name", sorted(CASES))
def test_reference_spectra(name):
    nm, sp = CASES[name]
    res = bbn.run(_reference_case(nm, sp))
    ref = np.load(DATA / f"{name}.npz")
    curves = {c.key: c for c in res.curves}
    checked = 0
    for k, key in KEYS.items():
        if k not in ref.files or ref[k].size == 1:
            continue
        S = ref[k]
        S = S[..., None] if S.ndim == 3 else S
        for g in range(S.shape[3]):
            ck = key if g == 0 else f"{key}_{g}"
            expect = 4 * math.pi * np.abs(S[:, :, -1, g]).T
            assert np.allclose(curves[ck].psd, expect, rtol=1e-11, atol=0), (ck, g)
            checked += 1
    assert checked


def test_reference_runs_one_solver_call_for_both():
    nm, sp = CASES["syn_both_full"]
    runs = solver_runs(_reference_case(nm, sp))
    assert [(p, o["noise_type"]) for p, o, _ in runs] == [("rotor", "BOTH")]


def test_solver_called_directly():
    """solve() with the options built from the sections gives the same spectra."""
    nm, sp = CASES["syn_brwi_liep"]
    _, opt, kw = solver_runs(_reference_case(nm, sp))[0]
    out = solve(opt, **kw)
    assert np.allclose(out.Spps["BRWI"], np.load(DATA / "syn_brwi_liep.npz")["BRWI"], rtol=1e-11, atol=0)


def test_default_case_json_in_sync():
    web = json.loads((Path(__file__).parent.parent / "web" / "default_case.json").read_text())
    assert web == json.loads(json.dumps(default_case()))


# --- input validation, outputs, CLI and web API -------------------------------------------------------

def test_validation_messages():
    c = default_case()
    c["noise_model"].update(interaction=False, self_noise=[], bl_ingestion=False)
    with pytest.raises(bbn.SolverError, match="select at least one source"):
        bbn.run(c)
    c = default_case()
    c["rotor"]["stages"] = 1
    with pytest.raises(bbn.SolverError, match="two rotors"):
        bbn.run(c)
    c = default_case()
    c["spectra"]["wall_pressure"]["model"] = "nope"
    with pytest.raises(bbn.SolverError, match="unknown wall-pressure model"):
        bbn.run(c)
    c = default_case()
    c["noise_model"].update(formulation="simplified")
    c["spectra"]["wall_pressure"]["convection"] = "del_alamo_fit"
    with pytest.raises(bbn.SolverError, match="full formulation only"):
        bbn.run(c)


def test_single_rotor_self_noise_and_tables_as_text():
    c = default_case()
    c["rotor"]["stages"] = 1
    del c["rotor"]["rear"]
    c["noise_model"].update(interaction=False, self_noise=["front"], frequency={"min": 300, "max": 6000, "n": 4})
    tabs = c["spectra"]["wall_pressure"]["boundary_layers"]
    tabs["front_top"] = bl_text(synthetic_bl_tables()[0])
    c["rotor"]["front"]["blade"] = template("blade")
    res = bbn.run(c)
    assert [cv.key for cv in res.curves] == ["self_front"]
    d = res.to_dict()
    json.dumps(d, allow_nan=False)
    assert d["curves"][0]["third_octave"]["fc"]


def test_cli_run_and_template(tmp_path):
    case = tmp_path / "case.json"
    assert cli.main(["template", "case", str(case)]) == 0
    c = json.loads(case.read_text())
    c["noise_model"].update(frequency={"min": 200, "max": 5000, "n": 4}, observers={"theta_deg": [60, 90]})
    case.write_text(json.dumps(c))
    assert cli.main(["run", str(case), "-o", str(tmp_path / "out"), "-q"]) == 0
    files = {p.name for p in (tmp_path / "out").iterdir()}
    assert {"results.json", "spectra.csv", "directivity.csv", "sound_power.csv"} <= files
    head = (tmp_path / "out" / "spectra.csv").read_text().splitlines()[1]
    assert head.startswith("f_hz")


def test_webapi():
    r = json.loads(webapi.run(json.dumps(dict(default_case(), noise_model=dict(
        default_case()["noise_model"], interaction=True, self_noise=[], frequency={"min": 300, "max": 3000, "n": 3})))))
    assert r["ok"] and r["result"]["curves"][0]["key"] == "interaction"
    t = json.loads(webapi.parse_table("bl", template("bl")))
    assert t["ok"] and len(t["table"]["delta"]) == 5
    assert json.loads(webapi.parse_table("wake", "bw wrms_bg\n1 2\n"))["ok"] is False


def test_example_toml_with_table_files():
    case = bbn.load(Path(__file__).parent.parent / "examples" / "cror.toml")
    case["noise_model"].update(frequency={"min": 300, "max": 6000, "n": 3}, observers={"theta_deg": [90]})
    res = bbn.run(case)
    assert [c.key for c in res.curves] == ["interaction", "self_front", "self_rear"]
    assert all(np.all(c.psd > 0) for c in res.curves)
