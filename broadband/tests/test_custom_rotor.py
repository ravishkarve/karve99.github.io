"""Custom rotors: radial chord, stagger and chordwise speed feeding BRWI and BRTE."""
import numpy as np

from bbnoise.boundarylayer import flat_plate
from bbnoise.cases import CASES, get_case
from bbnoise.model import build_rotor, run_case
from bbnoise.rotor import Rotor, full_spectrum, observer_position, simplified_spectrum
from bbnoise.sources import TESource
from bbnoise.tables import blade_from_table

FLUID = {"c0": 340.0, "rho": 1.225, "nu": 1.5e-5}


def _quick(c, n=5):
    c["frequency"]["n"] = n
    c["observers"]["theta_deg"] = [60]
    c["options"] = {"sound_power": False}
    return c


def test_stagger_equal_to_inflow_reproduces_default():
    base = Rotor(B=3, r_tip=0.6, r_hub=0.2, chord=0.05, rpm=4000.0, Ux=40.0, n_strips=3)
    flow = [90.0 - np.degrees(st.psi) for st in base.strips()]
    rs = [st.r / 0.6 for st in base.strips()]
    same = Rotor(B=3, r_tip=0.6, r_hub=0.2, chord=0.05, rpm=4000.0, Ux=40.0, n_strips=3,
                 stagger_deg={"r_over_R": rs, "value": flow})
    for a, b in zip(base.strips(), same.strips()):
        assert abs(a.U - b.U) < 1e-9 and abs(a.psi - b.psi) < 1e-9 and abs(b.aoa_deg) < 1e-9
    src = TESource(lambda s: flat_plate(s.chord, s.U))
    w = 2 * np.pi * np.array([1000.0, 4000.0])
    x = observer_position(5.0, 70)
    for fn in (full_spectrum, simplified_spectrum):
        assert np.allclose(fn(base, src, w, x), fn(same, src, w, x), rtol=1e-9)


def test_stagger_and_UX_overrides():
    rot = Rotor(B=3, r_tip=0.6, r_hub=0.2, chord=0.05, rpm=4000.0, Ux=40.0, n_strips=2,
                stagger_deg=45.0, U_X={"r_over_R": [1 / 3, 1.0], "value": [100.0, 200.0]})
    for st in rot.strips():
        assert abs(np.degrees(st.psi) - 45.0) < 1e-9
        assert abs(st.U - (100.0 + 100.0 * (st.r / 0.6 - 1 / 3) / (2 / 3))) < 1e-9
    # without U_X the chordwise speed is the inflow component along the chord
    r2 = Rotor(B=3, r_tip=0.6, r_hub=0.2, chord=0.05, rpm=4000.0, Ux=40.0, n_strips=1, stagger_deg=45.0)
    st = r2.strips()[0]
    assert abs(st.U - st.W * np.cos(np.radians(st.aoa_deg))) < 1e-9 and st.U < st.W


def test_rear_stagger_changes_brwi_and_brte():
    c = _quick(get_case("custom_cror"))
    c["formulations"] = ["full"]
    a = run_case(c).to_dict()
    c["rotors"][1]["stagger_deg"] = 30.0
    b = run_case(c).to_dict()
    oa = lambda d, cat, rot: [cv["oaspl"] for cv in d["curves"] if cv["category"] == cat and cv["rotor"] == rot]
    assert abs(oa(a, "interaction", "rear")[0] - oa(b, "interaction", "rear")[0]) > 0.5
    assert abs(oa(a, "self", "rear")[0] - oa(b, "self", "rear")[0]) > 0.1
    assert oa(a, "self", "front") == oa(b, "self", "front")          # front rotor untouched
    strips = b["info"]["rotors"]["rear"]["strips"]
    assert all(abs(s["stagger_deg"] - 30.0) < 1e-9 for s in strips)


def test_blade_table_with_stagger_and_UX():
    text = "r_over_R,chord,stagger_deg,U_X\n0.4,0.3,30,120\n1.0,0.2,60,190\n"
    blade = blade_from_table(text, 2.0)
    assert blade["stagger_deg"]["value"] == [30.0, 60.0] and blade["U_X"]["value"] == [120.0, 190.0]
    rot = build_rotor({"B": 9, "r_tip": 2.0, "r_hub": 0.8, "rpm": 900.0, "Ux": 90.0, "blade_table": text}, FLUID)
    st = rot.strips()[-1]
    assert 30 < 90 - np.degrees(st.psi) < 60 and 120 < st.U < 190


def test_custom_cror_case():
    assert "custom_cror" in CASES
    d = run_case(_quick(get_case("custom_cror"))).to_dict()
    cats = {(cv["rotor"], cv["category"], cv["formulation"]) for cv in d["curves"]}
    assert ("rear", "interaction", "eq2.73") in cats and ("front", "self", "eq3.18") in cats
    assert all(np.all(np.isfinite(cv["psd_db"])) for cv in d["curves"] + d["totals"])
