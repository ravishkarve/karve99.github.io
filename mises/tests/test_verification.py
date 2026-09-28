import pytest

from pymises import verification as v


@pytest.mark.parametrize("fn", v.QUICK_CASES, ids=lambda f: f.__name__)
def test_quick_verification_case(fn):
    r = fn()
    assert r.passed, f"{r.name}: {r.metric} = {r.value} (tol {r.tolerance}) {r.details}"


@pytest.mark.slow
@pytest.mark.parametrize("fn", v.SLOW_CASES, ids=lambda f: f.__name__)
def test_slow_verification_case(fn):
    r = fn()
    assert r.passed, f"{r.name}: {r.metric} = {r.value} (tol {r.tolerance}) {r.details}"
