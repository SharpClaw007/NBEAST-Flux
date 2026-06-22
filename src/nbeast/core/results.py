"""Read an OpenMC statepoint into plain, viz-ready data.

Exposes k-eff, the flux energy spectrum, and the flux mesh map (with a one-call
VTK export for the 3D viewport). Use as a context manager to close the HDF5 file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import openmc


@dataclass
class Spectrum:
    energy_edges: np.ndarray  # eV, length n_groups + 1
    flux: np.ndarray          # length n_groups


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
        return Spectrum(np.asarray(energy_filter.values), flux)

    def flux_mesh_to_vtk(self, path: str | Path) -> Path:
        """Write the flux mesh tally to a VTK file (correct cell ordering) and
        return the path. Consumed by the pyvista viewport."""
        tally = self._sp.get_tally(name="flux_mesh")
        mesh = tally.find_filter(openmc.MeshFilter).mesh
        flux = tally.get_values(scores=["flux"]).ravel()
        path = Path(path)
        mesh.write_data_to_vtk(str(path), {"flux": flux})
        return path

    def close(self) -> None:
        self._sp.close()

    def __enter__(self) -> "Results":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
