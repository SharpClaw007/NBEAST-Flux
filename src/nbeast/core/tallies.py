"""Helpers to attach standard flux tallies to a model.

Two v1 result types: an energy **spectrum** (flux vs energy) and a spatial
**mesh** map (flux vs position). Both are read back by ``nbeast.core.results``.
"""

from __future__ import annotations

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
) -> openmc.RegularMesh:
    """Add a regular-mesh flux tally (name: 'flux_mesh'). Returns the mesh."""
    mesh = openmc.RegularMesh()
    mesh.dimension = dimension
    mesh.lower_left = lower_left
    mesh.upper_right = upper_right
    tally = openmc.Tally(name="flux_mesh")
    tally.filters = [openmc.MeshFilter(mesh)]
    tally.scores = ["flux"]
    _append(model, tally)
    return mesh
