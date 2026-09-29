import pytest

from bbnoise import verification


@pytest.mark.parametrize("fn", verification.CHECKS, ids=lambda f: f.__name__)
def test_check_passes(fn):
    c = fn()
    assert c.passed, f"{c.name}: {c.metric} = {c.value} (tol {c.tolerance}) {c.details}"
