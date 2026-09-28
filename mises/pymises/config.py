"""Configuration-file driven runs.

A case is described by a TOML, JSON or YAML file (TOML shown)::

    [case]
    name = "Compressor cascade"
    method = "panel"            # or "euler"
    output_dir = "results/compressor"

    [geometry]
    type = "parametric"         # "parametric" | "mises" | "naca4" | "coordinates"
    inlet_metal_angle = 45.0
    exit_metal_angle = 15.0
    max_thickness = 0.08
    thickness_form = "c4"       # "naca65" | "naca4" | "c4"
    pitch = 0.9                 # s/c   (or solidity = c/s)
    te_thickness = 0.004

    [flow]
    inlet_mach = 0.5
    inlet_angle = 43.0
    reynolds = 5.0e5

    [viscous]
    ncrit = 9.0
    xtr_upper = 1.0
    xtr_lower = 1.0

    [sweep]                     # optional
    parameter = "flow.inlet_angle"
    values = [37, 39, 41, 43, 45, 47]

Geometry types
--------------
``mises``        ``file = "blade.name"`` in MISES blade.xxx format (path relative
                 to the configuration file).
``naca4``        ``code = "0012"``, ``pitch``, ``alpha``.
``coordinates``  ``x = [...]``, ``y = [...]``, ``pitch`` (contour from the TE).
"""
from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass, field, fields
from pathlib import Path

import numpy as np

from .euler import EulerOptions
from .geometry import Blade
from .solver import CascadeSolver, FlowConditions, PanelOptions, ViscousOptions

try:                                    # Python >= 3.11
    import tomllib as _toml
except ModuleNotFoundError:             # pragma: no cover
    _toml = None

SECTIONS = ("case", "geometry", "flow", "viscous", "panel", "euler", "sweep", "output")


class ConfigError(ValueError):
    """Raised for invalid configuration files."""


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def load_config(path) -> dict:
    """Read a configuration file (.toml, .json, .yaml/.yml) into a dict."""
    path = Path(path)
    text = path.read_text()
    return parse_config(text, path.suffix.lower(), base_dir=path.parent)


def parse_config(text: str, fmt: str = ".toml", base_dir=None) -> dict:
    """Parse configuration text in the given format ('.toml', '.json', '.yaml')."""
    fmt = fmt if fmt.startswith(".") else "." + fmt
    if fmt == ".toml":
        if _toml is None:
            raise ConfigError("TOML needs Python >= 3.11 (tomllib); use JSON or YAML instead")
        try:
            cfg = _toml.loads(text)
        except Exception as exc:  # tomllib.TOMLDecodeError
            raise ConfigError(f"invalid TOML: {exc}") from exc
    elif fmt == ".json":
        try:
            cfg = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"invalid JSON: {exc}") from exc
    elif fmt in (".yaml", ".yml"):
        try:
            import yaml
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise ConfigError("YAML configuration files need PyYAML") from exc
        cfg = yaml.safe_load(text) or {}
    else:
        raise ConfigError(f"unsupported configuration format '{fmt}'")
    if not isinstance(cfg, dict):
        raise ConfigError("configuration must be a table/mapping at the top level")
    unknown = set(cfg) - set(SECTIONS)
    if unknown:
        raise ConfigError(f"unknown section(s) {sorted(unknown)}; allowed: {list(SECTIONS)}")
    if base_dir is not None:
        cfg.setdefault("_base_dir", str(base_dir))
    return cfg


# ---------------------------------------------------------------------------
# building objects
# ---------------------------------------------------------------------------

def _dataclass_from(cls, data: dict, section: str):
    allowed = {f.name for f in fields(cls)}
    unknown = set(data) - allowed
    if unknown:
        raise ConfigError(f"[{section}] unknown key(s) {sorted(unknown)}; allowed: {sorted(allowed)}")
    try:
        return cls(**data)
    except TypeError as exc:
        raise ConfigError(f"[{section}] {exc}") from exc


GEOMETRY_KEYS = {
    "parametric": {"type", "inlet_metal_angle", "exit_metal_angle", "max_thickness",
                   "thickness_form", "pitch", "solidity", "te_thickness", "chord", "name",
                   "n_points", "camber", "le_camber_fraction"},
    "mises": {"type", "file", "pitch", "name"},
    "naca4": {"type", "code", "pitch", "alpha", "name", "te_closed"},
    "coordinates": {"type", "x", "y", "pitch", "name"},
}


def build_blade(geo: dict, base_dir=None) -> Blade:
    """Create a :class:`Blade` from a [geometry] table."""
    geo = dict(geo)
    kind = geo.get("type", "parametric")
    if kind not in GEOMETRY_KEYS:
        raise ConfigError(f"[geometry] type must be one of {sorted(GEOMETRY_KEYS)}")
    unknown = set(geo) - GEOMETRY_KEYS[kind]
    if unknown:
        raise ConfigError(f"[geometry] unknown key(s) {sorted(unknown)} for type '{kind}'; "
                          f"allowed: {sorted(GEOMETRY_KEYS[kind])}")
    geo.pop("type", None)
    name = geo.pop("name", None)
    try:
        if kind == "parametric":
            blade = Blade.from_parameters(**geo, name=name)
        elif kind == "mises":
            fp = Path(geo["file"])
            if not fp.is_absolute() and base_dir is not None:
                fp = Path(base_dir) / fp
            blade = Blade.read_mises(fp)
            if "pitch" in geo:
                blade.pitch = float(geo["pitch"])
            if name:
                blade.name = name
        elif kind == "naca4":
            blade = Blade.naca4(geo.get("code", "0012"), pitch=geo.get("pitch", 1000.0),
                                alpha=geo.get("alpha", 0.0), te_closed=geo.get("te_closed", False))
            if name:
                blade.name = name
        else:
            if "pitch" not in geo:
                raise ConfigError("[geometry] coordinates need a pitch")
            blade = Blade(np.asarray(geo["x"], float), np.asarray(geo["y"], float),
                          float(geo["pitch"]), name or "blade")
    except KeyError as exc:
        raise ConfigError(f"[geometry] missing key {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"[geometry] {exc}") from exc
    return blade


@dataclass
class Case:
    name: str
    method: str
    blade: Blade
    flow: FlowConditions
    viscous: ViscousOptions
    panel: PanelOptions
    euler: EulerOptions
    output_dir: str | None = None
    sweep: dict | None = None
    output: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    def solver(self, **kw) -> CascadeSolver:
        return CascadeSolver(self.blade, self.flow, self.viscous, self.method, self.panel,
                             self.euler, **kw)


def build_case(cfg: dict) -> Case:
    """Turn a parsed configuration dict into a :class:`Case`."""
    base_dir = cfg.get("_base_dir")
    case = dict(cfg.get("case", {}))
    allowed_case = {"name", "method", "output_dir"}
    unknown = set(case) - allowed_case
    if unknown:
        raise ConfigError(f"[case] unknown key(s) {sorted(unknown)}; allowed: {sorted(allowed_case)}")
    method = str(case.get("method", "panel")).lower()
    if method not in ("panel", "euler"):
        raise ConfigError("[case] method must be 'panel' or 'euler'")
    if "geometry" not in cfg:
        raise ConfigError("missing [geometry] section")
    blade = build_blade(cfg["geometry"], base_dir)
    flow = _dataclass_from(FlowConditions, cfg.get("flow", {}), "flow")
    try:
        flow.validate()
    except ValueError as exc:
        raise ConfigError(f"[flow] {exc}") from exc
    viscous = _dataclass_from(ViscousOptions, cfg.get("viscous", {}), "viscous")
    panel = _dataclass_from(PanelOptions, cfg.get("panel", {}), "panel")
    euler = _dataclass_from(EulerOptions, cfg.get("euler", {}), "euler")
    sweep = cfg.get("sweep")
    if sweep is not None:
        sweep = _normalise_sweep(sweep)
    out_dir = case.get("output_dir")
    if out_dir and base_dir and not Path(out_dir).is_absolute():
        out_dir = str(Path(base_dir) / out_dir)
    output = dict(cfg.get("output", {}))
    unknown = set(output) - {"json", "csv", "plots"}
    if unknown:
        raise ConfigError(f"[output] unknown key(s) {sorted(unknown)}; allowed: json, csv, plots")
    return Case(case.get("name", blade.name), method, blade, flow, viscous, panel, euler,
                out_dir, sweep, output, cfg)


def _normalise_sweep(sweep: dict) -> dict:
    sweep = dict(sweep)
    unknown = set(sweep) - {"parameter", "values", "start", "stop", "step"}
    if unknown:
        raise ConfigError(f"[sweep] unknown key(s) {sorted(unknown)}")
    if "parameter" not in sweep:
        raise ConfigError("[sweep] needs 'parameter', e.g. 'flow.inlet_angle'")
    sec, _, key = sweep["parameter"].partition(".")
    if sec not in ("flow", "viscous", "geometry") or not key:
        raise ConfigError("[sweep] parameter must look like 'flow.<key>', 'viscous.<key>' "
                          "or 'geometry.<key>'")
    if "values" in sweep:
        vals = [float(v) for v in sweep["values"]]
    elif {"start", "stop", "step"} <= set(sweep):
        n = int(math.floor((sweep["stop"] - sweep["start"]) / sweep["step"] + 1e-9)) + 1
        vals = [sweep["start"] + i * sweep["step"] for i in range(n)]
    else:
        raise ConfigError("[sweep] give 'values' or 'start', 'stop' and 'step'")
    if not vals:
        raise ConfigError("[sweep] has no values")
    return {"parameter": sweep["parameter"], "values": vals}


# ---------------------------------------------------------------------------
# running
# ---------------------------------------------------------------------------

def run_case(case: Case, progress=None, verbose=False):
    """Run a case; returns a list of results (one per sweep point)."""
    if case.sweep is None:
        return [case.solver(progress=progress, verbose=verbose).solve()]
    results = []
    sec, _, key = case.sweep["parameter"].partition(".")
    for i, val in enumerate(case.sweep["values"]):
        cfg = copy.deepcopy(case.raw)
        cfg.pop("sweep", None)
        cfg.setdefault(sec, {})[key] = val
        sub = build_case(cfg)
        if progress:
            progress(f"sweep point {i + 1}/{len(case.sweep['values'])}: {key} = {val:g}")
        res = sub.solver(progress=progress, verbose=verbose).solve()
        res.performance["sweep_parameter"] = case.sweep["parameter"]
        res.performance["sweep_value"] = val
        results.append(res)
    return results


def run_config(path, output_dir=None, plots=None, progress=None, verbose=False):
    """Load, run and save a configuration file.  Returns (case, results, written_files)."""
    from .io import save_results
    cfg = load_config(path)
    case = build_case(cfg)
    results = run_case(case, progress=progress, verbose=verbose)
    out = output_dir or case.output_dir or str(Path(path).with_suffix("")) + "_results"
    want_plots = case.output.get("plots", True) if plots is None else plots
    files = save_results(case, results, out, plots=want_plots,
                         json_out=case.output.get("json", True),
                         csv_out=case.output.get("csv", True))
    return case, results, files


def run_config_text(text: str, fmt: str = ".toml", progress=None):
    """Run a configuration given as text (used by the web dashboard).  Returns results."""
    case = build_case(parse_config(text, fmt))
    return case, run_case(case, progress=progress)
