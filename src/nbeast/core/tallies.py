"""Helpers to attach standard flux tallies to a model.

Two v1 result types: an energy **spectrum** (flux vs energy) and a spatial
**mesh** map (flux vs position). Both are read back by ``nbeast.core.results``.
"""

from __future__ import annotations

import math

import numpy as np
import openmc


def _log_energy_grid(n_groups: int, e_min: float = 1e-5, e_max: float = 2.0e7) -> np.ndarray:
    """Log-spaced energy bin edges in eV (thermal to fast)."""
    return np.logspace(np.log10(e_min), np.log10(e_max), n_groups + 1)


def _append(model: openmc.model.Model, tally: openmc.Tally) -> None:
    if model.tallies is None:
        model.tallies = openmc.Tallies()
    model.tallies.append(tally)


def add_flux_spectrum(model: openmc.model.Model, n_groups: int = 100) -> openmc.Tally:
    """Add a log-energy flux spectrum tally (name: 'flux_spectrum')."""
    tally = openmc.Tally(name="flux_spectrum")
    tally.filters = [openmc.EnergyFilter(_log_energy_grid(n_groups))]
    tally.scores = ["flux"]
    _append(model, tally)
    return tally


def add_flux_mesh(
    model: openmc.model.Model,
    dimension: tuple[int, int, int],
    lower_left: tuple[float, float, float],
    upper_right: tuple[float, float, float],
    scores: tuple[str, ...] = ("flux",),
    name: str = "flux_mesh",
) -> openmc.RegularMesh:
    """Add a regular-mesh tally over the given scores. Returns the mesh."""
    mesh = openmc.RegularMesh()
    mesh.dimension = dimension
    mesh.lower_left = lower_left
    mesh.upper_right = upper_right
    tally = openmc.Tally(name=name)
    tally.filters = [openmc.MeshFilter(mesh)]
    tally.scores = list(scores)
    _append(model, tally)
    return mesh


def add_flux_volume_mesh(model: openmc.model.Model, n: int = 30) -> openmc.RegularMesh:
    """Add a 3D flux mesh (name: 'flux_volume') over the geometry bounding box for the
    publication volume render. Infinite axes collapse to a finite slab."""
    bbox = model.geometry.bounding_box
    lower, upper = bbox.lower_left, bbox.upper_right

    def finite(lo: float, hi: float, default: float = 1.0) -> tuple[float, float]:
        lo = lo if math.isfinite(lo) else -default
        hi = hi if math.isfinite(hi) else default
        return lo, hi

    x0, x1 = finite(float(lower[0]), float(upper[0]))
    y0, y1 = finite(float(lower[1]), float(upper[1]))
    z0, z1 = finite(float(lower[2]), float(upper[2]))
    return add_flux_mesh(
        model, (n, n, n), (x0, y0, z0), (x1, y1, z1), scores=("flux",), name="flux_volume"
    )


def add_entropy_mesh(model: openmc.model.Model, n: int = 8) -> openmc.RegularMesh:
    """Enable the Shannon-entropy diagnostic by attaching an entropy mesh.

    OpenMC then records the Shannon entropy of the fission source each generation
    (written to the statepoint) — the standard check that the source has converged
    before active batches begin. The mesh is sized to the geometry bounding box;
    axes that are infinite (e.g. the unbounded z of a 2D pin cell) collapse to a
    single bin so the entropy reflects the spatial degrees of freedom that matter.
    """
    bbox = model.geometry.bounding_box
    lower, upper = bbox.lower_left, bbox.upper_right

    def axis(lo: float, hi: float, default: float = 1.0) -> tuple[float, float, int]:
        finite = math.isfinite(lo) and math.isfinite(hi)
        lo = lo if math.isfinite(lo) else -default
        hi = hi if math.isfinite(hi) else default
        return lo, hi, (n if finite else 1)

    x0, x1, nx = axis(float(lower[0]), float(upper[0]))
    y0, y1, ny = axis(float(lower[1]), float(upper[1]))
    z0, z1, nz = axis(float(lower[2]), float(upper[2]))

    mesh = openmc.RegularMesh()
    mesh.dimension = (nx, ny, nz)
    mesh.lower_left = (x0, y0, z0)
    mesh.upper_right = (x1, y1, z1)
    model.settings.entropy_mesh = mesh
    return mesh


# Reaction-rate + energy-deposition scores carried on the spatial slice mesh, so the
# Results panel can map each one. All are available from the standard data (no extra
# library): 'heating' is the KERMA energy-deposition score.
SLICE_SCORES = ("flux", "fission", "absorption", "nu-fission", "heating")


def add_flux_slice_mesh(
    model: openmc.model.Model, n: int = 40, z_half: float = 1.0
) -> openmc.RegularMesh:
    """Add an n×n mesh on a central z-slice, sized to the model's geometry, carrying
    flux + reaction-rate + heating maps.

    Bounds come from the geometry bounding box; infinite axes (e.g. the
    unbounded z of a 2D pin cell) collapse to a thin slab so the result is a
    clean 2D map regardless of template.
    """
    bbox = model.geometry.bounding_box
    lower, upper = bbox.lower_left, bbox.upper_right

    def finite(lo: float, hi: float, default: float) -> tuple[float, float]:
        lo = lo if math.isfinite(lo) else -default
        hi = hi if math.isfinite(hi) else default
        return lo, hi

    x0, x1 = finite(float(lower[0]), float(upper[0]), 1.0)
    y0, y1 = finite(float(lower[1]), float(upper[1]), 1.0)
    return add_flux_mesh(
        model, (n, n, 1), (x0, y0, -z_half), (x1, y1, z_half), scores=SLICE_SCORES
    )


def add_dose_mesh(
    model: openmc.model.Model,
    n: int = 40,
    particle: str = "neutron",
    geometry: str = "AP",
    z_half: float = 1.0,
    name: str = "dose_mesh",
) -> openmc.RegularMesh:
    """Add a flux-to-dose-rate mesh (ICRP-116 ambient-dose coefficients).

    An :class:`openmc.EnergyFunctionFilter` weights the flux by the energy-dependent
    dose conversion factor, so the tally reports dose rate per source particle —
    the headline result for shielding studies. ``geometry`` is the ICRP irradiation
    geometry (``AP`` = antero-posterior, the conservative default).
    """
    bbox = model.geometry.bounding_box
    lower, upper = bbox.lower_left, bbox.upper_right

    def finite(lo: float, hi: float, default: float) -> tuple[float, float]:
        lo = lo if math.isfinite(lo) else -default
        hi = hi if math.isfinite(hi) else default
        return lo, hi

    x0, x1 = finite(float(lower[0]), float(upper[0]), 1.0)
    y0, y1 = finite(float(lower[1]), float(upper[1]), 1.0)
    mesh = openmc.RegularMesh()
    mesh.dimension = (n, n, 1)
    mesh.lower_left = (x0, y0, -z_half)
    mesh.upper_right = (x1, y1, z_half)

    energies, coeffs = openmc.data.dose_coefficients(particle, geometry)
    tally = openmc.Tally(name=name)
    tally.filters = [openmc.MeshFilter(mesh), openmc.EnergyFunctionFilter(energies, coeffs)]
    tally.scores = ["flux"]
    _append(model, tally)
    return mesh
