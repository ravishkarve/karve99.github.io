"""pymises: a pythonic cascade blade-to-blade flow solver in the spirit of MISES.

Main entry points::

    from pymises import Blade, FlowConditions, ViscousOptions, CascadeSolver
    from pymises.config import run_config
"""
import os as _os

# The dense systems in pymises are small (a few hundred unknowns); multi-threaded
# BLAS only adds contention, which can make LU factorisations 30x slower.
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    _os.environ.setdefault(_v, "1")

from .geometry import Blade
from .solver import (CascadeResult, CascadeSolver, FlowConditions, PanelOptions,
                     ViscousOptions)
from .euler import EulerOptions

__version__ = "0.1.0"

__all__ = ["Blade", "CascadeSolver", "CascadeResult", "FlowConditions", "ViscousOptions",
           "PanelOptions", "EulerOptions", "__version__"]
