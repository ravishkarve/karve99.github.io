import math

import numpy as np
import pytest

from pymises import Blade
from pymises.geometry import half_thickness, _signed_area


def test_parametric_blade_properties(compressor_blade):
    b = compressor_blade
    a1, a2 = b.estimated_metal_angles()
    assert (a1, a2) == (45.0, 15.0)
    assert b.chord == pytest.approx(1.0, abs=2e-3)
    assert b.stagger == pytest.approx(30.0, abs=0.3)
    assert b.max_thickness == pytest.approx(0.08, abs=4e-3)
    assert b.te_gap == pytest.approx(0.004, rel=1e-6)
    assert b.pitch == pytest.approx(0.9)
    assert _signed_area(b.x, b.y) > 0          # counter-clockwise


def test_metal_angles_estimated_from_contour():
    b = Blade.from_parameters(40.0, 10.0, 0.06, pitch=1.0, thickness_form="naca65")
    c = Blade(b.x, b.y, b.pitch)                # no stored metal angles
    a1, a2 = c.estimated_metal_angles()
    assert a1 == pytest.approx(40.0, abs=1.5)
    assert a2 == pytest.approx(10.0, abs=1.5)


@pytest.mark.parametrize("form", ["naca65", "naca4", "c4"])
def test_thickness_forms_have_requested_maximum(form):
    xi = np.linspace(0, 1, 2001)
    t = 2 * half_thickness(xi, form, 0.12)
    assert t.max() == pytest.approx(0.12, rel=0.01)
    assert t[0] == 0.0


def test_orientation_is_normalised():
    b = Blade.from_parameters(45.0, 15.0, 0.08, pitch=0.9)
    r = Blade(b.x[::-1], b.y[::-1], b.pitch)
    assert _signed_area(r.x, r.y) > 0
    np.testing.assert_allclose(r.x, b.x)


def test_repanel_places_le_node_and_count(compressor_blade):
    r = compressor_blade.repanel(120)
    assert r.n_points == 121
    xl, yl = compressor_blade.le_point
    assert math.hypot(r.x[r.i_le] - xl, r.y[r.i_le] - yl) < 1e-9
    L = np.hypot(np.diff(r.x), np.diff(r.y))
    assert L[r.i_le - 1] < 3e-3 and L[0] > 5e-3     # fine at the LE, coarser at the TE


def test_closed_te(compressor_blade):
    c = compressor_blade.closed_te()
    assert c.te_gap < 1e-12
    assert c.meta["te_gap_original"] == pytest.approx(0.004)
    # geometry only changes near the trailing edge
    far = np.abs(compressor_blade.x - 0.4) < 0.1
    np.testing.assert_allclose(c.y[far], compressor_blade.y[far])


def test_mises_file_roundtrip(tmp_path, compressor_blade):
    p = tmp_path / "blade.test"
    compressor_blade.write_mises(p, inlet_angle=43.0)
    b = Blade.read_mises(p)
    assert b.pitch == pytest.approx(0.9)
    assert b.meta["sinl"] == pytest.approx(math.tan(math.radians(43.0)), rel=1e-5)
    np.testing.assert_allclose(b.x, compressor_blade.x, atol=1e-7)
    np.testing.assert_allclose(b.y, compressor_blade.y, atol=1e-7)


def test_naca4_isolated():
    b = Blade.naca4("0012", alpha=0.0)
    assert b.max_thickness == pytest.approx(0.12, abs=2e-3)
    assert b.chord == pytest.approx(1.0, abs=1e-3)
    assert Blade.naca4("2412").max_thickness == pytest.approx(0.12, abs=3e-3)


def test_axial_surfaces_single_valued(compressor_blade):
    x_le, x_te, fu, fl = compressor_blade.axial_surfaces()
    xs = np.linspace(x_le, x_te, 50)
    assert np.all(fu(xs) >= fl(xs) - 1e-12)
    assert fu(x_te) == pytest.approx(fl(x_te))        # sharpened TE


def test_bezier_camber_turbine_blade():
    b = Blade.from_parameters(30.0, -60.0, 0.18, pitch=0.85, camber="bezier",
                              le_camber_fraction=0.72)
    assert b.estimated_metal_angles() == (30.0, -60.0)
    assert b.stagger < -30.0
    with pytest.raises(ValueError):
        Blade.from_parameters(30.0, -60.0, 0.18, pitch=0.85, camber="spline")


def test_invalid_inputs():
    with pytest.raises(ValueError):
        Blade.from_parameters(45.0, 15.0, 0.08)                   # no pitch
    with pytest.raises(ValueError):
        Blade(np.zeros(3), np.zeros(3), 1.0)
    with pytest.raises(ValueError):
        half_thickness(0.5, "naca99")
