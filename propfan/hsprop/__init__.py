"""hsprop: performance of very-high-solidity propellers and propfans up to Mach 0.8+."""
from .gas import Atmosphere
from .geometry import Blade, Nacelle, Propeller
from .section import SectionModel, SectionOptions
from .solver import OperatingPoint, PropellerSolver, Result, SolverSettings
from .wake import WakeSettings

__version__ = "0.1.0"
__all__ = ["Atmosphere", "Blade", "Nacelle", "Propeller", "SectionModel", "SectionOptions",
           "OperatingPoint", "PropellerSolver", "Result", "SolverSettings", "WakeSettings"]
