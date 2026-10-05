"""Port of BoB 3.5 (Broadband noise for Open rotor Blades, ANTC / Airbus, University of Southampton).

The MATLAB routines are ported line by line so that results agree with BoB to
round-off; see ``bbnoise.bob.run.run_bob`` and the ``bbnoise bob`` command.
"""
from .inputs import BoBError  # noqa: F401
from .options import DEFAULTS, parse_launch_file  # noqa: F401
from .run import run_bob  # noqa: F401
