"""BoB 3.5 port: MATLAB helpers, input readers, and agreement with BoB 3.5 run in Octave.

The reference spectra in tests/data/bob were produced by running BoB 3.5 (unmodified
models; see README for the Octave compatibility shims) on the synthetic inputs of
bbnoise.bob.synthetic, which are made-up numbers.
"""
import json
import os
from pathlib import Path

import numpy as np
import pytest
import scipy.io as sio
from scipy.special import erf

from bbnoise import cli, webapi
from bbnoise.bob import BoBError, parse_launch_file, run_bob
from bbnoise.bob.case import run_bob_raw
from bbnoise.bob.inputs import read_bl_file, read_bl_ingestion
from bbnoise.bob.launch import launch_text
from bbnoise.bob.mlab import erfz, fzero, interp_idx, mlinspace, mround
from bbnoise.bob.pp import compute_results_pylon, write_outputs_pylon
from bbnoise.bob.synthetic import (bl_text, synthetic_bl_tables, synthetic_ingestion, synthetic_inputs,
                                   synthetic_wake)
from bbnoise.cases import CASES
from bbnoise.model import run_case

DATA = Path(__file__).parent / "data" / "bob"


# --- MATLAB helpers ----------------------------------------------------------------------

def test_mround_half_away_from_zero():
    assert mround(np.array([0.5, 1.5, 2.5, -0.5, -2.5])).tolist() == [1, 2, 3, -1, -3]


def test_mlinspace_single_point_is_end():
    assert mlinspace(2.0, 7.0, 1).tolist() == [7.0]


def test_interp_idx_by_index():
    v = np.array([0.0, 10.0, 20.0])
    assert interp_idx(v, np.array([1.0, 1.5, 3.0])).tolist() == [0.0, 5.0, 20.0]


def test_erfz_matches_erf_on_real_axis():
    x = np.linspace(-2, 2, 9)
    assert np.allclose(erfz(x + 0j).real, erf(x), atol=1e-8)


def test_erfz_symmetry():
    z = np.array([0.3 + 0.7j, 1.2 - 0.4j, 2.0 + 1.5j])
    assert np.allclose(erfz(np.conj(z)), np.conj(erfz(z)), rtol=1e-10)
    assert np.allclose(erfz(-z), -erfz(z), rtol=1e-10)


def test_fzero_bracket_search_from_scalar():
    assert fzero(lambda x: x ** 3 - 2.0, 5.0) == pytest.approx(2 ** (1 / 3), rel=1e-12)


# --- launch files and input files ---------------------------------------------------------

LAUNCH = """
% comment line
opt.StageCount = 2;      % trailing comment
opt.noise_type = 'BRTE'; opt.amiet = true;
opt.theta = [30 60 90]*pi/180;
opt.bl_files = {'a.txt','b.txt'};
opt.f_num = 2^4;
"""


def test_parse_launch_file():
    o = parse_launch_file(LAUNCH, defaults=False)
    assert o["StageCount"] == 2 and o["noise_type"] == "BRTE" and o["amiet"] is True
    assert np.allclose(o["theta"], np.radians([30, 60, 90]))
    assert o["bl_files"] == ["a.txt", "b.txt"] and o["f_num"] == 16


def test_launch_text_round_trip():
    o = parse_launch_file(LAUNCH)
    back = parse_launch_file(launch_text(o))
    for k, v in o.items():
        if isinstance(v, (list, np.ndarray)) and not isinstance(v, str) and np.size(v) and \
                not isinstance(np.ravel(v)[0], str):
            assert np.allclose(np.asarray(back[k], float), np.asarray(v, float)), k
        else:
            assert back[k] == v, k


def test_read_bl_file_columns():
    tab = synthetic_bl_tables()[0]
    t = read_bl_file(bl_text(tab))
    assert np.allclose(t["R"], tab[:, 0]) and np.allclose(t["d"], tab[:, 1])
    assert np.allclose(t["mom_th"], tab[:, 3]) and np.allclose(t["tauwall"], tab[:, 11])


def test_read_bl_ingestion_text():
    t = read_bl_ingestion("#z\tua\tla\tut\tlt\n0.01\t1\t0.3\t2\t0.15\n0.02\t1\t0.29\t2\t0.145\n")
    assert t["bl_wnd"].tolist() == [0.01, 0.02] and t["bl_lt"].tolist() == [0.15, 0.145]


def test_webapi_bob_parse():
    def call(kind, payload):
        r = webapi.bob_parse(kind, payload)
        return json.loads(r) if isinstance(r, str) else r
    r = call("bl", bl_text(synthetic_bl_tables()[1]))
    assert r["ok"] and r["rows"] == 5 and len(r["table"]["delta"]) == 5
    r = call("launch", LAUNCH)
    assert r["ok"] and r["options"]["noise_type"] == "BRTE"
    r = call("launch_out", json.dumps({"StageCount": 1, "noise_type": "BRWI"}))
    assert r["ok"] and "opt.noise_type = 'BRWI';" in r["text"]
    assert not call("nope", "")["ok"]


# --- agreement with BoB 3.5 (Octave) -----------------------------------------------------

def _synthetic_case(options):
    inp = synthetic_inputs()
    return {"type": "bob", "options": options, "inputs": inp,
            "bl_files": [bl_text(t) for t in synthetic_bl_tables()], "wake": synthetic_wake(),
            "bl_ingestion": synthetic_ingestion()}


def _ref(name):
    d = np.load(DATA / f"{name}.npz")
    return json.loads(str(d["options"])), {k: d[k] for k in d.files if k != "options"}


@pytest.mark.parametrize("name", sorted(p.stem for p in DATA.glob("*.npz")))
def test_matches_bob_reference(name):
    opt, ref = _ref(name)
    out = run_bob_raw(_synthetic_case(opt))
    for k, a in ref.items():
        if a.size == 1 and a.ravel()[0] == 0:
            continue
        b = np.asarray(out.Spps[k]).reshape(a.shape)
        assert np.allclose(b, a, rtol=1e-11, atol=0), k


def test_cli_bob_writes_bob_files(tmp_path):
    """Full file route: launch_BoB.m + CaseInputs .mat + BL files + Wake_data.mat -> BoB's .dat files."""
    opt, _ = _ref("syn_both_full")
    inp = synthetic_inputs()
    (tmp_path / "INPUT" / "BL").mkdir(parents=True)
    sio.savemat(tmp_path / "INPUT" / "synth.mat", inp)
    sio.savemat(tmp_path / "INPUT" / "Wake_data.mat", synthetic_wake())
    for i, t in enumerate(synthetic_bl_tables()):
        (tmp_path / "INPUT" / "BL" / f"bl_{i + 1}.txt").write_text(bl_text(t))
    opt.update({"input_folder": "INPUT/", "CaseInputs": "synth.mat", "Wake_data_file": "INPUT/Wake_data.mat",
                "BL_folder": "INPUT/BL/", "bl_files": [f"bl_{i}.txt" for i in range(1, 5)]})
    (tmp_path / "launch_BoB.m").write_text(launch_text(opt))
    assert cli.main(["bob", str(tmp_path / "launch_BoB.m"), "-o", str(tmp_path / "OUT"), "-q"]) == 0
    for ref in DATA.glob("syn_both_full__*.dat"):
        got = (tmp_path / "OUT" / ref.name.split("__", 1)[1]).read_text()
        assert got == ref.read_text(), ref.name
    m = sio.loadmat(tmp_path / "OUT" / "BoB_output.mat", struct_as_record=False)
    assert "Spps" in m


def test_bpri_bl_files_match_bob(tmp_path):
    """pp_pylon.m: BPRI_BL PWL spectra (total and per strip) and 1/3-octave PWL, byte for byte."""
    opt, _ = _ref("syn_bpri_bl")
    out = run_bob_raw(_synthetic_case(opt))
    res = compute_results_pylon(out)
    write_outputs_pylon(out, tmp_path, res)
    refs = list(DATA.glob("syn_bpri_bl__*.dat"))
    assert refs
    for ref in refs:
        assert (tmp_path / ref.name.split("__", 1)[1]).read_text() == ref.read_text(), ref.name
    one = run_bob_raw(_synthetic_case(dict(opt, spectral_phi_obs=[0.0])))
    with pytest.raises(BoBError):                       # pp_pylon.m writes PWL_B1(1:3,:,:)
        write_outputs_pylon(one, tmp_path / "one")
    narrow = run_bob_raw(_synthetic_case(dict(opt, f_l=300.0, f_h=3000.0)))
    res = compute_results_pylon(narrow)                 # BoB: bands fail -> -999, no files
    assert res["PWL_B1"] == -999 and write_outputs_pylon(narrow, tmp_path / "narrow", res) == []


def test_bob_failure_paths_raise_like_bob():
    opt, _ = _ref("syn_both_full")
    with pytest.raises(BoBError):                       # BRWI.m needs flow.L, never set with amiet
        run_bob_raw(_synthetic_case(dict(opt, noise_type="BRWI", amiet=True)))
    with pytest.raises(BoBError):                       # inputs.m handles 0 % and 100 % only
        run_bob_raw(_synthetic_case(dict(opt, contraction_perc=50)))


@pytest.mark.parametrize("key", [k for k in CASES if k.startswith("bob_")])
def test_bob_cases_run(key):
    case = json.loads(json.dumps(CASES[key]))
    case["options"].update({"f_num": 3, "phi_num": 12})
    res = run_case(case)
    assert res.curves and res.totals
    for c in res.curves:
        assert np.all(np.isfinite(c.G)) and c.G.max() > 0


# BoB's own example (not redistributed here): set BOB_DIR to an unpacked BoB 3.5 folder.
BOB_EXAMPLE = Path(os.environ.get("BOB_DIR", Path.home() / "Documents" / "bob_3.5")) / "examples"


@pytest.mark.skipif(not (BOB_EXAMPLE / "launch_BoB.m").exists(), reason="BoB 3.5 example not available")
def test_bob_shipped_example():
    from bbnoise.bob.case import case_from_launch
    ref = sio.loadmat(BOB_EXAMPLE / "OUTPUT" / "BoB_output.mat", struct_as_record=False)
    out = run_bob_raw(case_from_launch(BOB_EXAMPLE / "launch_BoB.m"))
    S = ref["Spps"][0, 0]
    for k in S._fieldnames:
        a = np.asarray(getattr(S, k))
        if a.size > 1:
            assert np.allclose(np.asarray(out.Spps[k]).reshape(a.shape), a, rtol=1e-10, atol=0), k
