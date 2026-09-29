import numpy as np
import pytest

from bbnoise.airfoil import le_response, te_response
from bbnoise.boundarylayer import bpm, bpm_thickness, flat_plate
from bbnoise.special import Estar, Estar_over_sqrt, sears
from bbnoise.turbulence import Liepmann, VonKarman, WakeTurbulence, make_spectrum
from bbnoise.wallpressure import WPS_MODELS, BoundaryLayer, wps, wps_normalised


def test_estar_over_sqrt_entire():
    # value at 0 and consistency with E*(2z)/sqrt(z) for positive and negative arguments
    assert abs(Estar_over_sqrt(0.0) - 2 / np.sqrt(np.pi)) < 1e-12
    for z in (0.3, 4.0):
        assert abs(Estar_over_sqrt(z) - Estar(2 * z) / np.sqrt(z)) < 1e-12
    assert np.isfinite(Estar_over_sqrt(-3.0))


def test_sears_limits():
    assert abs(abs(sears(1e-6)) - 1) < 1e-4
    k = 50.0
    assert abs(abs(sears(k)) * np.sqrt(2 * np.pi * k) - 1) < 0.02


def test_spectrum_factory():
    assert isinstance(make_spectrum("von Karman", 1, 1), VonKarman)
    assert isinstance(make_spectrum("Liepmann", 1, 1), Liepmann)
    with pytest.raises(ValueError):
        make_spectrum("kolmogorov", 1, 1)


def test_spectral_tails():
    # von Karman decays as k^-8/3 and Liepmann as k^-3 at high wavenumber
    vk, lp = VonKarman(1.0, 0.05), Liepmann(1.0, 0.05)
    k1, k2 = 1e5, 1e6
    assert abs(np.log(vk.phi_ww(k2, 0) / vk.phi_ww(k1, 0)) / np.log(10) + 8 / 3) < 1e-2
    assert abs(np.log(lp.phi_ww(k2, 0) / lp.phi_ww(k1, 0)) / np.log(10) + 3) < 1e-2
    assert vk.phi_ww(k2, 0.0) > lp.phi_ww(k2, 0.0)


def test_periodic_wake_redistributes_energy():
    # a long integral scale compared with the wake spacing gives a structured (non-monotonic)
    # spectrum; the passage-averaged model has the same energy but a smooth spectrum
    kw_args = dict(B1=10, Omega_rel=1000.0, w_c=5.0, Lw_over_s=0.05, Lambda=0.05)
    per = WakeTurbulence(model="periodic", **kw_args)
    avg = WakeTurbulence(model="averaged", **kw_args)
    U = 100.0
    K = np.linspace(1.0, 600.0, 1200)
    a = per.phi(K, 0.0, U, 0.2)
    b = avg.phi(K, 0.0, U, 0.2)
    d = np.diff(a[K > 150])
    assert np.any(d > 0) and np.any(d < 0)          # local maxima beyond the main peak
    assert np.max(np.abs(10 * np.log10(a / b))) > 1.0


def test_le_response_finite_everywhere():
    Kx = np.geomspace(0.01, 100, 50)
    for q in (-5.0, 0.0, 3.0):
        L = le_response(Kx, 0.0, 0.4, np.full_like(Kx, q))
        assert np.all(np.isfinite(L))


def test_te_backscatter_small_at_high_frequency():
    K = 40.0
    q = 0.0
    I1 = te_response(K, 1 / 0.7, 0.0, 0.2, q, backscatter=False)
    I = te_response(K, 1 / 0.7, 0.0, 0.2, q, backscatter=True)
    assert abs(abs(I) / abs(I1) - 1) < 0.1


def test_bpm_thickness_trends():
    t0 = bpm_thickness(0.3048, 71.3, alpha_deg=0)
    t6 = bpm_thickness(0.3048, 71.3, alpha_deg=6)
    assert t6["suction"][1] > t0["suction"][1] > t6["pressure"][1]
    tr = bpm_thickness(0.3048, 71.3, tripped=True)["suction"][1]
    un = bpm_thickness(0.3048, 71.3, tripped=False)["suction"][1]
    assert tr > un


@pytest.mark.parametrize("model", list(WPS_MODELS))
def test_wps_positive_and_decaying(model):
    bl = bpm(0.3048, 71.3)["suction"]
    w = np.geomspace(10, 1e6, 200)
    phi = wps(model, w, bl)
    assert np.all(phi > 0)
    assert phi[-1] < phi.max() * 1e-2


def test_gep_regression_value():
    # Phi Ue/(tau_w^2 delta*) at omega delta*/Ue = 1, beta_C = 0, M = 0.1, Cf = 0.003, R_T = 10
    bl = BoundaryLayer(Ue=34.0, delta_star=0.002, delta=0.016, cf=0.003, beta_c=0.0, c0=340.0,
                       nu=34.0 * 0.002 * 0.0015 / 10.0).complete()
    assert abs(bl.RT_star - 10.0) < 1e-9
    expected = (5.41 + 0.003) / (1 + 1 + 0.1 + 4.6 / (0.003 * 10 ** 5.83))
    assert abs(wps_normalised("dominique_gep", 1.0, bl) - expected) < 1e-9


def test_apg_raises_rozenberg():
    zpg = BoundaryLayer(Ue=50, delta_star=0.002, delta=0.016, beta_c=0.0).complete()
    apg = BoundaryLayer(Ue=50, delta_star=0.002, delta=0.016, beta_c=3.0).complete()
    assert wps_normalised("rozenberg", 0.3, apg) > wps_normalised("rozenberg", 0.3, zpg)


def test_flat_plate_bl():
    bl = flat_plate(0.1, 50)["suction"]
    assert 1.2 < bl.H < 1.4 and bl.cf > 0
