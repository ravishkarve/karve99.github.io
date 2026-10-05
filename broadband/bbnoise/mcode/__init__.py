"""Port of a MATLAB broadband rotor-noise code (ANTC / Airbus, University of Southampton).

The MATLAB routines are ported line by line so that results agree with the MATLAB code to
round-off; see ``bbnoise.mcode.run.run_mcode`` and the ``bbnoise mcode`` command.
"""
from .inputs import MCodeError  # noqa: F401
from .options import DEFAULTS, parse_launch_file  # noqa: F401
from .run import run_mcode  # noqa: F401
