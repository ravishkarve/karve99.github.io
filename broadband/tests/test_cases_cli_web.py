import json

import numpy as np
import pytest

from bbnoise import cli, webapi
from bbnoise.cases import CASES, get_case
from bbnoise.model import run_case, third_octave


def _quick(case):
    case["frequency"] = {"f_min": 200.0, "f_max": 8000.0, "n": 8}
    obs = case.get("observers", {})
    obs["theta_deg"] = obs.get("theta_deg", [90])[:2]
    case["observers"] = obs
    for r in case.get("rotors", []):
        r["n_strips"] = min(r.get("n_strips", 4), 3)
    return case


@pytest.mark.parametrize("key", list(CASES))
def test_literature_case_runs(key):
    res = run_case(_quick(get_case(key)))
    assert res.curves
    for c in res.curves:
        assert np.all(np.isfinite(c.G)) and np.all(c.G >= 0) and c.G.max() > 0
    d = res.to_dict()
    json.dumps(d, allow_nan=False)


def test_cror_rwi_dominates_self_noise():
    res = run_case(_quick(get_case("cror_takeoff")))
    oa = {c.label: 10 * np.log10(np.trapezoid(c.G, res.f)) for c in res.curves}
    rwi = max(v for k, v in oa.items() if "wake" in k)
    te = max(v for k, v in oa.items() if "self" in k)
    assert rwi > te + 10


def test_third_octave_energy_conserved():
    f = np.geomspace(100, 10000, 200)
    G = np.full_like(f, 1e-6)
    fc, spl = third_octave(f, G)
    tot = 10 * np.log10(np.sum(10 ** (spl / 10)))
    lo, hi = fc[0] / 2 ** (1 / 6), fc[-1] * 2 ** (1 / 6)
    assert abs(tot - 10 * np.log10(1e-6 * (hi - lo) / 4e-10)) < 0.05


def test_cli_commands(tmp_path, capsys):
    assert cli.main(["list"]) == 0
    assert cli.main(["case", "bpm_naca0012_te", "-q", "--no-plots", "-o", str(tmp_path),
                     "--set", "frequency.n=6"]) == 0
    assert any(p.suffix == ".csv" for p in tmp_path.iterdir())
    f = tmp_path / "c.json"
    assert cli.main(["example", "paterson_amiet_1976", str(f)]) == 0
    assert cli.main(["run", str(f), "-q", "--set", "frequency.n=5", "--set", 'turbulence.spectrum="liepmann"']) == 0
    assert cli.main(["wps", "--Ue", "40", "--delta-star", "0.002", "--beta-c", "1"]) == 0
    out = capsys.readouterr().out
    assert "dominique_g" in out


def test_webapi_roundtrip():
    m = json.loads(webapi.meta())
    assert m["ok"] and len(m["wps_models"]) == 7 and len(m["cases"]) == len(CASES)
    c = json.loads(webapi.case("paterson_amiet_1976"))["case"]
    c["frequency"]["n"] = 6
    r = json.loads(webapi.run(json.dumps(c)))
    assert r["ok"] and len(r["result"]["curves"]) == 2
    w = json.loads(webapi.wall_pressure(json.dumps({"Ue": 40, "delta_star": 0.002, "beta_c": 1.0})))
    assert w["ok"] and len(w["models"]) == 7
    bad = json.loads(webapi.run(json.dumps({"type": "nonsense"})))
    assert not bad["ok"] and "unknown case type" in bad["error"]
