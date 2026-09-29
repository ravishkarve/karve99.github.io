import numpy as np

from bbnoise.boundarylayer import flat_plate
from bbnoise.rotor import Rotor, full_spectrum, observer_position, simplified_spectrum, sound_power
from bbnoise.sources import LESource, TESource
from bbnoise.turbulence import HomogeneousTurbulence


def _rotor(**kw):
    d = dict(B=3, r_tip=0.5, r_hub=0.15, chord=0.05, rpm=4000.0, Ux=30.0, n_strips=4)
    d.update(kw)
    return Rotor(**d)


def test_strip_kinematics():
    r = _rotor()
    st = r.strips()
    assert len(st) == 4
    assert abs(sum(s.dr for s in st) - 0.35) < 1e-12
    s = st[-1]
    assert abs(s.U - np.hypot(s.Omega * s.r, 30.0)) < 1e-12


def test_axisymmetry_in_azimuth():
    r = _rotor()
    src = LESource(HomogeneousTurbulence("vonkarman", 0.05, 0.05))
    f = 2 * np.pi * np.array([400.0, 3000.0])
    a = simplified_spectrum(r, src, f, observer_position(10, 60, 0))
    b = simplified_spectrum(r, src, f, observer_position(10, 60, 77))
    assert np.allclose(a, b, rtol=1e-6)


def test_inverse_square_law():
    r = _rotor()
    src = TESource(lambda s: flat_plate(s.chord, s.U))
    f = 2 * np.pi * np.array([1000.0, 5000.0])
    a = full_spectrum(r, src, f, observer_position(20, 70))
    b = full_spectrum(r, src, f, observer_position(40, 70))
    assert np.allclose(a / b, 4.0, rtol=2e-3)


def test_sound_power_positive():
    r = _rotor(n_strips=2)
    src = LESource(HomogeneousTurbulence("liepmann", 0.05, 0.05))
    W = sound_power(r, src, 2 * np.pi * np.array([500.0, 2000.0]), "simplified", n_theta=7)
    assert np.all(W > 0)
