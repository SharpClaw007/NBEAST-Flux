"""Compare two runs — the fundamental research motion: "case A vs case B".

Given two results (typically two :class:`~nbeast.core.project.RunRecord`s from the
run history), this reports the change in k-effective *with its combined statistical
uncertainty* — so the user can tell a real reactivity effect from Monte Carlo noise —
and a parameter-by-parameter diff of what was actually changed between the cases.

Pure and dependency-light (numbers + dicts only) so it is trivially testable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class KeffDelta:
    delta: float            # k_b - k_a
    sigma: float            # combined 1-sigma uncertainty on the delta
    n_sigma: float          # |delta| / sigma  (statistical significance)
    significant: bool       # |delta| > 2 sigma (a real effect, not MC noise)

    @property
    def delta_pcm(self) -> float:
        return self.delta * 1.0e5

    @property
    def sigma_pcm(self) -> float:
        return self.sigma * 1.0e5

    def summary(self) -> str:
        verdict = "significant" if self.significant else "within noise"
        return (
            f"Δk = {self.delta_pcm:+.0f} ± {self.sigma_pcm:.0f} pcm "
            f"({self.n_sigma:.1f}σ, {verdict})"
        )


def keff_delta(
    keff_a: float, std_a: float | None, keff_b: float, std_b: float | None
) -> KeffDelta:
    """Reactivity change B−A and whether it exceeds Monte Carlo noise.

    Uncertainties add in quadrature; the two runs are assumed statistically
    independent (different seeds or independent samples — which they are here).
    """
    sa = float(std_a or 0.0)
    sb = float(std_b or 0.0)
    delta = float(keff_b) - float(keff_a)
    sigma = math.sqrt(sa * sa + sb * sb)
    n_sigma = abs(delta) / sigma if sigma > 0 else math.inf
    return KeffDelta(delta=delta, sigma=sigma, n_sigma=n_sigma, significant=n_sigma > 2.0)


@dataclass(frozen=True)
class ParamRow:
    key: str
    a: object
    b: object
    changed: bool


def param_diff(params_a: dict, params_b: dict) -> list[ParamRow]:
    """Aligned parameter diff over the union of keys (sorted, changed-first)."""
    keys = sorted(set(params_a) | set(params_b))
    rows = []
    for k in keys:
        va, vb = params_a.get(k), params_b.get(k)
        rows.append(ParamRow(key=k, a=va, b=vb, changed=not _equalish(va, vb)))
    rows.sort(key=lambda r: (not r.changed, r.key))  # changed parameters first
    return rows


def _equalish(a, b) -> bool:
    if a is None or b is None:
        return a is b
    try:
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-12)
    except (TypeError, ValueError):
        return a == b


def compare(record_a, record_b) -> dict:
    """Compare two objects exposing ``keff``, ``keff_std``, ``parameters`` (and
    optionally ``title()``). Returns a dict ready for a comparison view."""
    delta = keff_delta(
        getattr(record_a, "keff", None) or 0.0, getattr(record_a, "keff_std", None),
        getattr(record_b, "keff", None) or 0.0, getattr(record_b, "keff_std", None),
    )
    return {
        "label_a": _label(record_a, "A"),
        "label_b": _label(record_b, "B"),
        "keff_a": getattr(record_a, "keff", None),
        "keff_b": getattr(record_b, "keff", None),
        "delta": delta,
        "params": param_diff(
            getattr(record_a, "parameters", {}) or {},
            getattr(record_b, "parameters", {}) or {},
        ),
    }


def _label(record, fallback: str) -> str:
    title = getattr(record, "title", None)
    if callable(title):
        try:
            return title()
        except Exception:  # noqa: BLE001
            pass
    return str(getattr(record, "id", fallback))
