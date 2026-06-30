"""Tier-3 sweep value lists + criticality-search numerics (data-free).

The search is exercised against synthetic monotonic k(x) functions so its
convergence behaviour is checked without running OpenMC.
"""

import math

import pytest

from nbeast.core.sweep import CriticalitySearch, sweep_values


# ---- sweep value lists ----------------------------------------------------
def test_sweep_values_linear():
    assert sweep_values(1, 2, 5) == [1.0, 1.25, 1.5, 1.75, 2.0]


def test_sweep_values_single_point():
    assert sweep_values(3, 9, 1) == [3.0]


def test_sweep_values_log():
    vals = sweep_values(1e-2, 1e2, 5, log=True)
    assert vals[0] == pytest.approx(1e-2) and vals[-1] == pytest.approx(1e2)
    assert vals[2] == pytest.approx(1.0)  # geometric midpoint


def test_sweep_values_errors():
    with pytest.raises(ValueError):
        sweep_values(1, 2, 0)
    with pytest.raises(ValueError):
        sweep_values(-1, 10, 5, log=True)


# ---- criticality search ---------------------------------------------------
def _drive(kfun, lo, hi, **kw):
    s = CriticalitySearch(lo, hi, **kw)
    while (x := s.propose()) is not None:
        s.submit(x, kfun(x))
    return s


def test_search_bracketed_linear():
    # k = 1 + 0.08*(x - 8.7407): root exactly at 8.7407, already bracketed by [5, 12]
    s = _drive(lambda x: 1 + 0.08 * (x - 8.7407), 5, 12)
    assert s.converged
    assert s.estimate() == pytest.approx(8.7407, abs=1e-3)


def test_search_expands_bracket_upward():
    # k = 0.05x, root at x = 20; start below the root so the bracket must grow.
    s = _drive(lambda x: 0.05 * x, 1, 5, x_max=100)
    assert s.converged
    assert s.estimate() == pytest.approx(20.0, abs=1e-2)


def test_search_handles_decreasing_k():
    # k decreases with x: root of 2 - 0.1x = 1 is at x = 10.
    s = _drive(lambda x: 2.0 - 0.1 * x, 0, 5)
    assert s.converged
    assert s.estimate() == pytest.approx(10.0, abs=1e-2)


def test_search_nonlinear_monotone():
    # k = 1.5(1 - e^{-x/6}); k = 1 at x = 6 ln 3 ≈ 6.5917
    s = _drive(lambda x: 1.5 * (1 - math.exp(-x / 6.0)), 1, 30)
    assert s.converged
    assert s.estimate() == pytest.approx(6.0 * math.log(3), abs=5e-2)


def test_search_target_other_than_one():
    s = _drive(lambda x: 0.1 * x, 1, 5, target=1.2, x_max=100)
    assert s.estimate() == pytest.approx(12.0, abs=1e-2)


def test_search_gives_up_within_bounds():
    # Root would be at x = 20 but x_max caps the bracket at 6 — cannot reach it.
    s = _drive(lambda x: 0.05 * x, 1, 5, x_max=6, max_evals=15)
    assert not s.converged
    assert s.solution["x"] is not None  # still reports the best estimate it found


def test_search_respects_eval_budget():
    s = _drive(lambda x: math.atan(x), 0.1, 0.2, target=1.4, max_evals=4, x_max=1e6)
    assert s.solution["n_evals"] <= 4


def test_invalid_bracket_raises():
    with pytest.raises(ValueError):
        CriticalitySearch(5.0, 5.0)
