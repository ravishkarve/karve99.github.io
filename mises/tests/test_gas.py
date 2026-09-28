import math

import numpy as np
import pytest

from pymises import gas


def test_isentropic_ratios_consistent():
    m = np.linspace(0.0, 2.5, 26)
    t, p, r = gas.t_ratio(m), gas.p_ratio(m), gas.rho_ratio(m)
    np.testing.assert_allclose(p, r * t, rtol=1e-12)          # ideal gas p = rho R T
    np.testing.assert_allclose(gas.mach_from_p_ratio(p), m, atol=1e-10)


def test_speed_mach_inverse():
    m = np.array([0.0, 0.3, 0.8, 1.0, 1.7])
    np.testing.assert_allclose(gas.mach_from_speed(gas.speed_over_a0(m)), m, atol=1e-12)


def test_sonic_values():
    assert gas.t_ratio(1.0) == pytest.approx(1 / 1.2)
    assert gas.p_ratio(1.0) == pytest.approx(0.528282, rel=1e-5)
    assert gas.area_ratio(1.0) == pytest.approx(1.0)


def test_area_ratio_known_value():
    assert gas.area_ratio(2.0) == pytest.approx(1.6875, rel=1e-6)
    assert gas.mach_from_area_ratio(1.6875, supersonic=True) == pytest.approx(2.0, rel=1e-8)
    assert gas.mach_from_area_ratio(1.6875, supersonic=False) == pytest.approx(0.3722, rel=1e-3)


def test_normal_shock_textbook_values():
    m2, p21, p0r = gas.normal_shock(2.0)
    assert m2 == pytest.approx(0.57735, rel=1e-4)
    assert p21 == pytest.approx(4.5, rel=1e-10)
    assert p0r == pytest.approx(0.72087, rel=1e-4)


def test_mass_flow_function_maximum_at_sonic():
    m = np.linspace(0.05, 2.0, 400)
    f = gas.mass_flow_function(m)
    assert abs(m[np.argmax(f)] - 1.0) < 0.01
    v = float(gas.mass_flow_function(0.4))
    assert gas.mach_from_mass_flow_function(v) == pytest.approx(0.4, rel=1e-9)
    assert math.isnan(gas.mach_from_mass_flow_function(2.0 * float(gas.mass_flow_function(1.0))))


def test_karman_tsien_reduces_to_incompressible():
    assert gas.karman_tsien_cp(-0.5, 0.0) == pytest.approx(-0.5)
    assert gas.karman_tsien_cp(-0.5, 0.6) < -0.5 / math.sqrt(1 - 0.36) * 0.99


def test_sutherland_reference():
    assert gas.sutherland_ratio(1.0) == pytest.approx(1.0)
    assert gas.sutherland_ratio(1.2) > 1.0
