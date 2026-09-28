import math

import numpy as np
import pytest

from pymises import Blade
from pymises.panel import CascadePanelMethod, _coth_minus_inv, _log_sinh_over_w


def test_kernel_series_and_asymptotics_agree():
    w = np.array([0.3 + 0.2j, 0.99 + 0.1j, 1.01 - 0.4j, 3.0 + 1.0j, -2.0 + 0.5j])
    ref = np.log(np.abs(np.sinh(w) / w))
    np.testing.assert_allclose(_log_sinh_over_w(w), ref, rtol=1e-12, atol=1e-13)
    np.testing.assert_allclose(_coth_minus_inv(w), 1 / np.tanh(w) - 1 / w, rtol=1e-10, atol=1e-12)
    # large |Re w| must not overflow
    assert np.isfinite(_log_sinh_over_w(np.array([800.0 + 0.3j]))).all()


def test_symmetric_aerofoil_zero_lift():
    b = Blade.naca4("0012", pitch=1e4, alpha=0.0).repanel(160)
    sol = CascadePanelMethod(b).solve(0.0)
    assert abs(sol.circulation) < 1e-10
    n = b.n_points
    np.testing.assert_allclose(sol.gamma, -sol.gamma[::-1], atol=1e-10)


def test_naca0012_inviscid_lift_and_peak_speed():
    b = Blade.naca4("0012", pitch=1e4, alpha=5.0).repanel(200)
    sol = CascadePanelMethod(b).solve(0.0)
    cl = -2.0 * sol.circulation
    assert cl == pytest.approx(0.604, rel=0.01)                 # XFOIL inviscid 0.60
    b0 = Blade.naca4("0012", pitch=1e4, alpha=0.0).repanel(200)
    assert CascadePanelMethod(b0).solve(0.0).ue.max() == pytest.approx(1.19, abs=0.01)


def test_cascade_far_field_relations(compressor_blade):
    b = compressor_blade.closed_te().repanel(160)
    sol = CascadePanelMethod(b).solve(43.0)
    # Kutta-Joukowski for a cascade: circulation = s (v2 - v1)  (unit axial velocity here)
    assert sol.circulation == pytest.approx(b.pitch * (sol.v2 - sol.v1), rel=1e-10)
    assert sol.u2 == pytest.approx(sol.u1)                       # incompressible, no sources
    assert math.tan(math.radians(sol.beta1)) == pytest.approx(sol.v1 / sol.u1)
    assert 17.0 < sol.beta2 < 25.0                                # turning with ~6 deg deviation
    assert sol.gamma[0] == pytest.approx(-sol.gamma[-1])         # Kutta condition


def test_periodicity_translation_invariance(compressor_blade):
    b = compressor_blade.closed_te().repanel(120)
    s1 = CascadePanelMethod(b).solve(40.0)
    s2 = CascadePanelMethod(b.translated(0.3, 2 * b.pitch)).solve(40.0)
    np.testing.assert_allclose(s1.gamma, s2.gamma, atol=1e-9)


def test_solidity_trend(compressor_blade):
    """Higher solidity guides the flow better: exit angle closer to the metal angle."""
    b2 = []
    for s in (1.4, 0.9, 0.6):
        b = Blade.from_parameters(45, 15, 0.08, pitch=s, thickness_form="c4").closed_te().repanel(160)
        b2.append(CascadePanelMethod(b).solve(43.0).beta2)
    assert b2[0] > b2[1] > b2[2] > 15.0


def test_interaction_matrix_properties(compressor_blade):
    b = compressor_blade.closed_te().repanel(160)
    pm = CascadePanelMethod(b)
    inv = pm.solve(43.0)
    D = pm.ue_sensitivity(inv.stag_panel)
    d = np.diag(D)[5:-5]
    assert np.all(d > 0)                          # a local displacement bump speeds up the flow
    G = pm.mass_defect_operator(inv.stag_panel)
    m = np.linspace(0, 1, pm.N)
    # emitted flux telescopes to the trailing-edge mass defects of both surfaces
    assert np.dot(G @ m, pm.L) == pytest.approx(m[0] + m[-1], rel=1e-12)


def test_source_model_matches_displaced_body(compressor_blade):
    """Mass-defect sources reproduce the edge-velocity change of a displaced surface."""
    b = compressor_blade.repanel(180)
    pm = CascadePanelMethod(b)
    inv = pm.solve(39.0)
    k = inv.stag_panel
    s = np.concatenate([[0.0], np.cumsum(pm.L)])
    sa, sb = s[k + 30], s[k + 70]
    bump = np.where((s > sa) & (s < sb), np.sin(np.pi * (s - sa) / (sb - sa)) ** 2, 0.0)
    eps = 1e-4
    due_src = np.abs(pm.solve_with_mass_defect(39.0, eps * bump * inv.ue, k).gamma) - inv.ue
    tx, ty = np.gradient(b.x), np.gradient(b.y)
    tn = np.hypot(tx, ty)
    bd = Blade(b.x + ty / tn * eps * bump, b.y - tx / tn * eps * bump, b.pitch)
    bd.meta["i_le"] = b.i_le
    due_disp = np.abs(CascadePanelMethod(bd).solve(39.0).gamma) - inv.ue
    idx = np.arange(k + 20, k + 80)
    diff = np.abs(due_src[idx] - due_disp[idx]).max() / np.abs(due_disp[idx]).max()
    assert diff < 0.15
