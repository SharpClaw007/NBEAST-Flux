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

    keff: float | None
    keff_std: float | None
    n_inactive: int
    n_active: int
    entropy: np.ndarray | None = None          # Shannon entropy per generation
    flux_mean_rel_err: float | None = None      # over signal-carrying mesh cells
    flux_max_rel_err: float | None = None
    warnings: list[str] = field(default_factory=list)
    run_mode: str = "eigenvalue"

    @property
    def keff_pcm(self) -> float | None:
        """k-eff 1-sigma uncertainty in pcm (1e-5 Δk) — the reactor-physics unit."""
        return None if self.keff_std is None else self.keff_std * 1.0e5

    @property
    def ok(self) -> bool:
        return not self.warnings

    def summary_lines(self) -> list[str]:
        """Human-readable provenance/quality lines for the report + UI."""
        if self.keff is not None:
            lines = [
                f"k-effective = {self.keff:.5f} +/- {self.keff_std:.5f}  ({self.keff_pcm:.0f} pcm)",
                f"active / inactive batches = {self.n_active} / {self.n_inactive}",
            ]
        else:
            lines = [f"fixed-source run — {self.n_active} batches"]
        if self.flux_mean_rel_err is not None and self.flux_max_rel_err is not None:
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
        """Return (mean, std, rel_err) flat arrays for one mesh-tally score.

        Non-finite values are coerced to zero: some scores (notably ``heating`` for
        nuclides whose library lacks KERMA data — e.g. water cells) return NaN over
        part of the mesh, and NaN/Inf corrupt the VTK export and crash the renderer.
        """
        tally = self._sp.get_tally(name=name)
        mean = _finite(tally.get_values(scores=[score]).ravel())
        std = _finite(tally.get_values(scores=[score], value="std_dev").ravel())
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

    def field_to_vtk(
        self, path: str | Path, score: str = "flux",
        name: str = "flux_mesh", label: str | None = None, scale: float = 1.0,
    ) -> Path:
        """Write a mesh-tally score **and its relative error** to a VTK file (correct
        cell ordering) and return the path. The viewport selects either array by name
        (``<label>`` or ``<label>_rel_err``). ``name`` picks the tally (e.g.
        ``dose_mesh``); ``label`` overrides the array name (e.g. read ``flux`` from
        the dose tally but store it as ``dose``). ``scale`` multiplies the mean (used
        for power/unit normalization; the relative error is unaffected)."""
        tally = self._sp.get_tally(name=name)
        mesh = tally.find_filter(openmc.MeshFilter).mesh
        mean, _std, rel = self.field_values(score, name)
        if scale != 1.0:
            mean = mean * scale
        label = label or score
        path = Path(path)
        mesh.write_data_to_vtk(str(path), {label: mean, f"{label}_rel_err": rel})
        return path

    # ---- absolute (power-normalized) units -------------------------------
    # Field maps are per source neutron; multiplying by the source rate (and mesh
    # cell volume) converts them to absolute rates. The source rate follows from the
    # requested fission power and the total fission rate. Requires a fissile system;
    # returns a no-op factor (1.0) otherwise, keeping the maps honestly relative.
    _EV_TO_J = 1.602176634e-19
    _ABS_CONST = {
        "flux": 1.0, "fission": 1.0, "absorption": 1.0, "nu-fission": 1.0,
        "heating": _EV_TO_J,                       # eV·cm⁻³·s⁻¹ → W·cm⁻³
        "dose": 3600.0 * 1e-12,                    # pSv·s⁻¹ → Sv·h⁻¹
    }

    def source_rate(self, power_w: float):
        """Source neutrons/s that produce ``power_w`` of fission power (None if the
        system has no fission, or the run lacks the whole-geometry ``power_norm``
        tally). Uses recoverable fission energy (kappa-fission) over the WHOLE model,
        not the thin visualization slice — a slice under-counts fissions badly."""
        if power_w <= 0.0:
            return None
        energy_ev = self._kappa_fission_ev()
        if energy_ev is None:
            return None
        return power_w / (energy_ev * self._EV_TO_J)

    def _kappa_fission_ev(self):
        """Whole-geometry recoverable fission energy per source neutron (eV), or None."""
        try:
            tally = self._sp.get_tally(name="power_norm")
            energy = float(tally.get_values(scores=["kappa-fission"]).sum())
        except (LookupError, KeyError):
            return None
        return energy if energy > 0.0 else None

    def cell_volume(self, name: str = "flux_mesh") -> float:
        mesh = self._sp.get_tally(name=name).find_filter(openmc.MeshFilter).mesh
        vol = 1.0
        for lo, hi, n in zip(mesh.lower_left, mesh.upper_right, mesh.dimension):
            vol *= (float(hi) - float(lo)) / int(n)
        return vol

    def absolute_factor(self, score: str, source_rate: float | None,
                        name: str = "flux_mesh") -> float:
        """Factor to turn a per-source tally value into an absolute SI rate, given the
        absolute source rate [neutrons/s] (from a reactor power, or a fixed source's
        strength). ``source_rate`` None/0 → no-op (maps stay relative)."""
        if not source_rate or source_rate <= 0.0:
            return 1.0
        base = score[:-8] if score.endswith("_rel_err") else score
        return (source_rate / self.cell_volume(name)) * self._ABS_CONST.get(base, 1.0)

    def fission_power(self, source_rate: float | None):
        """Absolute fission power [W] for a source rate — the fixed-source *output*
        (S × recoverable fission energy). None if there's no fission."""
        if not source_rate or source_rate <= 0.0:
            return None
        energy_ev = self._kappa_fission_ev()
        if energy_ev is None:
            return None
        return source_rate * energy_ev * self._EV_TO_J

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

    # ---- raw data export -------------------------------------------------
    def mesh_arrays(self, name: str = "flux_mesh") -> dict:
        """Every score on a mesh tally as flat (mean, std, rel_err) arrays, plus the
        mesh geometry and per-cell centre coordinates — the basis for raw export.

        Arrays are in OpenMC mesh-cell order (x fastest, then y, then z), so the
        i-th element of every array refers to the same cell as ``centers[i]``.
        """
        tally = self._sp.get_tally(name=name)
        mesh = tally.find_filter(openmc.MeshFilter).mesh
        dimension = tuple(int(d) for d in mesh.dimension)
        lower = tuple(float(v) for v in mesh.lower_left)
        upper = tuple(float(v) for v in mesh.upper_right)
        data = {}
        for score in tally.scores:
            mean = _finite(tally.get_values(scores=[score]).ravel())
            std = _finite(tally.get_values(scores=[score], value="std_dev").ravel())
            rel = np.divide(std, mean, out=np.zeros_like(mean), where=mean > 0)
            data[score] = {"mean": mean, "std": std, "rel_err": rel}
        return {
            "scores": list(tally.scores),
            "dimension": dimension,
            "lower_left": lower,
            "upper_right": upper,
            "centers": cell_centers(dimension, lower, upper),
            "data": data,
        }

    def _spectrum_arrays(self):
        """(energy_edges, flux, flux_std) if a spectrum tally exists, else None."""
        try:
            spec = self.flux_spectrum()
        except Exception:  # noqa: BLE001 — no spectrum tally is fine
            return None
        return (
            np.asarray(spec.energy_edges, float),
            np.asarray(spec.flux, float),
            np.asarray(spec.flux_std, float),
        )

    def export_mesh_data(
        self,
        path: str | Path,
        fmt: str | None = None,
        name: str = "flux_mesh",
        include_spectrum: bool = True,
    ) -> Path:
        """Write mesh-tally arrays **with uncertainties** to NumPy / CSV / HDF5.

        ``fmt`` defaults to the file extension: ``.npz`` (NumPy), ``.csv``, or
        ``.h5``/``.hdf5``. NumPy and HDF5 also carry the flux energy spectrum when
        present; CSV is a single long table (one row per mesh cell).
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fmt = (fmt or path.suffix.lstrip(".")).lower()
        arrays = self.mesh_arrays(name)
        spectrum = self._spectrum_arrays() if include_spectrum else None

        if fmt in ("npz", "npy", "numpy"):
            _write_npz(path, arrays, spectrum)
        elif fmt == "csv":
            _write_csv(path, arrays)
        elif fmt in ("h5", "hdf5"):
            _write_hdf5(path, arrays, spectrum)
        else:
            raise ValueError(f"Unsupported raw-export format: {fmt!r} (use npz, csv, or h5)")
        return path

    # ---- convergence + trust ---------------------------------------------
    def entropy(self):
        """Shannon entropy of the fission source per generation, or None if not recorded.

        ``StatePoint.entropy`` raises (KeyError) rather than returning None when the
        run had no entropy mesh, so guard for it — keeps diagnostics working for
        fixed-source runs and any run without the diagnostic enabled.
        """
        try:
            ent = self._sp.entropy
        except (KeyError, AttributeError):
            return None
        if ent is None:
            return None
        ent = np.asarray(ent, dtype=float).ravel()
        return ent if ent.size else None

    @property
    def run_mode(self) -> str:
        return str(getattr(self._sp, "run_mode", "eigenvalue") or "eigenvalue")

    @property
    def n_inactive(self) -> int:
        return int(getattr(self._sp, "n_inactive", 0) or 0)

    def k_generation(self):
        """Per-generation k-effective (single estimator), or None — for replaying
        the convergence curve of a saved run loaded from its statepoint."""
        kg = getattr(self._sp, "k_generation", None)
        if kg is None:
            return None
        arr = np.asarray(kg, dtype=float).ravel()
        return arr if arr.size else None

    def diagnostics(self) -> Diagnostics:
        """Roll up uncertainties + source convergence into a trust check.

        For a fixed-source run there is no k-effective or fission-source convergence,
        so only the flux uncertainty is assessed.
        """
        fixed_source = self.run_mode == "fixed source"
        keff = keff_std = None
        if not fixed_source:
            k = self._sp.keff
            keff = float(k.nominal_value)
            keff_std = float(k.std_dev)
        n_inactive = self.n_inactive
        ent = self.entropy()

        n_active = 0
        if ent is not None:
            n_active = max(int(ent.size) - n_inactive, 0)
        elif fixed_source:
            n_active = int(getattr(self._sp, "n_batches", 0) or 0)

        mean_rel = max_rel = None
        try:
            mean_rel, max_rel = self.field_rel_err_summary("flux")
        except Exception:  # noqa: BLE001 — no mesh tally is fine
            pass

        if fixed_source:
            warnings = _fixed_source_warnings(mean_rel)
        else:
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
            run_mode=self.run_mode,
        )

    def close(self) -> None:
        self._sp.close()

    def __enter__(self) -> "Results":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _finite(arr: np.ndarray) -> np.ndarray:
    """Replace NaN/±Inf with 0.0 — keeps tally arrays safe for VTK and export."""
    return np.nan_to_num(np.asarray(arr, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)


def cell_centers(dimension, lower_left, upper_right) -> np.ndarray:
    """(N, 3) cell-centre coordinates in OpenMC mesh order (x fastest, then y, z)."""
    nx, ny, nz = (int(d) for d in dimension)
    lo = np.asarray(lower_left, float)
    hi = np.asarray(upper_right, float)
    width = (hi - lo) / np.array([nx, ny, nz], float)
    idx = np.arange(nx * ny * nz)
    i = idx % nx
    j = (idx // nx) % ny
    k = idx // (nx * ny)
    return np.column_stack([
        lo[0] + (i + 0.5) * width[0],
        lo[1] + (j + 0.5) * width[1],
        lo[2] + (k + 0.5) * width[2],
    ])


def _write_npz(path: Path, arrays: dict, spectrum) -> None:
    payload = {
        "dimension": np.asarray(arrays["dimension"]),
        "lower_left": np.asarray(arrays["lower_left"], float),
        "upper_right": np.asarray(arrays["upper_right"], float),
        "centers": arrays["centers"],
        "scores": np.asarray(arrays["scores"], dtype=object),
    }
    for score, d in arrays["data"].items():
        payload[f"{score}_mean"] = d["mean"]
        payload[f"{score}_std"] = d["std"]
        payload[f"{score}_rel_err"] = d["rel_err"]
    if spectrum is not None:
        edges, flux, std = spectrum
        payload["spectrum_energy_edges_eV"] = edges
        payload["spectrum_flux"] = flux
        payload["spectrum_flux_std"] = std
    np.savez(path, **payload)


def _write_csv(path: Path, arrays: dict) -> None:
    import csv

    scores = arrays["scores"]
    centers = arrays["centers"]
    dim = arrays["dimension"]
    with open(path, "w", newline="") as handle:
        handle.write(f"# NBEAST mesh tally export — order: x fastest, then y, then z\n")
        handle.write(f"# dimension = {tuple(dim)}\n")
        handle.write(f"# lower_left = {tuple(arrays['lower_left'])} cm\n")
        handle.write(f"# upper_right = {tuple(arrays['upper_right'])} cm\n")
        writer = csv.writer(handle)
        header = ["cell", "x_cm", "y_cm", "z_cm"]
        for s in scores:
            header += [f"{s}_mean", f"{s}_std", f"{s}_rel_err"]
        writer.writerow(header)
        for c in range(centers.shape[0]):
            row = [c, centers[c, 0], centers[c, 1], centers[c, 2]]
            for s in scores:
                d = arrays["data"][s]
                row += [d["mean"][c], d["std"][c], d["rel_err"][c]]
            writer.writerow(row)


def _write_hdf5(path: Path, arrays: dict, spectrum) -> None:
    import h5py

    with h5py.File(path, "w") as f:
        f.attrs["format"] = "nbeast-mesh-export-1"
        f.attrs["order"] = "x-fastest"
        mesh = f.create_group("mesh")
        mesh.attrs["dimension"] = np.asarray(arrays["dimension"])
        mesh.attrs["lower_left"] = np.asarray(arrays["lower_left"], float)
        mesh.attrs["upper_right"] = np.asarray(arrays["upper_right"], float)
        mesh.create_dataset("centers", data=arrays["centers"])
        scores = f.create_group("scores")
        for score, d in arrays["data"].items():
            g = scores.create_group(score)
            g.create_dataset("mean", data=d["mean"])
            g.create_dataset("std", data=d["std"])
            g.create_dataset("rel_err", data=d["rel_err"])
        if spectrum is not None:
            edges, flux, std = spectrum
            spec = f.create_group("spectrum")
            spec.create_dataset("energy_edges_eV", data=edges)
            spec.create_dataset("flux", data=flux)
            spec.create_dataset("flux_std", data=std)


# Heuristic thresholds — advisory, tuned for the teaching/benchmark regime.
_KEFF_PCM_WARN = 200.0     # k-eff 1-sigma above this (pcm) is statistically weak
_FLUX_RELERR_WARN = 0.20   # >20% mean rel. error => the flux map is mostly noise
_MIN_INACTIVE = 5          # fewer than this rarely converges the fission source


def _fixed_source_warnings(mean_rel: float | None) -> list[str]:
    """Trust checks for a fixed-source run: only the flux statistics apply."""
    out: list[str] = []
    if mean_rel is not None and mean_rel > _FLUX_RELERR_WARN:
        out.append(
            f"Flux/dose map is statistically noisy (mean relative error "
            f"{mean_rel * 100:.0f}%). Increase particles per batch or batches."
        )
    return out


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
