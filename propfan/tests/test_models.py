"""The added physics: shock entropy, thin-aerofoil stall, 3-D relief, choke spillage, accounting."""
import math

import numpy as np
import pytest

from hsprop import OperatingPoint, PropellerSolver, SectionOptions, cases
from hsprop.gas import GAMMA, normal_shock_p0_ratio
from hsprop.section import NormalPlane, SectionModel


def _plain(alpha_deg, tau, cld=0.0):
    a = np.radians(np.atleast_1d(alpha_deg))
    one = np.ones_like(a)
    return NormalPlane.plain(a, 0.0 * one, 0.0 * one, tau * one, cld * one)


# ------------------------------------------------------------------ shock entropy
@pytest.mark.parametrize("M", [1.01, 1.02])
def test_shock_entropy_rise_follows_weak_shock_law(M):
    """ln(p01/p02) -> 2 gamma/(gamma+1)^2 (M^2-1)^3/3 for weak shocks."""
    weak = 2.0 * GAMMA / (GAMMA + 1.0) ** 2 * (M * M - 1.0) ** 3 / 3.0
    assert -math.log(normal_shock_p0_ratio(M)) == pytest.approx(weak, rel=0.08)


def test_wave_drag_bounded_by_low_supersonic_section():
    """Deep in the transonic band the subsonic pocket drag may not exceed the drag of the same
    section at the low-supersonic end of the band."""
    machs = np.linspace(0.80, 0.99, 20)
    sm = SectionModel(["naca16"] * machs.size, ["a1"] * machs.size, SectionOptions())
    r = sm.evaluate(_plain(np.full(machs.size, 2.0), 0.03, 0.4), machs, np.full(machs.size, 3e6))
    sup = SectionModel(["naca16"], ["a1"], SectionOptions())
    r_sup = sup.evaluate(_plain([2.0], 0.03, 0.4), np.array([1.15]), np.array([3e6]))
    assert np.all(np.diff(r.cd_wave) > -1e-6)                  # drag rises monotonically ...
    assert r.cd_wave.max() < 1.2 * r_sup.cd_wave[0]            # ... towards the supersonic level


# ------------------------------------------------------------------ thin-aerofoil stall
def test_thin_section_keeps_lift_after_bubble_burst_thick_one_stalls():
    """McCullough & Gault: a thin section's burst bubble reattaches as a long bubble (lift keeps
    rising, the suction is lost) until thin-aerofoil stall near 10 deg; a thick section stalls
    at the leading edge when its bubble bursts."""
    al = np.array([2.0, 4.0, 6.0, 8.0, 14.0, 16.0])
    n = al.size
    thin = SectionModel(["naca16"] * n, ["a1"] * n, SectionOptions())
    rt = thin.evaluate(_plain(al, 0.04), np.full(n, 0.25), np.full(n, 3e6))
    assert np.all(np.diff(rt.cl[:4]) > 0.0)                     # long bubble: lift rising to 8 deg
    assert rt.f_attached[3] > 0.8
    assert rt.cd[3] > 4.0 * rt.cd[0]                            # ... paid for with the lost suction
    assert rt.f_attached[4] < 0.3                               # thin-aerofoil stall by 14 deg
    thick = SectionModel(["naca16"] * n, ["a1"] * n, SectionOptions())
    rk = thick.evaluate(_plain(al, 0.12), np.full(n, 0.25), np.full(n, 3e6))
    assert rk.f_attached[3] > 0.9                               # attached at 8 deg
    assert rk.f_attached[5] < 0.3                               # leading-edge stall by 16 deg


def test_section_outputs_continuous_through_bubble_onset():
    """Incidence sweeps through the onset of leading-edge bubbles (free transition): the
    largest change of profile drag between neighbouring points shrinks in proportion to the
    step, i.e. no jumps in the transition location."""
    def max_step(h):
        al = np.arange(-3.0, 1.0 + 1e-9, h)
        sm = SectionModel(["naca16"] * al.size, ["a1"] * al.size, SectionOptions(xtr_upper=1.0, xtr_lower=1.0))
        r = sm.evaluate(_plain(al, 0.04, 0.3), np.full(al.size, 0.6), np.full(al.size, 2e6))
        return np.abs(np.diff(r.cd_profile)).max()
    assert max_step(0.0125) < 0.4 * max_step(0.05)


# ------------------------------------------------------------------ 3-D relief
def test_relief_wavenumber_limits():
    prop = cases.reference("sr2_class")
    sv = PropellerSolver(prop)
    geo = sv._geometry(0.0)
    npl = sv._normal_plane(geo, np.full(sv.N, 0.6))
    kappa = sv._relief_wavenumber(geo, npl)
    assert kappa[-1] > 0.9                                       # at the tip: slender-wing limit
    assert np.all(np.diff(kappa) > 0.0)                          # grows towards the tip
    # far from the tip of a narrow blade the strip is 2-D
    c_n = 0.01
    assert c_n / (2.0 * 10.0 + c_n) < 1e-3


# ------------------------------------------------------------------ propeller-level
@pytest.fixture(scope="module")
def sr3_design():
    prop = cases.reference("sr3_class")
    sv = PropellerSolver(prop)
    op = OperatingPoint(mach=0.8, altitude=10668.0, J=3.06)
    return sv.solve_for(op, CP=1.7, dbeta0=0.0)


def test_net_thrust_loss_identity(sr3_design):
    """P - T_net V equals the sum of the itemised losses (exact bookkeeping)."""
    r = sr3_design
    L = {k: v for k, v in r.losses.items() if k != "total"}
    assert sum(L.values()) == pytest.approx(1.0 - r.eta, abs=1e-9)
    assert L["nacelle_reaction"] == pytest.approx(-L["nacelle_interaction"], abs=1e-12)


def test_design_point_converges_and_is_sensible(sr3_design):
    r = sr3_design
    assert r.converged
    assert r.CP == pytest.approx(1.7, rel=1e-4)
    assert 0.74 < r.eta < 0.83


def test_choke_spillage_complementarity():
    """Low power at M 0.8: choked root strips spill (s > 0, chi = 1), the others do not."""
    prop = cases.reference("sr3_class")
    sv = PropellerSolver(prop)
    r = sv.solve(OperatingPoint(mach=0.8, altitude=10668.0, J=3.06, dbeta=-4.0))
    assert r.converged
    spill = -r.radial["u_spill"] / r.op["V"]
    chi = r.radial["choke_ratio"]
    assert spill.max() > 0.01
    assert np.all(spill > -1e-3)
    on = spill > 0.01
    assert np.all(np.abs(chi[on] - 1.0) < 0.01)
    assert np.all(spill[chi < 0.95] < 2e-3)


@pytest.mark.slow
def test_validation_against_nasa_sr3():
    prop = cases.reference("sr3_class")
    from hsprop.gas import Atmosphere
    sv = PropellerSolver(prop)
    op = OperatingPoint(mach=0.8, atmosphere=Atmosphere.from_total(288.15, 101325.0, 0.8), J=3.06)
    assert sv.solve_for(op, CP=1.7).eta == pytest.approx(0.787, abs=0.03)
    to = sv.solve_for(OperatingPoint(mach=0.2, altitude=0.0, J=0.875), CP=1.0, dbeta0=-15.0)
    assert to.eta == pytest.approx(0.549, abs=0.03)
