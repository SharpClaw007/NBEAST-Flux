"""Generate few-group cross sections — the bridge from Monte Carlo to diffusion codes.

A continuous-energy Monte Carlo run can collapse its flux-weighted reaction rates
into a handful of energy groups, producing the group constants (total, absorption,
fission, ν-fission, χ) that deterministic diffusion/transport codes consume. This is
a classic reactor-physics teaching and research workflow: run a pin cell or assembly,
generate two- or few-group constants, feed them to a lattice/core code.

This wraps :mod:`openmc.mgxs`. The caller attaches the library's tallies to a model,
runs it, then loads the constants back from the statepoint. Group-wise values are
read with ``get_xs()`` (NumPy) rather than the pandas helper, which sidesteps a
pandas-version incompatibility in some OpenMC builds.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import openmc
import openmc.mgxs as mgxs

# Standard collapsing structures (group boundaries are well known to reactor physics).
GROUP_STRUCTURES = ("CASMO-2", "CASMO-4", "CASMO-8", "CASMO-16")

# Scalar (one-value-per-group) cross sections — a complete few-group set for a simple
# diffusion calculation. Scatter matrices are a natural future addition.
SCALAR_TYPES = ("total", "absorption", "fission", "nu-fission", "chi")


def build_library(
    model: openmc.model.Model,
    structure: str = "CASMO-2",
    domain_type: str = "material",
    mgxs_types=SCALAR_TYPES,
) -> mgxs.Library:
    """Build an :class:`openmc.mgxs.Library` and attach its tallies to ``model``.

    Returns the library object, which the caller must keep so it can later
    :meth:`load_from_statepoint` the run's results.
    """
    if structure not in mgxs.GROUP_STRUCTURES:
        raise ValueError(f"Unknown group structure: {structure!r}")
    library = mgxs.Library(model.geometry)
    library.energy_groups = mgxs.EnergyGroups(mgxs.GROUP_STRUCTURES[structure])
    library.mgxs_types = list(mgxs_types)
    library.domain_type = domain_type
    library.by_nuclide = False
    if domain_type == "material":
        library.domains = list(model.geometry.get_all_materials().values())
    else:
        library.domains = list(model.geometry.get_all_material_cells().values())
    library.build_library()
    if model.tallies is None:
        model.tallies = openmc.Tallies()
    library.add_to_tallies(model.tallies, merge=True)
    return library


def _domain_label(domain, domain_type: str) -> str:
    name = (getattr(domain, "name", "") or "").strip()
    return name if name else f"{domain_type} {domain.id}"


def _group_bounds(edges: list[float], n_groups: int):
    """(e_low, e_high) eV for each group; group 1 is the highest-energy group."""
    return [(edges[n_groups - g], edges[n_groups - g + 1]) for g in range(1, n_groups + 1)]


def load_constants(library: mgxs.Library, statepoint_path: str | Path) -> dict:
    """Load group constants from a finished run into a plain, exportable dict."""
    sp = openmc.StatePoint(str(statepoint_path))
    try:
        library.load_from_statepoint(sp)
        groups = library.energy_groups
        n_groups = int(groups.num_groups)
        edges = [float(e) for e in groups.group_edges]
        domains: dict[str, dict] = {}
        for domain in library.domains:
            label = _domain_label(domain, library.domain_type)
            per_type = {}
            for mt in library.mgxs_types:
                obj = library.get_mgxs(domain, mt)
                mean = np.asarray(obj.get_xs()).ravel()
                try:
                    std = np.asarray(obj.get_xs(value="std_dev")).ravel()
                except Exception:  # noqa: BLE001 — some types report no std
                    std = np.zeros_like(mean)
                per_type[mt] = {"mean": mean.tolist(), "std": std.tolist()}
            domains[label] = per_type
        return {
            "n_groups": n_groups,
            "group_edges_eV": edges,
            "group_bounds_eV": _group_bounds(edges, n_groups),
            "mgxs_types": list(library.mgxs_types),
            "domains": domains,
        }
    finally:
        sp.close()


def export_constants(table: dict, path: str | Path, fmt: str | None = None) -> Path:
    """Write group constants to CSV (long format) or HDF5."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = (fmt or path.suffix.lstrip(".")).lower()
    if fmt == "csv":
        _export_csv(table, path)
    elif fmt in ("h5", "hdf5"):
        _export_hdf5(table, path)
    else:
        raise ValueError(f"Unsupported format: {fmt!r} (use csv or h5)")
    return path


def _export_csv(table: dict, path: Path) -> None:
    import csv

    bounds = table["group_bounds_eV"]
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["domain", "mgxs_type", "group", "e_low_eV", "e_high_eV", "mean", "std"])
        for domain, per_type in table["domains"].items():
            for mt, vals in per_type.items():
                for g, (mean, std) in enumerate(zip(vals["mean"], vals["std"])):
                    lo, hi = bounds[g] if g < len(bounds) else ("", "")
                    writer.writerow([domain, mt, g + 1, lo, hi, mean, std])


def _export_hdf5(table: dict, path: Path) -> None:
    import h5py

    with h5py.File(path, "w") as f:
        f.attrs["format"] = "nbeast-mgxs-1"
        f.attrs["n_groups"] = table["n_groups"]
        f.create_dataset("group_edges_eV", data=np.asarray(table["group_edges_eV"], float))
        grp = f.create_group("domains")
        for domain, per_type in table["domains"].items():
            dg = grp.create_group(domain)
            for mt, vals in per_type.items():
                tg = dg.create_group(mt)
                tg.create_dataset("mean", data=np.asarray(vals["mean"], float))
                tg.create_dataset("std", data=np.asarray(vals["std"], float))
