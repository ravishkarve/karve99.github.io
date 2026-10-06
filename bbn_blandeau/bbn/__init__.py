"""bbn: broadband noise of rotors and contra-rotating open rotors after V. P. Blandeau's thesis.

V. P. Blandeau, *Aerodynamic broadband noise from contra-rotating open rotors*, PhD thesis,
Institute of Sound and Vibration Research, University of Southampton (2011).

Sources: rotor-wake interaction noise of the rear rotor (BRWI), rotor trailing-edge noise
(BRTE, full and simplified rotational formulations) and boundary-layer ingestion noise with a
hard wall.  A case has three input sections (rotor, noise_model, spectra); see :mod:`bbn.config`.
"""
from .config import load, run  # noqa: F401
from .examples import default_case  # noqa: F401
from .inputs import SolverError  # noqa: F401
from .run import solve  # noqa: F401

__version__ = "1.0.0"
