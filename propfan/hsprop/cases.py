"""Reference propellers.

``sr3_class``  An eight-bladed, 45-degree-swept propfan reconstructed from the published
               SR-3 description (D = 0.622 m, hub/tip 0.235, activity factor 235 per blade,
               integrated design lift coefficient 0.214, 45 deg tip sweep, NACA 16 sections,
               area-ruled spinner, design point M 0.8 / 10.668 km / 243.8 m/s tip speed /
               J 3.06 / CP 1.70).  The published planform, thickness and sweep curves were not
               available to the author, so the distributions are smooth curves with those
               integral properties, and camber and twist are designed here (Betz loading at
               ideal incidence, ``design.design``).  It is an "SR-3-class" propeller, not the
               SR-3.
``sr2_class``  The straight-bladed companion (SR-2: eight blades, activity factor 203, the same
               design point, conventional spinner), designed the same way.
``high_solidity_12``  A twelve-bladed derivative of the SR-3 class (activity factor 200 per
               blade, total 2400 against 1880) designed for the same power per unit blade area
               (CP 2.17 at J 3.06): a very-high-solidity study case.

The designed geometries ship as JSON in ``hsprop/data``; ``reference(name)`` loads them and
``build(name)`` regenerates them (about a minute each).
"""
from __future__ import annotations

from importlib import resources

import numpy as np

from .geometry import Blade, Nacelle, Propeller
from .section import kuchemann_factor
from .solver import OperatingPoint

SR3_DESIGN = dict(mach=0.8, altitude=10668.0, tip_speed=243.84, J=3.06, CP=1.70)

# chord b/D control values (shape only; scaled to the activity factor)
_PLANFORMS = {
    "sr3": ([0.235, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 1.00],
            [0.120, 0.135, 0.160, 0.175, 0.180, 0.172, 0.152, 0.118, 0.090, 0.045]),
    "sr2": ([0.235, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 1.00],
            [0.120, 0.135, 0.155, 0.166, 0.170, 0.166, 0.152, 0.128, 0.108, 0.070]),
}
_THICKNESS = ([0.235, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00],
              [0.050, 0.045, 0.038, 0.033, 0.030, 0.027, 0.024, 0.022, 0.020])
_DESIGN_CL = ([0.235, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00],
              [0.32, 0.30, 0.27, 0.24, 0.21, 0.18, 0.15, 0.12, 0.08])


def _scale_to(values, x, target, fn):
    v = np.asarray(values, dtype=float)
    return v * target / fn(v, x)


def _af(b, x):
    xx = np.linspace(max(0.15, x[0]), 1.0, 2001)
    return 100000.0 / 16.0 * np.trapezoid(np.interp(xx, x, b) * xx ** 3, xx)


def _cli(c, x):
    xx = np.linspace(x[0], 1.0, 2001)
    return 3.0 * np.trapezoid(np.interp(xx, x, c) * xx ** 2, xx)


def propfan_blade(af=235.0, cli=0.214, tip_sweep_deg=45.0, planform="sr3", hub=0.235, n=41,
                  design=SR3_DESIGN, mach_n_target=0.85, name="propfan"):
    """Smooth propfan blade with a given activity factor, integrated design lift coefficient
    and tip sweep.

    The mid-chord sweep is laid out the way Hamilton Standard's were: outboard of the radius
    where the design relative Mach number first exceeds ``mach_n_target`` the blade is swept
    just enough to hold the normal Mach number there, allowing for the unsweeping of the
    isobars near the tip (Kuchemann), and limited to ``tip_sweep_deg``; inboard it is swept
    slightly forward.  ``tip_sweep_deg = 0`` gives a straight blade.  The twist is a placeholder
    until the blade is designed (``design.design``).
    """
    x = hub + (1.0 - hub) * 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, n)))
    xb, bb = _PLANFORMS[planform]
    b = _scale_to(np.interp(x, xb, bb), x, af, _af)
    t = np.interp(x, *_THICKNESS)
    c = _scale_to(np.interp(x, *_DESIGN_CL), x, cli, _cli)
    if tip_sweep_deg > 0.0:
        M, lam_d = design["mach"], design["J"] / np.pi
        m_rel = M * np.sqrt(1.0 + (x / lam_d) ** 2)
        need = np.arccos(np.minimum(1.0, mach_n_target / m_rel))
        x_s = lam_d * np.sqrt((mach_n_target / M) ** 2 - 1.0)
        d_tip = (1.0 - x) / (2.0 * np.maximum(b, 1e-3))          # distance from the tip in chords
        kf = np.maximum(kuchemann_factor(d_tip, np.maximum(need, 0.3)), 0.3)
        geo_sweep = np.degrees(np.arcsin(np.minimum(np.sin(need) / kf, np.sin(np.radians(tip_sweep_deg)))))
        fwd = -4.0 * np.sin(np.pi * np.clip((x - hub) / (x_s - hub), 0.0, 1.0))
        lam = np.maximum.accumulate(np.where(x >= x_s, geo_sweep, -90.0))
        lam = np.where(x < x_s, fwd, lam)
    else:
        lam = np.zeros_like(x)
    dmca = np.tan(np.radians(lam)) * 0.5                      # d(mca/D)/d(r/R)
    mca = np.concatenate([[0.0], np.cumsum(0.5 * (dmca[1:] + dmca[:-1]) * np.diff(x))])
    beta = np.degrees(np.arctan(design["J"] / (np.pi * x))) + 1.0
    return Blade(r_R=x, chord_D=b, beta_deg=beta, t_c=t, cl_design=c, mca_D=mca, name=name)


def sr3_class_blade(n=41):
    return propfan_blade(235.0, 0.214, 45.0, "sr3", n=n, name="SR-3 class")


def area_ruled_spinner(hub=0.235, root_speed=-0.10, mach=0.8, diameter=0.622, root_chord_D=0.12):
    """Area-ruled spinner: a 0.5 D nose and a waist under the blade root whose depth is chosen
    so that the flow over the root chord is decelerated by ``root_speed`` (fraction of V,
    chord average) at the design Mach number; the body radius at the propeller plane is the
    blade hub radius.  The SR-3 tests used such an area-ruled spinner to lower the blade-root
    Mach number."""
    from .nacelle import NacelleFlow

    def build(waist):
        return Nacelle.spinner(0.5 * hub / (1.0 - waist), nose_length_D=0.5, waist=waist, waist_x_D=0.0,
                               waist_width_D=0.22, length_D=5.0, tail_D=2.0)

    xs = np.linspace(-0.45, 0.45, 7) * root_chord_D * diameter

    def root_u(waist):
        fl = NacelleFlow(build(waist), diameter, mach)
        return float(fl.axial(xs, np.full(xs.size, 0.5 * hub * diameter * 1.02)).mean())

    lo, hi = 0.0, 0.35
    for _ in range(30):
        mid = 0.5 * (lo + hi)
        if root_u(mid) > root_speed:
            lo = mid
        else:
            hi = mid
    return build(0.5 * (lo + hi))


sr3_spinner = area_ruled_spinner


def conventional_spinner(hub=0.235):
    """Plain spinner (no area ruling) on a cylindrical nacelle."""
    return Nacelle.spinner(0.5 * hub, nose_length_D=0.5, waist=0.0, length_D=5.0, tail_D=2.0)


def _design(prop, CP, verbose=False, solver_kw=None, tip_relief=0.45):
    """Design camber and twist as the NASA/Hamilton Standard blades were: by strip theory
    with 2-D compressible sections, i.e. without the 3-D transonic relief (with it the
    designed camber of the SR-3 class would rise from the published CLi 0.214 to 0.28)."""
    from .design import design as inverse_design
    from .solver import SolverSettings
    op = OperatingPoint(mach=SR3_DESIGN["mach"], altitude=SR3_DESIGN["altitude"],
                        tip_speed=SR3_DESIGN["tip_speed"])
    solver_kw = solver_kw or {"settings": SolverSettings(relief_3d=False)}
    inverse_design(prop, op, CP, verbose=verbose, solver_kw=solver_kw, tip_relief=tip_relief)
    return prop


def sr3_class(design=True, verbose=False, solver_kw=None):
    blade = sr3_class_blade()
    prop = Propeller(blade, 8, 0.622, nacelle=area_ruled_spinner(root_chord_D=float(blade.chord_D[0])),
                     name="SR-3 class propfan")
    return _design(prop, SR3_DESIGN["CP"], verbose, solver_kw) if design else prop


def sr2_class(design=True, verbose=False, solver_kw=None):
    blade = propfan_blade(203.0, 0.214, 0.0, "sr2", name="SR-2 class")
    prop = Propeller(blade, 8, 0.622, nacelle=conventional_spinner(), name="SR-2 class propfan")
    return _design(prop, SR3_DESIGN["CP"], verbose, solver_kw) if design else prop


HS12_CP = SR3_DESIGN["CP"] * (12 * 200.0) / (8 * 235.0)


def high_solidity_12(design=True, verbose=False, solver_kw=None):
    blade = propfan_blade(200.0, 0.214, 45.0, "sr3", name="12-blade high solidity")
    prop = Propeller(blade, 12, 0.622, nacelle=area_ruled_spinner(root_chord_D=float(blade.chord_D[0])),
                     name="12-blade very-high-solidity propfan")
    return _design(prop, HS12_CP, verbose, solver_kw) if design else prop


BUILDERS = {"sr3_class": sr3_class, "sr2_class": sr2_class, "high_solidity_12": high_solidity_12}


def build(name, **kw):
    """Regenerate (design) a reference propeller."""
    if name not in BUILDERS:
        raise ValueError(f"unknown reference propeller {name!r}; choose from {sorted(BUILDERS)}")
    return BUILDERS[name](**kw)


def reference(name):
    """The shipped, designed reference propeller ``name`` (falls back to designing it)."""
    if name not in BUILDERS:
        raise ValueError(f"unknown reference propeller {name!r}; choose from {sorted(BUILDERS)}")
    path = resources.files("hsprop") / "data" / f"{name}.json"
    if path.is_file():
        with resources.as_file(path) as p:
            return Propeller.load(p)
    return build(name)
