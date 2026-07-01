"""Reactivity and source-driven power from k-effective — the moderation-curve math.

A critical reactor's *absolute* power is operational, not geometric, so the honest
quantities along a moderation sweep are:

* **reactivity** ρ = (k−1)/k — how far from critical the configuration is; and
* **subcritical multiplication** M = 1/(1−k) — how much an external source is
  amplified. For a source-driven (subcritical) system the steady power scales with M,
  so M is a genuine *relative* power proxy. It diverges as k → 1 (critical) and has no
  steady value above it (self-sustaining — power set by control, not geometry).
"""

from __future__ import annotations


def reactivity_pcm(k: float | None) -> float | None:
    """Reactivity ρ = (k−1)/k in pcm (10⁵·ρ). None for non-physical k ≤ 0."""
    if k is None or k <= 0.0:
        return None
    return (k - 1.0) / k * 1.0e5


def subcritical_multiplication(k: float | None) -> float | None:
    """Source multiplication M = 1/(1−k) for a subcritical system (k < 1).

    None at or above critical, where a fixed source has no steady-state power.
    """
    if k is None or k >= 1.0:
        return None
    return 1.0 / (1.0 - k)
