"""Read an OpenMC statepoint into plain, viz-ready data.

Exposes k-eff, the flux energy spectrum, and the flux mesh map (with a one-call
VTK export for the 3D viewport) — each now with its **statistical uncertainty**
(Monte Carlo results are estimates; a value without an error bar isn't a result).
Also reads the **Shannon entropy** of the fission source and rolls everything up
into :class:`Diagnostics`, a plain-language "can I trust this?" check.

Use as a context manager to close the HDF5 file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import openmc

# A flux mesh cell counts as "real" (carries signal) once its mean exceeds this
# fraction of the peak — used to ignore empty/void cells when summarising the
# relative error, so a sea of zero-flux cells doesn't dominate the statistics.
_SIGNAL_FRACTION = 1e-3


@dataclass
class Spectrum:
    energy_edges: np.ndarray  # eV, length n_groups + 1
    flux: np.ndarray          # length n_groups
    flux_std: np.ndarray      # 1-sigma absolute uncertainty per group

    @property
    def rel_err(self) -> np.ndarray:
        """Relative (fractional) uncertainty per group; 0 where flux is 0."""
        return np.divide(
            self.flux_std, self.flux, out=np.zeros_like(self.flux), where=self.flux > 0
        )


@dataclass
class Diagnostics:
    """A trust check for a finished run: uncertainties + source convergence.

    ``warnings`` is a list of plain-language cautions; an empty list means the
    run passed every heuristic check (``ok`` is True).
    """

    keff: float
    keff_std: float
    n_inactive: int
    n_active: int
    entropy: np.ndarray | None = None          # Shannon entropy per generation
    flux_mean_rel_err: float | None = None      # over signal-carrying mesh cells
    flux_max_rel_err: float | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def keff_pcm(self) -> float:
        """k-eff 1-sigma uncertainty in pcm (1e-5 Δk) — the reactor-physics unit."""
        return self.keff_std * 1.0e5

    @property
    def ok(self) -> bool:
        return not self.warnings

    def summary_lines(self) -> list[str]:
        """Human-readable provenance/quality lines for the report + UI."""
        lines = [
            f"k-effective = {self.keff:.5f} +/- {self.keff_std:.5f}  ({self.keff_pcm:.0f} pcm)",
            f"active / inactive batches = {self.n_active} / {self.n_inactive}",
        ]
        if self.flux_mean_rel_err is not None:
            lines.append(
                f"flux mesh rel. error = {self.flux_mean_rel_err * 100:.1f}% mean, "
                f"{self.flux_max_rel_err * 100:.1f}% max"
            )
        if self.entropy is not None and self.entropy.size:
            lines.append(f"Shannon entropy (final) = {float(self.entropy[-1]):.3f} bits")
        if self.warnings:
            lines.append("")
            lines.append("Cautions:")
            lines.extend(f"  - {w}" for w in self.warnings)
        else:
            lines.append("Convergence checks: passed.")
        return lines


class Results:
    def __init__(self, statepoint_path: str | Path):
        self._sp = openmc.StatePoint(str(statepoint_path))

    @property
    def keff(self):
        """Combined k-eff as an uncertainties ufloat (``.nominal_value`` / ``.std_dev``)."""
        return self._sp.keff

    def flux_spectrum(self) -> Spectrum:
        tally = self._sp.get_tally(name="flux_spectrum")
        energy_filter = tally.find_filter(openmc.EnergyFilter)
        flux = tally.get_values(scores=["flux"]).ravel()
        std = tally.get_values(scores=["flux"], value="std_dev").ravel()
        return Spectrum(np.asarray(energy_filter.values), flux, std)

    def mesh_scores(self) -> list[str]:
        """Scores available on the mesh tally (e.g. ['flux', 'fission'])."""
        return list(self._sp.get_tally(name="flux_mesh").scores)

    def field_values(self, score: str = "flux", name: str = "flux_mesh"):
        """Return (mean, std, rel_err) flat arrays for one mesh-tally score."""
        tally = self._sp.get_tally(name=name)
        mean = tally.get_values(scores=[score]).ravel()
        std = tally.get_values(scores=[score], value="std_dev").ravel()
        rel = np.divide(std, mean, out=np.zeros_like(mean), where=mean > 0)
        return mean, std, rel

    def field_rel_err_summary(self, score: str = "flux", name: str = "flux_mesh"):
        """(mean, max) relative error over signal-carrying cells; (None, None) if empty."""
        mean, _std, rel = self.field_values(score, name)
        if mean.size == 0 or mean.max() <= 0:
            return None, None
        signal = mean > _SIGNAL_FRACTION * mean.max()
        if not signal.any():
            return None, None
        return float(rel[signal].mean()), float(rel[signal].max())

    def field_to_vtk(self, path: str | Path, score: str = "flux") -> Path:
        """Write a mesh-tally score **and its relative error** to a VTK file (correct
        cell ordering) and return the path. The viewport selects either array by name
        (``<score>`` or ``<score>_rel_err``)."""
        tally = self._sp.get_tally(name="flux_mesh")
        mesh = tally.find_filter(openmc.MeshFilter).mesh
        mean, _std, rel = self.field_values(score)
        path = Path(path)
        mesh.write_data_to_vtk(str(path), {score: mean, f"{score}_rel_err": rel})
        return path

    def flux_mesh_to_vtk(self, path: str | Path) -> Path:
        return self.field_to_vtk(path, "flux")

    def flux_volume(self):
        """3D flux field for the volume render: (values, dims, lower_left, upper_right)."""
        tally = self._sp.get_tally(name="flux_volume")
        mesh = tally.find_filter(openmc.MeshFilter).mesh
        values = tally.get_values(scores=["flux"]).ravel()
        dims = tuple(int(d) for d in mesh.dimension)
        lower = tuple(float(v) for v in mesh.lower_left)
        upper = tuple(float(v) for v in mesh.upper_right)
        return values, dims, lower, upper

    # ---- convergence + trust ---------------------------------------------
    def entropy(self):
        """Shannon entropy of the fission source per generation, or None if not recorded."""
        ent = getattr(self._sp, "entropy", None)
        if ent is None:
            return None
        ent = np.asarray(ent, dtype=float).ravel()
        return ent if ent.size else None

    @property
    def n_inactive(self) -> int:
        return int(getattr(self._sp, "n_inactive", 0) or 0)

    def diagnostics(self) -> Diagnostics:
        """Roll up uncertainties + source convergence into a trust check."""
        k = self._sp.keff
        keff = float(k.nominal_value)
        keff_std = float(k.std_dev)
        n_inactive = self.n_inactive
        ent = self.entropy()

        n_active = 0
        if ent is not None:
            n_active = max(int(ent.size) - n_inactive, 0)

        mean_rel = max_rel = None
        try:
            mean_rel, max_rel = self.field_rel_err_summary("flux")
        except Exception:  # noqa: BLE001 — no mesh tally is fine
            pass

        warnings = _convergence_warnings(
            keff_std, ent, n_inactive, n_active, mean_rel, max_rel
        )
        return Diagnostics(
            keff=keff,
            keff_std=keff_std,
            n_inactive=n_inactive,
            n_active=n_active,
            entropy=ent,
            flux_mean_rel_err=mean_rel,
            flux_max_rel_err=max_rel,
            warnings=warnings,
        )

    def close(self) -> None:
        self._sp.close()

    def __enter__(self) -> "Results":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# Heuristic thresholds — advisory, tuned for the teaching/benchmark regime.
_KEFF_PCM_WARN = 200.0     # k-eff 1-sigma above this (pcm) is statistically weak
_FLUX_RELERR_WARN = 0.20   # >20% mean rel. error => the flux map is mostly noise
_MIN_INACTIVE = 5          # fewer than this rarely converges the fission source


def _convergence_warnings(
    keff_std: float,
    entropy: np.ndarray | None,
    n_inactive: int,
    n_active: int,
    mean_rel: float | None,
    max_rel: float | None,
) -> list[str]:
    """Plain-language cautions from simple, defensible heuristics."""
    out: list[str] = []

    if keff_std * 1e5 > _KEFF_PCM_WARN:
        out.append(
            f"k-eff uncertainty is high (+/-{keff_std * 1e5:.0f} pcm). "
            "Run more active batches or particles to tighten it."
        )

    if mean_rel is not None and mean_rel > _FLUX_RELERR_WARN:
        out.append(
            f"Flux map is statistically noisy (mean relative error "
            f"{mean_rel * 100:.0f}%). Increase particles per batch."
        )

    if n_inactive < _MIN_INACTIVE:
        out.append(
            f"Only {n_inactive} inactive batches — the fission source has little "
            "time to converge before tallying. Use at least 5–20."
        )

    # Shannon-entropy plateau test: if the source entropy is still systematically
    # rising through the *active* batches, tallying began before convergence.
    if entropy is not None and n_active >= 3:
        active = entropy[n_inactive:]
        if active.size >= 3:
            third = max(1, active.size // 3)
            first, last = active[:third], active[-third:]
            spread = float(active.std())
            rise = float(last.mean() - first.mean())
            if spread > 0 and rise > 2.0 * spread:
                out.append(
                    "Fission source may not be converged — the Shannon entropy is "
                    "still rising during the active batches. Increase inactive batches."
                )

    return out
