import os
import sys
from pathlib import Path

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402


def pytest_addoption(parser):
    parser.addoption("--runslow", action="store_true", default=False,
                     help="run slow tests (Euler solutions, ~1-3 min)")


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: slow test, needs --runslow")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runslow"):
        return
    skip = pytest.mark.skip(reason="slow test: use --runslow")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def compressor_blade():
    from pymises import Blade
    return Blade.from_parameters(45.0, 15.0, 0.08, pitch=0.9, thickness_form="c4",
                                 te_thickness=0.004)


@pytest.fixture(scope="session")
def compressor_result(compressor_blade):
    from pymises import CascadeSolver, FlowConditions
    return CascadeSolver(compressor_blade,
                         FlowConditions(inlet_mach=0.5, inlet_angle=43.0, reynolds=5e5)).solve()
