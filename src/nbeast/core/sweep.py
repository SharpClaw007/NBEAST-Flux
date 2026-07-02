"""Parameter sweeps and criticality search — the simple↔expert bridge.

A single k-effective run answers "is *this* configuration critical?". The research
motion is the next question: "*which* configuration is critical?" — what enrichment,
radius, or pitch drives k to 1, and how does k respond as a parameter varies. This
module holds the *numerics* for both, kept pure and OpenMC-free so they can be unit
tested without nuclear data: the GUI drives the actual transport runs and feeds the
results back in.

* :func:`sweep_values` — the list of parameter values for a sweep (linear or log).
* :class:`CriticalitySearch` — a robust, **statistics-aware** root finder that proposes
  the next parameter value to try and consumes the resulting ``(k, σ)``, converging on
  k = target (default 1.0). Every k from Monte Carlo is noisy, so the search:

  - only accepts a bracket when both endpoints differ from the target by more than
    their own 1σ (a sign flip inside the noise is not a root);
  - uses Illinois-variant false position (plain regula falsi retains a stale endpoint
    on convex curves) with a bisection fallback;
  - gates convergence on ``|k − target| ≤ max(tol_k, 2σ)`` *and* a localized root
    (bracket), so a single noisy near-target point can't stop the search;
  - asks the driver for more particles as the bracket narrows
    (:meth:`particles_factor`), shrinking σ in step with the interval;
  - reports the answer as an **interval** — :meth:`estimate` ± :meth:`estimate_std`,
    the endpoint σ propagated through the false-position slope.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def sweep_values(lo: float, hi: float, n: int, *, log: bool = False) -> list[float]:
    """``n`` parameter values from ``lo`` to ``hi`` inclusive (linear or log spaced)."""
    n = int(n)
    if n < 1:
        raise ValueError("n must be >= 1")
    lo, hi = float(lo), float(hi)
    if n == 1:
        return [lo]
    if log:
        if lo <= 0 or hi <= 0:
            raise ValueError("log spacing requires positive bounds")
        a, b = math.log(lo), math.log(hi)
        return [math.exp(a + (b - a) * i / (n - 1)) for i in range(n)]
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


@dataclass(frozen=True)
class SearchPoint:
    x: float          # parameter value
    k: float          # resulting k-effective
    std: float = 0.0  # 1-sigma Monte Carlo uncertainty on k


class CriticalitySearch:
    """Stateful driver for a criticality search; the caller does the transport runs.

    Usage::

        s = CriticalitySearch(lo, hi, target=1.0)
        while (x := s.propose()) is not None:
            k, std = run_and_get_keff(x, particles=base * s.particles_factor())
            s.submit(x, k, std)
        print(s.solution)   # includes x, x_std — quote the interval, not the number

    The bracket ``[lo, hi]`` is evaluated first. If those two points already straddle
    the target *significantly* (beyond their 1σ), Illinois false position homes in on
    the root; otherwise the bracket is expanded outward (assuming monotonicity) until
    it does or until ``[x_min, x_max]`` / the evaluation budget is exhausted.

    ``tol_k`` defaults to 200 pcm — deliberately the same level at which the run
    diagnostics (:data:`nbeast.core.results._KEFF_PCM_WARN`) call a k-eff
    "statistically weak": the search must not claim convergence finer than the level
    the rest of the tool treats as noise.
    """

    #: convergence claims require |k − target| ≤ max(tol_k, SIGMA_GATE·σ)
    SIGMA_GATE = 2.0

    def __init__(
        self,
        lo: float,
        hi: float,
        *,
        target: float = 1.0,
        tol_k: float = 2.0e-3,
        tol_x: float | None = None,
        max_evals: int = 12,
        x_min: float | None = None,
        x_max: float | None = None,
        max_particles_factor: int = 16,
    ):
        if hi == lo:
            raise ValueError("search bracket must have nonzero width")
        self.lo, self.hi = float(lo), float(hi)
        self.target = float(target)
        self.tol_k = float(tol_k)
        span = abs(self.hi - self.lo)
        self.tol_x = float(tol_x) if tol_x is not None else max(1e-9, 1e-4 * span)
        self.max_evals = int(max_evals)
        self.x_min = float(x_min) if x_min is not None else None
        self.x_max = float(x_max) if x_max is not None else None
        self.max_particles_factor = int(max_particles_factor)
        self.points: list[SearchPoint] = []
        self._failed = False           # ran out of room to bracket within bounds
        self._bracket: tuple[SearchPoint, SearchPoint] | None = None  # a.x < b.x
        self._stale = [0, 0]           # Illinois: consecutive retentions of (a, b)

    # ---- statistics ---------------------------------------------------------
    def _significant(self, p: SearchPoint) -> bool:
        """Is this point's k statistically distinguishable from the target (>1σ)?"""
        return abs(p.k - self.target) > p.std

    # ---- clamping -----------------------------------------------------------
    def _clamp(self, x: float) -> float:
        if self.x_min is not None:
            x = max(self.x_min, x)
        if self.x_max is not None:
            x = min(self.x_max, x)
        return x

    def _already_evaluated(self, x: float) -> bool:
        return any(abs(p.x - x) <= self.tol_x for p in self.points)

    # ---- stepping -----------------------------------------------------------
    def propose(self) -> float | None:
        """The next parameter value to evaluate, or None when finished."""
        if self.converged or self._failed or len(self.points) >= self.max_evals:
            return None
        n = len(self.points)
        if n == 0:
            return self._clamp(self.lo)
        if n == 1:
            x = self._clamp(self.hi)
            return None if self._already_evaluated(x) else x

        x = self._next_guess()
        if x is None or self._already_evaluated(x):
            return None
        return x

    def particles_factor(self) -> int:
        """Suggested multiplier on the per-run particle count for the *next* run.

        1 until a bracket exists (survey phase: cheap runs are fine). Once the search
        is homing in, statistics must keep pace with the shrinking interval: to gate
        convergence at tol_k, σ(k) needs to reach ~tol_k/2, and σ scales as
        1/√particles — so the factor is (σ_last / (tol_k/2))², capped.
        """
        if self._bracket is None or not self.points:
            return 1
        std = self.points[-1].std
        if std <= 0:
            return 1
        factor = math.ceil((std / (self.tol_k / 2.0)) ** 2)
        return max(1, min(self.max_particles_factor, factor))

    def submit(self, x: float, k: float, std: float = 0.0) -> None:
        point = SearchPoint(float(x), float(k), max(float(std), 0.0))
        self.points.append(point)
        self._update_bracket(point)

    def _update_bracket(self, p: SearchPoint) -> None:
        t = self.target
        if self._bracket is None:
            # Look for the tightest adjacent pair that *significantly* straddles the
            # target — a sign change within the endpoints' noise is not a bracket.
            pts = sorted(self.points, key=lambda q: q.x)
            best = None
            for a, b in zip(pts, pts[1:]):
                if ((a.k - t) * (b.k - t) < 0
                        and self._significant(a) and self._significant(b)):
                    if best is None or (b.x - a.x) < (best[1].x - best[0].x):
                        best = (a, b)
            if best is not None:
                self._bracket = best
                self._stale = [0, 0]
            return

        a, b = self._bracket
        if not (a.x < p.x < b.x) or not self._significant(p):
            return  # outside, or statistically indistinguishable from the target
        if (p.k - t) * (a.k - t) > 0:      # same side as a → replace a; b is retained
            self._bracket = (p, b)
            self._stale = [0, self._stale[1] + 1]
        else:
            self._bracket = (a, p)
            self._stale = [self._stale[0] + 1, 0]

    def _next_guess(self) -> float | None:
        t = self.target
        if self._bracket is not None:
            a, b = self._bracket
            # Illinois false position: halve the *retained* endpoint's residual
            # (stale[0] counts consecutive retentions of a, stale[1] of b) so a
            # convex k(x) can't pin one endpoint forever.
            da = (a.k - t) * (0.5 ** self._stale[0])
            db = (b.k - t) * (0.5 ** self._stale[1])
            x = (a.x * db - b.x * da) / (db - da)
            if not self._already_evaluated(x):
                return x
            mid = 0.5 * (a.x + b.x)     # bisection fallback keeps making progress
            return None if self._already_evaluated(mid) else mid

        # Not bracketed: expand outward in the direction that moves k toward target,
        # assuming monotonic k(x) (slope from the two extreme points).
        pts = sorted(self.points, key=lambda p: p.x)
        p0, pN = pts[0], pts[-1]
        if pN.x == p0.x:
            return None
        slope = (pN.k - p0.k) / (pN.x - p0.x)
        if slope == 0:
            return None  # flat — can't progress
        below = pN.k < t and p0.k < t  # all evaluated k below the target
        # Need to move k up if below, down if above. Direction in x depends on slope.
        go_up = (below and slope > 0) or ((not below) and slope < 0)
        span = max(pN.x - p0.x, self.tol_x)
        x = (pN.x + span) if go_up else (p0.x - span)
        x = self._clamp(x)
        if self._already_evaluated(x):
            self._failed = True  # clamped onto an existing point: out of room
            return None
        return x

    # ---- results ------------------------------------------------------------
    @property
    def bracketed(self) -> bool:
        return self._bracket is not None

    @property
    def converged(self) -> bool:
        if not self.points:
            return False
        p = self.points[-1]
        miss = abs(p.k - self.target)
        # A clean hit: within tol_k with statistics at least as tight as tol_k. This
        # is the only way to converge unbracketed (e.g. an exact deterministic hit).
        if miss <= self.tol_k and p.std <= self.tol_k:
            return True
        if self._bracket is None:
            return False
        # Localized root + last point within statistics of the target: more runs at
        # this quality cannot resolve further — converged *within statistics*, and the
        # answer is quoted as an interval.
        if miss <= max(self.tol_k, self.SIGMA_GATE * p.std):
            return True
        # A tight significant bracket also counts.
        a, b = self._bracket
        return (b.x - a.x) <= self.tol_x

    def best(self) -> SearchPoint | None:
        """The evaluated point whose k is closest to the target."""
        if not self.points:
            return None
        return min(self.points, key=lambda p: abs(p.k - self.target))

    def estimate(self) -> float | None:
        """Best estimate of the critical parameter value.

        The false-position root of the current significant bracket when one exists
        (sub-grid accuracy), else the closest evaluated point.
        """
        if self._bracket is not None:
            a, b = self._bracket
            da, db = a.k - self.target, b.k - self.target
            return (a.x * db - b.x * da) / (db - da)
        bp = self.best()
        return bp.x if bp else None

    def estimate_std(self) -> float | None:
        """1σ uncertainty on :meth:`estimate`, from the bracket endpoints' k-noise
        propagated through the false-position linear interpolant:
        ∂x*/∂k_a = L·d_b/Δ², ∂x*/∂k_b = −L·d_a/Δ² with L = a.x − b.x, Δ = d_b − d_a.
        None when no bracket exists (an unlocalized root has no defensible interval).
        """
        if self._bracket is None:
            return None
        a, b = self._bracket
        da, db = a.k - self.target, b.k - self.target
        delta = db - da
        if delta == 0:
            return None
        length = a.x - b.x
        var = (length / delta ** 2) ** 2 * (db ** 2 * a.std ** 2 + da ** 2 * b.std ** 2)
        return math.sqrt(var)

    @property
    def solution(self) -> dict:
        bp = self.best()
        return {
            "x": self.estimate(),
            "x_std": self.estimate_std(),
            "k": bp.k if bp else None,
            "target": self.target,
            "converged": self.converged,
            "bracketed": self.bracketed,
            "n_evals": len(self.points),
            "points": [(p.x, p.k, p.std) for p in self.points],
        }
