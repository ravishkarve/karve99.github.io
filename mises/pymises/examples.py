"""Example configuration files (also available as ``pymises example NAME DIR``)."""
from __future__ import annotations

from pathlib import Path

COMPRESSOR = """\
# Subsonic compressor cascade: C4 thickness on a circular-arc camber line.
# Run with:  pymises run compressor.toml
[case]
name = "C4 compressor cascade"
method = "panel"
output_dir = "results/compressor"

[geometry]
type = "parametric"
inlet_metal_angle = 45.0     # deg from axial
exit_metal_angle = 15.0
max_thickness = 0.08         # t/c
thickness_form = "c4"        # naca65 | naca4 | c4
pitch = 0.9                  # s/c
te_thickness = 0.004         # trailing-edge thickness / chord

[flow]
inlet_mach = 0.5
inlet_angle = 43.0           # deg from axial (incidence = inlet_angle - inlet_metal_angle)
reynolds = 5.0e5             # rho1 V1 c / mu1

[viscous]
ncrit = 9.0                  # e^N transition (9 = low-turbulence wind tunnel)
xtr_upper = 1.0              # forced transition x/c (1.0 = free transition)
xtr_lower = 1.0
"""

COMPRESSOR_SWEEP = """\
# Loss bucket: incidence sweep of the C4 compressor cascade.
[case]
name = "C4 compressor cascade - incidence sweep"
method = "panel"
output_dir = "results/compressor_sweep"

[geometry]
type = "parametric"
inlet_metal_angle = 45.0
exit_metal_angle = 15.0
max_thickness = 0.08
thickness_form = "c4"
pitch = 0.9
te_thickness = 0.004

[flow]
inlet_mach = 0.5
inlet_angle = 43.0
reynolds = 5.0e5

[viscous]
ncrit = 9.0

[sweep]
parameter = "flow.inlet_angle"
start = 35.0
stop = 51.0
step = 2.0
"""

TURBINE = """\
# Turbine cascade: front-loaded Bezier camber line, 90 degrees of turning.
[case]
name = "Turbine cascade"
method = "panel"
output_dir = "results/turbine"

[geometry]
type = "parametric"
camber = "bezier"
le_camber_fraction = 0.72    # > 0.5: turning concentrated near the LE (straight back)
inlet_metal_angle = 30.0
exit_metal_angle = -60.0
max_thickness = 0.18
thickness_form = "naca65"
pitch = 0.85
te_thickness = 0.01

[flow]
inlet_mach = 0.25
inlet_angle = 30.0
reynolds = 5.0e5

[viscous]
ncrit = 9.0
"""

EULER = """\
# High-subsonic compressor cascade with the Euler solver (compressible, captures shocks).
[case]
name = "C4 compressor cascade (Euler)"
method = "euler"
output_dir = "results/compressor_euler"

[geometry]
type = "parametric"
inlet_metal_angle = 45.0
exit_metal_angle = 15.0
max_thickness = 0.08
thickness_form = "c4"
pitch = 0.9
te_thickness = 0.004

[flow]
inlet_mach = 0.7
inlet_angle = 44.0
reynolds = 8.0e5

[viscous]
ncrit = 9.0

[euler]
ni_blade = 72                # cells along the blade
nj = 28                      # cells across the passage
coupling_cycles = 8
"""

MISES_BLADE_CONFIG = """\
# Using a MISES blade file (blade.xxx format: name, SINL SOUT CHINL CHOUT PITCH, x y ...)
[case]
name = "Blade from a MISES blade file"
method = "panel"
output_dir = "results/mises_file"

[geometry]
type = "mises"
file = "blade.c4"

[flow]
inlet_mach = 0.4
inlet_angle = 42.0
reynolds = 3.0e5

[viscous]
ncrit = 7.0
"""

AIRFOIL = """\
# A cascade built from aerofoil coordinates in Selig format (TE -> upper -> LE
# -> lower -> TE, as in the UIUC database and XFOIL).  Lednicer format works too.
# The section is scaled to the chord, rotated by the stagger angle and spaced
# at the given pitch.  To paste coordinates instead of naming a file, replace
# `file` by:   coordinates = '''
#              NACA 4412
#              1.000000  0.001300
#              ...
#              '''
[case]
name = "NACA 4412 cascade from Selig coordinates"
method = "panel"
output_dir = "results/airfoil"

[geometry]
type = "selig"
file = "naca4412.dat"        # path relative to this file
stagger = 30.0               # chord angle from axial [deg]
solidity = 1.2               # c/s  (or pitch = s/c)
# chord = 1.0                # scale factor for the section
# flip = false               # mirror the section (swap suction and pressure sides)

[flow]
inlet_mach = 0.3
inlet_angle = 40.0
reynolds = 5.0e5

[viscous]
ncrit = 9.0

[sweep]
parameter = "flow.inlet_angle"
values = [34.0, 37.0, 40.0, 43.0, 46.0]
"""


def _mises_blade_file(path):
    from .geometry import Blade
    blade = Blade.from_parameters(45.0, 15.0, 0.08, pitch=0.9, thickness_form="c4",
                                  te_thickness=0.004, name="C4 45/15 compressor blade")
    blade.write_mises(path, inlet_angle=42.0)


def _naca4412_selig(path):
    """A 69-point NACA 4412 in Selig format, like a typical UIUC database file."""
    from .geometry import Blade
    Blade.naca4("4412", pitch=1.0, n_points=35).write_selig(path)


EXAMPLES = {
    "compressor": {"compressor.toml": COMPRESSOR},
    "sweep": {"compressor_sweep.toml": COMPRESSOR_SWEEP},
    "turbine": {"turbine.toml": TURBINE},
    "euler": {"compressor_euler.toml": EULER},
    "mises": {"mises_file.toml": MISES_BLADE_CONFIG, "blade.c4": _mises_blade_file},
    "airfoil": {"airfoil.toml": AIRFOIL, "naca4412.dat": _naca4412_selig},
}


def write_example(name, directory="."):
    """Write the files of an example into ``directory``; returns the paths."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for fname, text in EXAMPLES[name].items():
        p = d / fname
        if callable(text):
            text(p)
        else:
            p.write_text(text)
        out.append(p)
    return out
