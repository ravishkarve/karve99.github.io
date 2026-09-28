import json

import pytest

from pymises.config import ConfigError, build_case, load_config, parse_config, run_config
from pymises.examples import EXAMPLES, write_example


def test_examples_parse(tmp_path):
    for name in EXAMPLES:
        files = write_example(name, tmp_path / name)
        cfg = [f for f in files if f.suffix == ".toml"][0]
        case = build_case(load_config(cfg))
        assert case.blade.pitch > 0
        assert case.method in ("panel", "euler")


def test_json_and_yaml_equivalent():
    toml_text = """
[geometry]
type = "parametric"
inlet_metal_angle = 45.0
exit_metal_angle = 15.0
max_thickness = 0.08
pitch = 0.9
[flow]
inlet_mach = 0.4
inlet_angle = 42.0
"""
    c1 = build_case(parse_config(toml_text, ".toml"))
    js = json.dumps({"geometry": {"type": "parametric", "inlet_metal_angle": 45.0,
                                  "exit_metal_angle": 15.0, "max_thickness": 0.08, "pitch": 0.9},
                     "flow": {"inlet_mach": 0.4, "inlet_angle": 42.0}})
    c2 = build_case(parse_config(js, ".json"))
    yml = """
geometry: {type: parametric, inlet_metal_angle: 45.0, exit_metal_angle: 15.0,
           max_thickness: 0.08, pitch: 0.9}
flow: {inlet_mach: 0.4, inlet_angle: 42.0}
"""
    pytest.importorskip("yaml")
    c3 = build_case(parse_config(yml, ".yaml"))
    for c in (c2, c3):
        assert c.flow == c1.flow
        assert (c.blade.x == c1.blade.x).all()


@pytest.mark.parametrize("text, msg", [
    ("[geometry]\ntype='parametric'\npitch=0.9\nbogus=1\n", "unknown key"),
    ("[flow]\ninlet_mach=0.5\n", "missing [geometry]"),
    ("[geometry]\ntype='naca4'\n[flow]\ninlet_mach=1.5\n", "inlet_mach"),
    ("[geometry]\ntype='naca4'\n[wrong]\na=1\n", "unknown section"),
    ("[geometry]\ntype='naca4'\n[sweep]\nparameter='flow.inlet_angle'\n", "values"),
    ("[geometry]\ntype='naca4'\n[case]\nmethod='rans'\n", "method"),
])
def test_config_errors(text, msg):
    with pytest.raises(ConfigError, match=msg.replace("[", r"\[").replace("]", r"\]")):
        build_case(parse_config(text, ".toml"))


def test_sweep_expansion():
    case = build_case(parse_config(
        "[geometry]\ntype='naca4'\n[sweep]\nparameter='flow.inlet_angle'\nstart=0\nstop=4\nstep=2\n",
        ".toml"))
    assert case.sweep["values"] == [0.0, 2.0, 4.0]


def test_run_config_writes_outputs(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text("""
[case]
name = "test"
[geometry]
type = "parametric"
inlet_metal_angle = 45.0
exit_metal_angle = 15.0
max_thickness = 0.08
thickness_form = "c4"
pitch = 0.9
[flow]
inlet_mach = 0.4
inlet_angle = 43.0
reynolds = 5e5
[panel]
n_panels = 140
[sweep]
parameter = "flow.inlet_angle"
values = [41.0, 45.0]
""")
    case, results, files = run_config(cfg, output_dir=tmp_path / "out", plots=True)
    names = {f.name for f in files}
    assert "sweep.csv" in names and "sweep.json" in names and "point_000.json" in names
    assert len(results) == 2
    assert results[0].performance["sweep_value"] == 41.0


def test_mises_geometry_path_is_relative_to_config(tmp_path):
    write_example("mises", tmp_path)
    case = build_case(load_config(tmp_path / "mises_file.toml"))
    assert case.blade.pitch == pytest.approx(0.9)
