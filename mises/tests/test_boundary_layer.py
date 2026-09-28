import math

import numpy as np
import pytest

from pymises import Blade
from pymises.boundary_layer import (BLEnvironment, BoundaryLayerSolver, Surface, build_surfaces,
                                    cf_lam, cf_turb, di_lam, hkin, hs_lam, hs_turb, station_vars)
from pymises.panel import CascadePanelMethod


def test_laminar_closures_at_blasius():
    hk = 2.591
    assert hs_lam(hk) == pytest.approx(1.5725, abs=5e-3)        # Blasius H* = 1.5725
    assert cf_lam(hk, 1.0) == pytest.approx(0.441, rel=0.03)      # Cf Re_theta
    assert di_lam(hk, 1.0) * hs_lam(hk) / 2 == pytest.approx(0.1736, rel=0.03)  # CD Re_theta


def test_turbulent_closures_reasonable():
    rt = np.array([1e3, 1e4])
    cf = cf_turb(np.array([1.4, 1.4]), rt, 0.0)
    assert np.all(cf > 0) and cf[0] > cf[1]
    assert 1.4 < float(hs_turb(np.array([1.4]), np.array([1e4]), 0.0)[0]) < 1.9


def test_hk_compressibility():
    assert hkin(2.0, 0.0) == 2.0
    assert hkin(2.0, 0.5) < 2.0


def _flat(n, x0, re, ncrit=9.0, forced=None):
    env = BLEnvironment(reynolds=re, mach1=0.0, ncrit=ncrit)
    xi = np.linspace(x0, 1.0, n)
    srf = Surface("flat", np.arange(n), xi, xi, 0 * xi, xi, forced if forced else n)
    th0 = 0.664 * math.sqrt(x0 / re)
    out = BoundaryLayerSolver(env).march(srf, np.ones(n), init=(th0, 2.59 * th0))
    return env, xi, out


def test_blasius_growth():
    env, xi, (A, th, m, ue, typ) = _flat(120, 0.01, 1e6, ncrit=100)
    ex = 0.664 * np.sqrt(xi / 1e6)
    np.testing.assert_allclose(th[20:], ex[20:], rtol=0.02)
    assert np.all(typ == 1)


def test_forced_transition_gives_turbulent_growth():
    env, xi, (A, th, m, ue, typ) = _flat(150, 0.01, 1e6, forced=10)
    assert np.all(typ[10:] == 2) and np.all(typ[:10] == 1)
    st = station_vars(A, th, m, ue, typ, env)
    assert 1.3 < st.h[-1] < 1.6
    assert th[-1] > 2.0 * 0.664 / math.sqrt(1e6)                   # thicker than laminar


def test_inverse_mode_through_separation():
    """Strong deceleration: the march must switch to inverse mode, not produce NaNs."""
    env = BLEnvironment(reynolds=2e5, mach1=0.0)
    n = 120
    xi = np.linspace(0.01, 1.0, n)
    ue = np.where(xi < 0.3, 1.0, 1.0 - 0.8 * (xi - 0.3))
    srf = Surface("decel", np.arange(n), xi, xi, 0 * xi, xi, n)
    th0 = 0.664 * math.sqrt(xi[0] / 2e5)
    A, th, m, ueb, typ = BoundaryLayerSolver(env).march(srf, ue, init=(th0, 2.59 * th0))
    assert np.all(np.isfinite(th)) and np.all(np.isfinite(m))
    assert np.any(typ == 2)                                          # separation triggers transition
    assert np.any(np.abs(ueb - ue) > 1e-6)                           # inverse mode was used


def test_coupled_newton_converges_on_cascade(compressor_blade):
    b = compressor_blade.closed_te().repanel(160)
    pm = CascadePanelMethod(b)
    inv = pm.solve(43.0)
    env = BLEnvironment(reynolds=5e5, mach1=0.0)
    su, sl = build_surfaces(b.x, b.y, inv.stag_panel, inv.stag_frac)
    from pymises.solver import _close_te_bl
    D = pm.ue_sensitivity(su.stag_panel)
    su, sl, D = _close_te_bl(su, sl, D)
    out = BoundaryLayerSolver(env).solve_coupled([su, sl], inv.ue, D)
    assert out["converged"]
    assert out["residual"] < 1e-5
    assert out["iterations"] < 40


def test_build_surfaces_cover_all_nodes(compressor_blade):
    b = compressor_blade.closed_te().repanel(100)
    inv = CascadePanelMethod(b).solve(43.0)
    su, sl = build_surfaces(b.x, b.y, inv.stag_panel, inv.stag_frac)
    nodes = np.concatenate([su.nodes, sl.nodes] + ([[su.stag_node]] if su.stag_node is not None else []))
    assert sorted(nodes.tolist()) == list(range(b.n_points))
    assert np.all(np.diff(su.xi) > 0) and np.all(np.diff(sl.xi) > 0) and su.xi[0] > 0
