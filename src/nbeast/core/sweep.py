"""Parameter sweeps and criticality search — the simple↔expert bridge.

A single k-effective run answers "is *this* configuration critical?". The research
motion is the next question: "*which* configuration is critical?" — what enrichment,
radius, or pitch drives k to 1, and how does k respond as a parameter varies. This
module holds the *numerics* for both, kept pure and OpenMC-free so they can be unit
tested without nuclear data: the GUI drives the actual transport runs and feeds the
results back in.

* :func:`sweep_values` — the list of parameter values for a sweep (linear or log).
* :class:`CriticalitySearch` — a robust root finder that proposes the next parameter
  value to try and consumes the resulting k, converging on k = target (default 1.0).
  It uses bracketing false-position (regula falsi) with automatic bracket expansion,
  which only assumes k is monotonic in the parameter — true for the cases that matter
  (radius, enrichment, pitch near the critical point).
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
    x: float   # parameter value
    k: float   # resulting k-effective


class CriticalitySearch:
    """Stateful driver for a criticality search; the caller does the transport runs.

    Usage::

        s = CriticalitySearch(lo, hi, target=1.0)
        while (x := s.propose()) is not None:
            k = run_and_get_keff(x)
            s.submit(x, k)
        print(s.solution)

    The bracket ``[lo, hi]`` is evaluated first. If those two points already straddle
    the target, false position homes in on the root; otherwise the bracket is expanded
    outward (assuming monotonicity) until it does or until ``[x_min, x_max]`` / the
    evaluation budget is exhausted.
    """

    def __init__(
        self,
        lo: float,
        hi: float,
        *,
        target: float = 1.0,
        tol_k: float = 1.5e-3,
        tol_x: float | None = None,
        max_evals: int = 12,
        x_min: float | None = None,
        x_max: float | None = None,
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
        self.points: list[SearchPoint] = []
        self._failed = False  # ran out of room to bracket within bounds

    # ---- clamping ---------------------------------------------------------
    def _clamp(self, x: float) -> float:
        if self.x_min is not None:
            x = max(self.x_min, x)
        if self.x_max is not None:
            x = min(self.x_max, x)
        return x

    def _already_evaluated(self, x: float) -> bool:
        return any(abs(p.x - x) <= self.tol_x for p in self.points)

    # ---- stepping ---------------------------------------------------------
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

    def submit(self, x: float, k: float) -> None:
        self.points.append(SearchPoint(float(x), float(k)))

    def _next_guess(self) -> float | None:
        pts = sorted(self.points, key=lambda p: p.x)
        t = self.target

        # A sign change between adjacent points => bracketed; false position.
        for a, b in zip(pts, pts[1:]):
            da, db = a.k - t, b.k - t
            if da == 0:
                return None  # exact hit already recorded
            if da * db < 0:
                # regula falsi root of the linear interpolant between a and b
                x = a.x + da * (a.x - b.x) / (db - da)
                return self._clamp(x)

        # Not bracketed: expand outward in the direction that moves k toward target,
        # assuming monotonic k(x) (slope from the two extreme points).
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

    # ---- results ----------------------------------------------------------
    @property
    def converged(self) -> bool:
        if not self.points:
            return False
        if abs(self.points[-1].k - self.target) <= self.tol_k:
            return True
        # A tight bracket around the target also counts as converged.
        pts = sorted(self.points, key=lambda p: p.x)
        for a, b in zip(pts, pts[1:]):
            if (a.k - self.target) * (b.k - self.target) < 0 and (b.x - a.x) <= self.tol_x:
                return True
        return False

    def best(self) -> SearchPoint | None:
        """The evaluated point whose k is closest to the target."""
        if not self.points:
            return None
        return min(self.points, key=lambda p: abs(p.k - self.target))

    def estimate(self) -> float | None:
        """Best estimate of the critical parameter value.

        Uses the false-position root of the tightest straddling bracket when one
        exists (sub-grid accuracy), else the closest evaluated point.
        """
        if not self.points:
            return None
        pts = sorted(self.points, key=lambda p: p.x)
        t = self.target
        best_pair = None
        for a, b in zip(pts, pts[1:]):
            if (a.k - t) * (b.k - t) < 0:
                width = b.x - a.x
                if best_pair is None or width < best_pair[0]:
                    root = a.x + (a.k - t) * (a.x - b.x) / ((b.k - t) - (a.k - t))
                    best_pair = (width, root)
        if best_pair is not None:
            return best_pair[1]
        bp = self.best()
        return bp.x if bp else None

    @property
    def solution(self) -> dict:
        bp = self.best()
        return {
            "x": self.estimate(),
            "k": bp.k if bp else None,
            "target": self.target,
            "converged": self.converged,
            "bracketed": self.estimate() is not None and any(
                (a.k - self.target) * (b.k - self.target) < 0
                for a, b in zip(sorted(self.points, key=lambda p: p.x),
                                sorted(self.points, key=lambda p: p.x)[1:])
            ),
            "n_evals": len(self.points),
            "points": [(p.x, p.k) for p in self.points],
        }
