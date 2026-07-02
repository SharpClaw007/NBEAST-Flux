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


# ---- statistics awareness (criticism #7) ------------------------------------
def test_noisy_sign_flip_is_not_a_bracket():
    """Two near-critical points whose sign change is inside their own noise must
    not be accepted as a bracket — that 'root' is noise, not physics."""
    s = CriticalitySearch(1, 2)
    s.submit(1.0, 0.999, std=0.005)   # −100 pcm ± 500 pcm: indistinguishable from 1
    s.submit(2.0, 1.001, std=0.005)   # +100 pcm ± 500 pcm
    assert not s.bracketed
    assert s.solution["bracketed"] is False
    assert s.estimate_std() is None   # no bracket → no defensible interval


def test_significant_sign_flip_is_a_bracket():
    s = CriticalitySearch(1, 2)
    s.submit(1.0, 0.90, std=0.002)    # −10 000 pcm ± 200: clearly below
    s.submit(2.0, 1.10, std=0.002)    # clearly above
    assert s.bracketed
    assert s.estimate() == pytest.approx(1.5)


def test_estimate_interval_propagates_endpoint_noise():
    """σₓ from the false-position slope: symmetric bracket, σ(k)=0.01 each,
    slope 0.2/unit → ∂x/∂k = 2.5 per endpoint → σₓ = √2·2.5·0.01."""
    s = CriticalitySearch(1, 2)
    s.submit(1.0, 0.9, std=0.01)
    s.submit(2.0, 1.1, std=0.01)
    assert s.estimate() == pytest.approx(1.5)
    assert s.estimate_std() == pytest.approx(math.sqrt(2) * 2.5 * 0.01, rel=1e-6)
    assert s.solution["x_std"] == pytest.approx(s.estimate_std())


def test_one_noisy_near_target_point_does_not_converge():
    """A single 'k ≈ 1' with huge σ must not stop the search — the root isn't
    localized and the agreement is only statistical."""
    s = CriticalitySearch(1, 2)
    s.submit(1.0, 1.0005, std=0.004)   # within 2σ of target but σ ≫ tol_k, no bracket
    assert not s.converged
    assert s.propose() is not None     # the search keeps going


def test_converges_within_statistics_once_bracketed():
    s = CriticalitySearch(1, 2)
    s.submit(1.0, 0.95, std=0.001)
    s.submit(2.0, 1.05, std=0.001)     # significant bracket
    s.submit(1.5, 1.0005, std=0.001)   # |k−1| = 50 pcm ≤ 2σ = 200 pcm → done
    assert s.converged
    assert s.solution["x_std"] is not None


def test_particles_factor_scales_with_noise():
    s = CriticalitySearch(1, 2)
    assert s.particles_factor() == 1          # survey phase: cheap runs
    s.submit(1.0, 0.95, std=0.004)
    s.submit(2.0, 1.05, std=0.004)            # bracketed, σ = 400 pcm, tol 200 pcm
    # need σ → tol/2 = 100 pcm → (400/100)² = 16
    assert s.particles_factor() == 16
    s.submit(1.5, 1.02, std=0.002)            # tighter stats → smaller boost: (200/100)² = 4
    assert s.particles_factor() == 4
    s.submit(1.2, 1.01, std=0.0005)           # σ already below tol/2 → no boost needed
    assert s.particles_factor() == 1
    assert s.particles_factor() <= s.max_particles_factor


def test_tolerance_not_below_diagnostics_noise_floor():
    """tol_k defaults to the same 200 pcm the diagnostics call 'statistically weak'
    (_KEFF_PCM_WARN) — the search must not claim finer convergence than that."""
    from nbeast.core.results import _KEFF_PCM_WARN

    assert CriticalitySearch(1, 2).tol_k == pytest.approx(_KEFF_PCM_WARN * 1e-5)


def test_illinois_converges_on_convex_curve():
    """Plain regula falsi stalls one endpoint on convex k(x); Illinois must still
    converge within the budget on a strongly convex curve."""
    s = _drive(lambda x: 1.5 * (1 - math.exp(-x / 4.0)), 0.5, 40, max_evals=12)
    assert s.converged
    assert s.estimate() == pytest.approx(-4.0 * math.log(1 - 1 / 1.5), abs=5e-2)
