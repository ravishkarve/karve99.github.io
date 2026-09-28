import json
import math

import numpy as np
import pytest

from pymises import Blade, CascadeSolver, EulerOptions, FlowConditions, ViscousOptions


def test_compressor_result_ranges(compressor_result):
    p = compressor_result.performance
    assert compressor_result.convergence["bl_converged"]
    assert 0.005 < p["omega"] < 0.03
    assert 3.0 < p["deviation"] < 12.0
    assert p["M2"] < p["M1"]                                   # diffusing cascade
    assert p["p2_p1"] > 1.0
    assert 0.0 < p["xtr_upper"] < 1.0 and 0.0 < p["xtr_lower"] < 1.0
    assert compressor_result.warnings == []


def test_result_serialisation(compressor_result):
    d = json.loads(compressor_result.to_json())
    assert d["method"] == "panel"
    assert len(d["upper"]["mis"]) == len(d["upper"]["xc"])
    assert d["bl_upper"]["theta"][-1] > 0
    assert "loss omega" in compressor_result.summary()


def test_inviscid_has_zero_loss():
    sharp = Blade.from_parameters(45, 15, 0.08, pitch=0.9, thickness_form="c4", te_thickness=0.0)
    r = CascadeSolver(sharp, FlowConditions(0.5, 43.0, 5e5), ViscousOptions(enabled=False)).solve()
    assert abs(r.loss) < 1e-12
    assert r.bl_upper is None


def test_blunt_trailing_edge_base_loss(compressor_blade):
    """Without boundary layers, a blunt TE still has the (small) base-blockage mixing loss."""
    r = CascadeSolver(compressor_blade, FlowConditions(0.5, 43.0, 5e5),
                      ViscousOptions(enabled=False)).solve()
    assert 0.0 < r.loss < 1e-3


def test_reynolds_trend(compressor_blade):
    """Loss falls with Reynolds number (fixed incidence)."""
    w = [CascadeSolver(compressor_blade, FlowConditions(0.4, 43.0, re)).solve().loss
         for re in (2.5e5, 1e6)]
    assert w[0] > w[1]


def test_forced_transition_moves_transition(compressor_blade):
    r = CascadeSolver(compressor_blade, FlowConditions(0.4, 43.0, 5e5),
                      ViscousOptions(xtr_upper=0.2, xtr_lower=0.2)).solve()
    assert r.performance["xtr_upper"] <= 0.21 and r.performance["xtr_lower"] <= 0.21
    assert r.bl_upper.forced


def test_compressibility_raises_suction_peak(compressor_blade):
    lo = CascadeSolver(compressor_blade, FlowConditions(0.05, 43.0, 5e5), ViscousOptions(enabled=False)).solve()
    hi = CascadeSolver(compressor_blade, FlowConditions(0.6, 43.0, 5e5), ViscousOptions(enabled=False)).solve()
    ratio_lo = lo.upper.q.max()
    ratio_hi = hi.upper.q.max()
    assert ratio_hi > ratio_lo                                  # Karman-Tsien amplification


def test_flow_validation():
    with pytest.raises(ValueError):
        FlowConditions(inlet_mach=1.2).validate()
    with pytest.raises(ValueError):
        CascadeSolver(Blade.naca4("0012"), FlowConditions(), method="streamline")


def test_turbine_cascade():
    b = Blade.from_parameters(30.0, -60.0, 0.18, pitch=0.85, camber="bezier",
                              le_camber_fraction=0.72, te_thickness=0.01)
    r = CascadeSolver(b, FlowConditions(0.25, 30.0, 5e5)).solve()
    p = r.performance
    assert p["M2"] > p["M1"]                                    # accelerating
    assert abs(p["deviation"]) < 4.0
    assert 0.0 < p["omega_exit"] < 0.08


@pytest.mark.slow
def test_euler_viscous_close_to_panel(compressor_blade):
    fl = FlowConditions(0.5, 43.0, 5e5)
    re = CascadeSolver(compressor_blade, fl, method="euler").solve()
    rp = CascadeSolver(compressor_blade, fl).solve()
    assert re.performance["omega"] == pytest.approx(rp.performance["omega"], abs=0.006)
    assert re.performance["beta2"] == pytest.approx(rp.performance["beta2"], abs=2.0)
