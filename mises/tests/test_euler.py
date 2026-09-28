import numpy as np
import pytest

from pymises import Blade, gas
from pymises.euler import EulerOptions, EulerSolver, HGrid, _thomas


def test_grid_geometry(compressor_blade):
    o = EulerOptions(ni_blade=40, nj=16, ni_inlet=12, ni_exit=14)
    g = HGrid.for_blade(compressor_blade, o, 43.0, 21.0)
    assert np.all(g.area > 0)
    # closed cells: face vectors sum to zero
    s = (g.Si[1:] - g.Si[:-1]) + (g.Sj[:, 1:] - g.Sj[:, :-1])
    assert np.abs(s).max() < 1e-12
    # periodic boundaries are exactly one pitch apart
    per = ~g.wall_lo
    dy = g.Y[:, -1] - g.Y[:, 0]
    cols = np.where(per)[0]
    assert np.allclose(dy[cols], compressor_blade.pitch)
    xc, yc = g.contour()
    assert xc[0] == pytest.approx(xc[-1]) and yc[0] == pytest.approx(yc[-1])


def test_irs_tridiagonal_solver():
    rng = np.random.default_rng(1)
    D = rng.standard_normal((4, 7, 5))
    e = rng.uniform(0.0, 1.0, (7, 5))
    X = _thomas(D, e, axis=1)
    # check residual of (1 + 2e) x_i - e (x_{i-1} + x_{i+1}) = d along axis 1
    Xp = np.pad(X, ((0, 0), (1, 1), (0, 0)))
    r = (1 + 2 * e) * X - e * (Xp[:, :-2] + Xp[:, 2:]) - D
    assert np.abs(r).max() < 1e-12


def test_freestream_preservation():
    from pymises.verification import verify_euler_freestream
    assert verify_euler_freestream().passed


def test_wall_mass_flux_is_zero_and_transpiration_adds_mass(compressor_blade):
    o = EulerOptions(ni_blade=30, nj=12, ni_inlet=10, ni_exit=10)
    g = HGrid.for_blade(compressor_blade, o, 43.0, 21.0)
    es = EulerSolver(g, 43.0, 0.4, opts=o)
    es.initialise(21.0)
    R0 = es.residual(es.U)
    f = np.zeros(2 * (g.i_te - g.i_le))
    f[5] = 1e-3
    es.set_transpiration(f)
    R1 = es.residual(es.U)
    # blowing enters the continuity residual as a negative (inflow) contribution
    assert (R0[0] - R1[0]).sum() == pytest.approx(1e-3, rel=1e-9)


def test_coarse_cascade_converges_and_conserves_mass(compressor_blade):
    o = EulerOptions(ni_blade=36, nj=14, ni_inlet=12, ni_exit=14, max_steps=4000, tol=1e-4)
    g = HGrid.for_blade(compressor_blade, o, 43.0, 21.0)
    es = EulerSolver(g, 43.0, 0.4, opts=o)
    es.initialise(21.0, 0.32)
    run = es.run()
    assert run["converged"]
    m_in = es.plane_fluxes(1)[0]
    m_out = es.plane_fluxes(g.ni - 2)[0]
    assert abs(m_out - m_in) / m_in < 5e-4
    assert es.inlet_state()[1] == pytest.approx(0.4, abs=1e-3)


@pytest.mark.slow
def test_nozzle_shock():
    from pymises.verification import verify_euler_nozzle
    r = verify_euler_nozzle()
    assert r.passed, r.details
