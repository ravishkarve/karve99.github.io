import math

import pytest

from pymises import gas
from pymises.losses import (cascade_mixed_out_loss, edge_state_for_mass, fluxes_of_uniform,
                            lieblein_loss, mixed_out, uniform_state)
from pymises.verification import incompressible_mixed_out_loss


def test_mixed_out_of_uniform_flow_is_identity():
    g = 1.4
    for m, b in ((0.3, 10.0), (0.7, 45.0), (0.9, -30.0)):
        mdot, fx, fy = fluxes_of_uniform(m, b, 1.0, g)
        st = mixed_out(mdot, fx, fy, 1.0 / (g - 1.0), 1.0, g)
        assert st.mach == pytest.approx(m, rel=1e-10)
        assert st.angle == pytest.approx(b, abs=1e-9)
        assert st.p0 * g == pytest.approx(1.0, rel=1e-12)


def test_zero_boundary_layer_gives_zero_loss():
    lb = cascade_mixed_out_loss(0.6, 40.0, 20.0, 0.9, 0.0, 0.0, 0.0)
    assert abs(lb.omega) < 1e-12


def test_loss_increases_with_momentum_thickness():
    w = [cascade_mixed_out_loss(0.5, 45.0, 20.0, 0.9, 1.7 * t, t).omega for t in (0.001, 0.002, 0.004)]
    assert 0 < w[0] < w[1] < w[2]
    assert w[1] / w[0] == pytest.approx(2.0, rel=0.05)        # ~linear for thin wakes


def test_incompressible_limit_matches_closed_form():
    lb = cascade_mixed_out_loss(0.005, 50.0, 25.0, 1 / 1.2, 2.0 * 0.004, 0.004)
    ref = incompressible_mixed_out_loss(0.004, 0.008, 1 / 1.2, 50.0, 25.0)
    assert lb.omega == pytest.approx(ref, rel=1e-3)
    # first-order term is Lieblein's far-wake expression
    assert lieblein_loss(0.004, 1.0, 1.2, 50.0, 25.0) == pytest.approx(ref, rel=0.03)


def test_base_blockage_adds_loss():
    a = cascade_mixed_out_loss(0.5, 45.0, 20.0, 0.9, 0.004, 0.002, 0.0).omega
    b = cascade_mixed_out_loss(0.5, 45.0, 20.0, 0.9, 0.004, 0.002, 0.01).omega
    assert b > a


def test_edge_state_mass_balance():
    rho1, V1, p1, _ = uniform_state(0.5, 40.0)
    mdot = rho1 * V1 * math.cos(math.radians(40.0)) * 0.9
    me, choked = edge_state_for_mass(mdot, 20.0, 0.01, 0.9)
    rho, V, p, _ = uniform_state(me, 20.0)
    assert not choked
    assert rho * V * (0.9 * math.cos(math.radians(20.0)) - 0.01) == pytest.approx(mdot, rel=1e-9)
