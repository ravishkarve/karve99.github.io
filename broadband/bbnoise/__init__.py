"""bbnoise: aerodynamic broadband noise of rotors after V. P. Blandeau's thesis.

V. P. Blandeau, "Aerodynamic broadband noise from contra-rotating open rotors",
PhD thesis, ISVR, University of Southampton (2011).

* rotor-wake interaction (leading-edge) noise, full rotating-dipole and simplified
  (Amiet azimuthal average) formulations, von Karman and Liepmann spectra,
  periodic or passage-averaged front-rotor wakes
* trailing-edge self noise, full and simplified formulations, with the Amiet,
  Chase-Howe, Goody, Rozenberg, Kamruzzaman, Lee and VKI GEP wall-pressure models
"""
__version__ = "0.1.0"

from .model import run_case, CaseResult  # noqa: E402,F401
from .cases import CASES, get_case, list_cases  # noqa: E402,F401
