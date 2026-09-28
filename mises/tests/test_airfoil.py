"""Aerofoil coordinates in Selig / Lednicer format placed in a cascade."""
import math

import numpy as np
import pytest

from pymises import Blade, CascadeSolver, FlowConditions
from pymises.cli import main
from pymises.config import ConfigError, build_blade, build_case, parse_config
from pymises.geometry import normalise_airfoil, parse_airfoil_coordinates


@pytest.fixture(scope="module")
def naca4412_text():
    return Blade.naca4("4412", pitch=1.0, n_points=35).to_selig()


def _lednicer(text):
    _, x, y, _ = parse_airfoil_coordinates(text)
    i = int(np.argmin(x))
    up = np.c_[x[:i + 1][::-1], y[:i + 1][::-1]]
    lo = np.c_[x[i:], y[i:]]
    rows = [f"{a:.6f} {b:.6f}" for a, b in up] + [""] + [f"{a:.6f} {b:.6f}" for a, b in lo]
    return f"NACA 4412\n{len(up)}. {len(lo)}.\n\n" + "\n".join(rows)


def test_parse_selig(naca4412_text):
    name, x, y, fmt = parse_airfoil_coordinates(naca4412_text)
    assert (name, fmt, x.size) == ("NACA 4412", "selig", 69)
    assert x[0] == pytest.approx(1.0, abs=1e-3) and y[0] > y[-1]      # starts at TE, upper first


def test_parse_accepts_commas_comments_and_no_name(naca4412_text):
    lines = naca4412_text.splitlines()[1:]
    text = "# exported from a CAD tool\n" + "\n".join(l.strip().replace(" ", ",", 1).replace(" ", "")
                                                       for l in lines)
    name, x, _, _ = parse_airfoil_coordinates(text)
    assert name == "aerofoil" and x.size == 69


def test_lednicer_matches_selig(naca4412_text):
    a = Blade.from_selig(naca4412_text, stagger=30, solidity=1.2)
    b = Blade.from_selig(_lednicer(naca4412_text), stagger=30, solidity=1.2)
    assert b.meta["format"] == "lednicer"
    assert np.allclose(a.x, b.x, atol=2e-6) and np.allclose(a.y, b.y, atol=2e-6)


def test_lednicer_count_mismatch_raises(naca4412_text):
    bad = _lednicer(naca4412_text).replace("35. 35.", "35. 36.")
    with pytest.raises(ValueError, match="Lednicer"):
        parse_airfoil_coordinates(bad)


@pytest.mark.parametrize("text, msg", [
    ("", "no coordinate pairs"),
    ("foil\n0 0\n1 0\n", "at least 8"),
    ("foil\n1 0\n0.5 0.1\nnot a number here\n", "could not read"),
])
def test_parse_errors(text, msg):
    with pytest.raises(ValueError, match=msg):
        parse_airfoil_coordinates(text)


def test_contour_must_start_at_trailing_edge(naca4412_text):
    _, x, y, _ = parse_airfoil_coordinates(naca4412_text)
    i = int(np.argmin(x))
    xs, ys = np.r_[x[i:], x[1:i + 1]], np.r_[y[i:], y[1:i + 1]]     # starts at the LE
    with pytest.raises(ValueError, match="trailing edge"):
        normalise_airfoil(xs, ys)


def test_cascade_placement(naca4412_text):
    b = Blade.from_selig(naca4412_text, stagger=30.0, solidity=1.25, chord=2.0)
    assert b.chord == pytest.approx(2.0, rel=2e-3)
    assert b.stagger == pytest.approx(30.0, abs=0.1)
    assert b.pitch == pytest.approx(1.6)
    assert b.max_thickness == pytest.approx(0.12, abs=2e-3)
    a1, a2 = b.estimated_metal_angles()
    assert a1 > 30.0 > a2                      # positive camber turns flow towards axial
    f = Blade.from_selig(naca4412_text, stagger=-20.0, pitch=0.8, flip=True)
    f1, f2 = f.estimated_metal_angles()
    assert f1 < -20.0 < f2 and f.stagger == pytest.approx(-20.0, abs=0.1)
    with pytest.raises(ValueError, match="exactly one"):
        Blade.from_selig(naca4412_text, stagger=30.0)


def test_clockwise_input_gives_same_blade(naca4412_text):
    lines = naca4412_text.splitlines()
    rev = "\n".join([lines[0]] + lines[1:][::-1])
    a = Blade.from_selig(naca4412_text, stagger=25, pitch=0.9)
    b = Blade.from_selig(rev, stagger=25, pitch=0.9)
    assert a.chord == pytest.approx(b.chord) and a.max_thickness == pytest.approx(b.max_thickness)
    assert np.allclose(np.sort(a.x), np.sort(b.x))


def test_selig_round_trip(tmp_path):
    b = Blade.from_parameters(45.0, 15.0, 0.08, pitch=0.9, thickness_form="c4")
    p = tmp_path / "c4.dat"
    b.write_selig(p)
    c = Blade.read_airfoil(p, stagger=b.stagger, pitch=0.9)
    assert c.chord == pytest.approx(b.chord, rel=1e-3)
    assert c.max_thickness == pytest.approx(b.max_thickness, rel=1e-3)
    ref = Blade(b.x, b.y, b.pitch)          # angles estimated from the contour, as for c
    assert np.max(np.abs(np.array(c.estimated_metal_angles())
                         - np.array(ref.estimated_metal_angles()))) < 0.05


def test_config_inline_and_file_agree(tmp_path, naca4412_text):
    (tmp_path / "foil.dat").write_text(naca4412_text)
    common = {"type": "selig", "stagger": 30.0, "solidity": 1.2}
    b1 = build_blade(dict(common, file="foil.dat"), base_dir=tmp_path)
    b2 = build_blade(dict(common, coordinates=naca4412_text))
    assert np.allclose(b1.x, b2.x) and b1.name == "NACA 4412"
    toml = ("[geometry]\ntype = \"selig\"\nstagger = 30.0\npitch = 0.8\nname = \"my foil\"\n"
            f"coordinates = '''\n{naca4412_text}'''\n[flow]\ninlet_mach = 0.3\n"
            "inlet_angle = 40.0\nreynolds = 5e5\n")
    case = build_case(parse_config(toml, ".toml"))
    assert case.blade.name == "my foil" and case.blade.pitch == pytest.approx(0.8)


@pytest.mark.parametrize("geo, msg", [
    ({"type": "selig", "stagger": 30, "pitch": 1.0}, "exactly one of 'file'"),
    ({"type": "selig", "coordinates": "x", "file": "a.dat", "pitch": 1.0}, "exactly one of 'file'"),
    ({"type": "selig", "coordinates": "x"}, "'pitch' or"),
    ({"type": "selig", "file": "missing.dat", "pitch": 1.0}, "could not read"),
    ({"type": "selig", "coordinates": "only text", "pitch": 1.0}, "no coordinate pairs"),
    ({"type": "selig", "coordinates": "x", "pitch": 1.0, "camber": 2}, "unknown key"),
])
def test_config_errors(tmp_path, geo, msg):
    with pytest.raises(ConfigError, match=msg):
        build_blade(geo, base_dir=tmp_path)


def test_coarse_selig_file_solves_like_fine(naca4412_text):
    """A 69-point file and a 481-point file of the same section give the same answer."""
    fl = FlowConditions(inlet_mach=0.3, inlet_angle=40.0, reynolds=5e5)
    coarse = CascadeSolver(Blade.from_selig(naca4412_text, stagger=30, solidity=1.2), fl).solve()
    fine_text = Blade.naca4("4412", pitch=1.0).to_selig()
    fine = CascadeSolver(Blade.from_selig(fine_text, stagger=30, solidity=1.2), fl).solve()
    assert not coarse.warnings
    assert coarse.performance["omega"] == pytest.approx(fine.performance["omega"], rel=0.05)
    assert coarse.performance["beta2"] == pytest.approx(fine.performance["beta2"], abs=0.5)


def test_cli_exports_selig(tmp_path, capsys):
    assert main(["example", "airfoil", str(tmp_path)]) == 0
    out = tmp_path / "exported.dat"
    assert main(["blade", str(tmp_path / "airfoil.toml"), "-w", str(out)]) == 0
    name, x, _, _ = parse_airfoil_coordinates(out.read_text())
    assert name == "NACA 4412" and x.size == 69
    assert x.min() == pytest.approx(0.0, abs=2e-3) and x.min() >= -1e-9
