"""Blade and boundary-layer tables, per-rotor boundary layers and per-strip contributions."""
import json
from pathlib import Path

import numpy as np
import pytest

from bbnoise import cli, webapi
from bbnoise.boundarylayer import make_boundary_layers
from bbnoise.io import load_case
from bbnoise.model import build_rotor, run_case
from bbnoise.tables import BL_TEMPLATE, BLADE_TEMPLATE, bl_from_table, blade_from_table

EX = Path(__file__).resolve().parent.parent / "examples"
FLUID = {"c0": 340.0, "rho": 1.225, "nu": 1.5e-5}


def test_blade_table_r_over_R_and_metres():
    b = blade_from_table(BLADE_TEMPLATE)
    assert b["chord"]["r_over_R"][0] == 0.3 and b["chord"]["value"][2] == 0.06
    m = blade_from_table("r;chord;Ux\n0.1;0.05;60\n0.2;0.04;70\n", r_tip=0.2)
    assert m["chord"]["r_over_R"] == [0.5, 1.0] and m["Ux"]["value"] == [60.0, 70.0]
    with pytest.raises(ValueError):
        blade_from_table("r_over_R,foo\n0.5,1\n")
    with pytest.raises(ValueError):
        blade_from_table("r,chord\n0.1,0.05\n")          # r in metres without r_tip


def test_rotor_uses_blade_table():
    spec = {"name": "r", "B": 3, "r_tip": 0.5, "r_hub": 0.1, "rpm": 3000, "n_strips": 4,
            "blade_table": "r_over_R chord\n0.2 0.10\n1.0 0.02\n"}
    rot = build_rotor(spec, FLUID)
    st = rot.strips()
    x = np.array([s.r / 0.5 for s in st])
    assert np.allclose([s.chord for s in st], np.interp(x, [0.2, 1.0], [0.10, 0.02]))


def test_bl_table_long_and_wide_formats_agree():
    long = bl_from_table(BL_TEMPLATE)
    wide_text = ("r_over_R,suction_delta_star_over_c,suction_H,suction_beta_c,pressure_delta_star_over_c,pressure_H\n"
                 "0.3,0.016,1.6,1.5,0.006,1.4\n0.7,0.012,1.6,1.5,0.005,1.4\n1.0,0.010,1.6,1.5,0.005,1.4\n")
    wide = bl_from_table(wide_text)
    for side in ("suction", "pressure"):
        a = make_boundary_layers(long, 0.1, 100.0, r_over_R=0.5)[side]
        b = make_boundary_layers(wide, 0.1, 100.0, r_over_R=0.5)[side]
        assert abs(a.delta_star - b.delta_star) < 1e-12 and a.H == b.H
    s = make_boundary_layers(long, 0.1, 100.0, r_over_R=0.5)["suction"]
    assert abs(s.delta_star - 0.1 * 0.014) < 1e-12 and s.beta_c == 1.5


def test_bl_table_airfoil_single_row_per_side():
    spec = bl_from_table("side\tdelta_star\tH\tcf\nsuction\t0.003\t1.7\t0.002\npressure\t0.0015\t1.4\t\n")
    bls = make_boundary_layers(spec, 0.3, 50.0)
    assert bls["suction"].delta_star == 0.003 and bls["suction"].cf == 0.002
    assert bls["pressure"].cf > 0            # blank -> estimated
    with pytest.raises(ValueError):
        bl_from_table("side,H\nsuction,1.4\npressure,1.4\n")      # no thickness


def test_bl_file_method_and_json_rows():
    rows = json.dumps([{"side": "both", "delta_star_over_c": 0.01, "H": 1.5}])
    bls = make_boundary_layers({"method": "file", "text": rows}, 0.2, 60.0)
    assert abs(bls["pressure"].delta_star - 0.002) < 1e-12


def test_example_with_files_runs_and_strips_sum(tmp_path):
    case = load_case(EX / "cror_files.toml")
    assert Path(case["rotors"][0]["blade_file"]).is_absolute()
    case["frequency"] = {"f_min": 300.0, "f_max": 6000.0, "n": 6}
    case["observers"]["theta_deg"] = [90]
    case["formulations"] = ["full"]
    for r in case["rotors"]:
        r["n_strips"] = 4
    res = run_case(case)
    front = res.info["bl_distribution"]["front"]
    assert front["suction_H"][0] > front["suction_H"][-1]            # H varies along the blade (file)
    assert res.info["rotors"]["front"]["strips"][0]["chord"] != res.info["rotors"]["front"]["strips"][2]["chord"]
    for c in res.curves:
        assert np.allclose(np.asarray(c.strips["G"]).sum(axis=0), c.G)
    d = res.to_dict()["curves"][0]["strips"]
    assert abs(sum(d["share"]) - 1) < 1e-3 and len(d["psd_db"]) == 4


def test_per_rotor_boundary_layers_differ():
    case = load_case(EX / "cror_files.toml")
    case["frequency"] = {"f_min": 500.0, "f_max": 4000.0, "n": 4}
    case["observers"]["theta_deg"] = [90]
    case["formulations"] = ["full"]
    case["brwi"]["enabled"] = False
    case["brte"]["models"] = ["goody"]
    for r in case["rotors"]:
        r["n_strips"] = 3
    res = run_case(case)
    bl = res.info["boundary_layers"]
    assert bl["front"]["suction"]["H"] != bl["rear"]["suction"]["H"]


def test_cli_template_and_strip_outputs(tmp_path):
    f = tmp_path / "bl.csv"
    assert cli.main(["template", "bl", str(f)]) == 0 and "side" in f.read_text()
    assert cli.main(["case", "blandeau_joseph_2011", "-q", "-o", str(tmp_path), "--set", "frequency.n=5",
                     "--set", "observers.theta_deg=[45]"]) == 0
    names = {p.name for p in tmp_path.iterdir()}
    assert "blandeau_joseph_2011_strips.csv" in names and "blandeau_joseph_2011_strip_psd.csv" in names


def test_webapi_parse_table_and_estimate_radial():
    r = json.loads(webapi.parse_table("bl", BL_TEMPLATE, None))
    assert r["ok"] and r["boundary_layer"]["method"] == "user"
    r = json.loads(webapi.parse_table("blade", "r,chord\n0.1,0.05\n0.3,0.04\n", 0.3))
    assert r["ok"] and r["blade"]["chord"]["r_over_R"][-1] == 1.0
    bad = json.loads(webapi.parse_table("bl", "x,y\n1,2\n", None))
    assert not bad["ok"]
    from bbnoise.cases import get_case
    e = json.loads(webapi.estimate_bl(json.dumps(get_case("cror_takeoff")), "rear"))
    assert e["ok"] and len(e["radial"]) == 10 and "rear" in e["where"]


def test_non_positive_user_values_rejected():
    with pytest.raises(ValueError, match="cf must be positive"):
        make_boundary_layers({"method": "user", "both": {"delta_star_over_c": 0.01, "cf": 0.0}}, 0.1, 50.0)
