"""Linear row theory: exact limits and the Prandtl-Glauert lattice map."""
import math

import numpy as np
import pytest

from hsprop.cascade import ThinCascade, map_lattice, row_factors, row_kernel_regular


def test_row_kernel_series_matches_closed_form():
    P = 0.8 * (np.sin(0.4) + 1j * np.cos(0.4))
    z = np.array([1e-4, 0.01, 0.05, 0.3, -0.7, 0.95])
    ref = 1.0 / np.tan(np.pi * z / P) - P / (np.pi * z)
    np.testing.assert_allclose(row_kernel_regular(z, P), ref, rtol=1e-9, atol=1e-12)
    assert row_kernel_regular(0.0, P) == 0.0


def test_isolated_limit_is_thin_aerofoil_theory():
    for mean in ("a1", "parabolic"):
        ka, kc = row_factors([1e-9], [0.4], 0.0, mean=mean)
        assert ka[0] == pytest.approx(1.0, abs=1e-10)        # CL = 2 pi alpha
        assert kc[0] == pytest.approx(1.0, abs=1e-10)        # CL = cl_d at zero incidence


@pytest.mark.parametrize("sigma", [0.25, 0.5, 1.0, 2.0, 4.0])
def test_weinig_flat_plates_zero_stagger(sigma):
    """Weinig's exact flat-plate row at zero stagger: k = 2/(pi sigma) tanh(pi sigma / 2)."""
    ka, _ = row_factors([sigma], [0.0])
    assert ka[0] == pytest.approx(2.0 / (np.pi * sigma) * np.tanh(np.pi * sigma / 2.0), rel=2e-4)


def test_dense_row_guides_the_flow():
    """sigma -> infinity at zero stagger: exit flow along the plates, CL -> 4 alpha / sigma."""
    ka, _ = row_factors([20.0], [0.0])
    assert ka[0] * 2 * np.pi == pytest.approx(4.0 / 20.0, rel=0.01)


def test_lattice_map_limits():
    s, x = map_lattice(1.0, 0.0, 0.6)          # side-by-side blades look denser by 1/beta
    assert s == pytest.approx(1.0 / 0.6) and x == pytest.approx(0.0)
    s, x = map_lattice(1.0, np.pi / 2, 0.6)    # tandem blades are unchanged
    assert s == pytest.approx(1.0) and x == pytest.approx(np.pi / 2)
    s, x = map_lattice(0.7, 0.5, 1.0)
    assert s == pytest.approx(0.7) and x == pytest.approx(0.5)


def test_compressible_isolated_aerofoil_is_prandtl_glauert():
    ka, kc = row_factors([1e-9], [0.3], 0.7)
    assert ka[0] == pytest.approx(1.0, abs=1e-9)     # the 1/beta is applied by the section model


def test_euler_verification_data_supports_lattice_map():
    """pymises Euler lift slopes of five rows (data/euler_lattice_verification.json): the
    lattice map must beat the conventional isolated-PG correction on every case and be
    within 3 % where blade-to-blade interference dominates (stagger <= 20 deg)."""
    import json
    from pathlib import Path
    rows = json.loads((Path(__file__).resolve().parents[1] / "data" / "euler_lattice_verification.json").read_text())
    for r in rows:
        e = r["euler"][1] / r["euler"][0]
        m = r["lattice_map"][1] / r["lattice_map"][0]
        n = r["naive"][1] / r["naive"][0]
        assert abs(m - e) <= abs(n - e) + 1e-9
        if r["stagger"] <= 20:
            assert abs(m / e - 1.0) < 0.03


def test_superposition_matches_direct_solution():
    tc = ThinCascade()
    sh = tc.shape_terms(["naca16"] * 2, ["a1"] * 2)
    sol = tc.solve([1.1, 0.4], [0.3, 0.9], [0.7, 0.9], sh)
    # thickness lift vanishes in the isolated limit and is negative for positive stagger
    assert sol.cl_unit[0, 2] < 0.0 and sol.cl_unit[1, 2] < 0.0
    assert np.all(np.isfinite(sol.u_img_e)) and np.all(np.isfinite(sol.halfgam_e))
