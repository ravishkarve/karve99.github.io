"""Boundary layer, nacelle flow, section model and vortex system against exact results."""
import math

import numpy as np
import pytest

from hsprop.boundary_layer import march
from hsprop.geometry import Blade, Nacelle, Propeller
from hsprop.nacelle import NacelleFlow
from hsprop.section import NormalPlane, SectionModel, SectionOptions, kuchemann_factor


# ------------------------------------------------------------------ boundary layer
X_BL = np.concatenate([[0.0], 0.5 * (1 - np.cos(np.linspace(0, np.pi, 83)[1:-1]))])


def test_blasius_flat_plate():
    r = march(X_BL, np.ones((1, X_BL.size)), [1e6], [0.0])
    assert r.cd[0] == pytest.approx(1.328 / math.sqrt(1e6), rel=0.02)
    assert r.x_tr[0] == 1.0


@pytest.mark.parametrize("Re", [1e6, 3e6, 1e7])
def test_turbulent_flat_plate_friction(Re):
    r = march(X_BL, np.ones((1, X_BL.size)), [Re], [0.0], xtr_forced=[0.001])
    schlichting = 0.455 / math.log10(Re) ** 2.58
    assert r.cd[0] == pytest.approx(schlichting, rel=0.08)


def test_transition_moves_smoothly_with_forcing():
    xs = np.linspace(0.2, 0.3, 11)
    cds = [march(X_BL, np.ones((1, X_BL.size)), [3e6], [0.0], xtr_forced=[x]).cd[0] for x in xs]
    d = np.diff(cds)
    # later transition, less drag; continuous (piecewise smooth between grid nodes)
    assert np.all(d < 0) and np.max(np.abs(d)) < 3.0 * np.mean(np.abs(d))


# ------------------------------------------------------------------ nacelle
def _spheroid(a, b, n=401):
    t = np.linspace(0, np.pi, n)
    return Nacelle(x_D=-a * np.cos(t), r_D=b * np.sin(t))


def _exact_equator(a, b):
    if a == b:
        return 1.5
    e = math.sqrt(1 - (b / a) ** 2)
    a0 = 2 * (1 - e * e) / e ** 3 * (math.atanh(e) - e)
    return 2 / (2 - a0)


@pytest.mark.parametrize("a", [1.0, 2.0, 4.0])
def test_spheroid_surface_speed(a):
    fl = NacelleFlow(_spheroid(a, 1.0), 1.0, 0.0)
    u = fl.axial(np.array([0.0]), np.array([1.0]))[0]
    assert 1 + u == pytest.approx(_exact_equator(a, 1.0), rel=0.006)


def test_goethert_rule_in_kernel():
    M = 0.7
    beta = math.sqrt(1 - M * M)
    fl = NacelleFlow(_spheroid(4.0, 1.0), 1.0, M)
    u = fl.axial(np.array([0.0]), np.array([1.0]))[0]
    assert u == pytest.approx((_exact_equator(4.0, beta) - 1) / beta ** 2, rel=0.05)


# ------------------------------------------------------------------ section model
def _plain(alpha_deg, sigma=0.0, xi=0.0, tau=0.06, cld=0.2, n=None):
    a = np.radians(np.atleast_1d(alpha_deg))
    one = np.ones_like(a)
    return NormalPlane.plain(a, sigma * one, xi * one, tau * one, cld * one)


def test_low_speed_section_lift_and_drag_are_realistic():
    al = np.arange(-2.0, 4.01, 1.0)
    sm = SectionModel(["naca16"] * al.size, ["a1"] * al.size, SectionOptions())
    r = sm.evaluate(_plain(al), np.full(al.size, 0.3), np.full(al.size, 3e6))
    slope = np.polyfit(np.radians(al), r.cl, 1)[0]
    assert 5.6 < slope < 6.9                           # 2 pi / beta with viscous loss
    a0 = -np.polyfit(np.radians(al), r.cl, 1)[1] / slope
    assert math.degrees(a0) == pytest.approx(-1.85, abs=0.25)   # a = 1.0 mean line, cl_d 0.2
    assert np.all((r.cd > 0.003) & (r.cd < 0.012))


def test_drag_divergence_near_korn():
    """6 % section near its design lift: drag divergence Mach (dCD/dM = 0.1) within 0.04 of
    Korn's equation with kappa_A = 0.87-0.90."""
    machs = np.arange(0.70, 0.90, 0.005)
    sm = SectionModel(["naca16"] * machs.size, ["a1"] * machs.size, SectionOptions(xtr_upper=0.05, xtr_lower=0.05))
    r = sm.evaluate(_plain(np.zeros(machs.size), tau=0.06, cld=0.2), machs, np.full(machs.size, 3e6))
    dcd = np.gradient(r.cd, machs)
    mdd = machs[np.argmax(dcd > 0.1)]
    korn = 0.87 - 0.06 - np.mean(r.cl[:5]) / 10.0
    assert korn - 0.01 < mdd < korn + 0.07


def test_kuchemann_factor_limits():
    assert kuchemann_factor(0.0, 0.7) == pytest.approx(0.0)
    assert kuchemann_factor(10.0, 0.7) > 0.99


# ------------------------------------------------------------------ vortex system
def test_many_bladed_rotor_tends_to_actuator_disk():
    from hsprop import PropellerSolver, SolverSettings, WakeSettings
    B = 48
    bl = Blade(r_R=[0.05, 1.0], chord_D=[0.01, 0.01], beta_deg=[60, 30], t_c=[0.02, 0.02], cl_design=[0, 0])
    sv = PropellerSolver(Propeller(bl, B, 2.0), wake=WakeSettings(hub_images=False, length_D=40),
                         settings=SolverSettings(n_panels=16, nacelle=False))
    geo = sv._geometry(0.0)
    V, Omega = 1.0, 3.0
    gam = np.full(sv.N, 1e-3)
    Aa, At, Ar, info = sv._influence(geo, gam, V, Omega, 0.0, None)
    r = geo["r"]
    mid = (r > 0.3) & (r < 0.8)
    ut = (At @ gam)[mid]
    np.testing.assert_allclose(ut, B * 1e-3 / (4 * np.pi * r[mid]), rtol=0.01)       # swirl B G/(4 pi r)
    ua = (Aa @ gam)[mid]
    gamma_cyl = B * 1e-3 * Omega / (2 * np.pi * (V + 2 * info["ua0"].mean()))
    np.testing.assert_allclose(ua, 0.5 * gamma_cyl, rtol=0.03)                        # vortex cylinder
