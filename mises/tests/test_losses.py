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


# ---------------------------------------------------------------------------
# lift and drag coefficients
# ---------------------------------------------------------------------------

def test_force_coefficients_reduce_to_dixon_relations_in_incompressible_flow():
    import math
    from pymises.losses import cascade_force_coefficients, cascade_mixed_out_loss, uniform_state
    m1, b1, b2, s, c = 0.02, 42.0, 18.0, 0.9, 1.0
    loss = cascade_mixed_out_loss(m1, b1, b2, s, 0.02, 0.012, 0.004)
    rho1, V1, p1, _ = uniform_state(m1, b1)
    u1, v1 = V1 * math.cos(math.radians(b1)), V1 * math.sin(math.radians(b1))
    fc = cascade_force_coefficients(rho1, u1, v1, p1, loss.exit, s, c)
    q = 0.5 * rho1 * V1 ** 2
    w = (loss.inlet_p0 - loss.exit.p0) / q            # loss on rho V1^2 / 2
    t1, t2 = math.tan(math.radians(b1)), math.tan(math.radians(loss.exit.angle))
    bm = math.atan(0.5 * (t1 + t2))
    assert fc["beta_m"] == pytest.approx(math.degrees(bm), abs=1e-9)
    assert fc["cd"] == pytest.approx(s / c * w * math.cos(bm), rel=2e-3)
    cl_dixon = 2 * s / c * math.cos(math.radians(b1)) ** 2 * (t1 - t2) / math.cos(bm) - s / c * w * math.sin(bm)
    assert fc["cl"] == pytest.approx(cl_dixon, rel=2e-3)
    # the loss-based drag used in compressible flow coincides with the momentum drag here
    fl = cascade_force_coefficients(rho1, u1, v1, p1, loss.exit, s, c, p01=loss.inlet_p0)
    assert fl["cd"] == pytest.approx(fc["cd"], rel=3e-3)
    assert fl["cd_momentum"] == fc["cd"]


def test_loss_based_drag_is_positive_where_momentum_drag_is_not():
    """Decelerating compressible cascade: density rise makes the momentum drag negative."""
    import math
    from pymises.losses import cascade_force_coefficients, cascade_mixed_out_loss, uniform_state
    m1, b1, b2, s = 0.7, 47.0, 22.0, 0.9
    loss = cascade_mixed_out_loss(m1, b1, b2, s, 0.0, 0.0, 0.0)     # lossless
    rho1, V1, p1, _ = uniform_state(m1, b1)
    u1, v1 = V1 * math.cos(math.radians(b1)), V1 * math.sin(math.radians(b1))
    fc = cascade_force_coefficients(rho1, u1, v1, p1, loss.exit, s, 1.0, p01=loss.inlet_p0)
    assert abs(fc["cd"]) < 1e-9
    assert fc["cd_momentum"] < -1e-3


def test_inviscid_cascade_lift_matches_kutta_joukowski(compressor_blade):
    import math
    from pymises import CascadeSolver, FlowConditions, ViscousOptions
    r = CascadeSolver(compressor_blade, FlowConditions(0.02, 43.0, 5e5), ViscousOptions(enabled=False)).solve()
    p = r.performance
    b1, b2 = math.radians(p["beta1"]), math.radians(p["beta2"])
    s = compressor_blade.pitch / compressor_blade.chord
    bm = math.atan(0.5 * (math.tan(b1) + math.tan(b2)))
    # L = rho Vm Gamma with Gamma = s (v1 - v2) and u1 = u2 = cos(beta1) V1
    cl_kj = 2 * s * math.cos(b1) ** 2 * (math.tan(b1) - math.tan(b2)) / math.cos(bm)
    assert p["cl"] == pytest.approx(cl_kj, rel=5e-3)
    assert abs(p["cd"]) < 2e-3


def test_viscous_compressor_has_positive_lift_and_drag(compressor_blade):
    from pymises import CascadeSolver, FlowConditions
    p = CascadeSolver(compressor_blade, FlowConditions(0.5, 43.0, 5e5)).solve().performance
    assert p["cl"] > 0.5 and p["cd"] > 0.0
    assert p["lift_drag"] == pytest.approx(p["cl"] / p["cd"])
