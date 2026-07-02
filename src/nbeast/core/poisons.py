"""Equilibrium fission-product poisoning — Xe-135 and Sm-149.

These two fission products dominate reactor poisoning: both have enormous *thermal*
absorption cross sections, build to an equilibrium, and cost reactivity. This module
computes their equilibrium concentrations (relative to the fuel's U-235) from the
standard chain constants, and adds them to a fuel material so a re-run reveals the
reactivity penalty.

It is a **thermal-spectrum, saturation approximation** — appropriate for LEU thermal
lattices (pin cell / assembly), and correctly ~negligible in fast systems. Xe-135 and
Sm-149 cross-section data are not in the bundled H/O/U/Zr library, so the feature is
gated on a download (like depletion).
"""

from __future__ import annotations

import openmc

# Thermal-U235 fission-product yields and chain constants.
GAMMA_I135 = 0.0639        # I-135 chain yield  → decays to Xe-135
GAMMA_XE135 = 0.00237      # direct Xe-135 yield
GAMMA_PM149 = 0.0113       # Pm-149 chain yield → decays to Sm-149
LAMBDA_XE = 2.106e-5       # Xe-135 decay constant [1/s] (t½ ≈ 9.14 h)
SIGMA_A_XE = 2.65e6        # Xe-135 thermal absorption [barn]
SIGMA_A_SM = 4.03e4        # Sm-149 thermal absorption [barn]
SIGMA_F_U235 = 585.0       # U-235 thermal fission [barn]

_BARN_TO_CM2 = 1.0e-24
REQUIRED_NUCLIDES = ("Xe135", "Sm149")


def equilibrium_ratios(
    flux: float | None = None,
    sigma_f_u235: float | None = None,
    sigma_a_xe: float | None = None,
    sigma_a_sm: float | None = None,
) -> tuple[float, float]:
    """Equilibrium (N_Xe/N_U235, N_Sm/N_U235) atom-density ratios.

    ``flux`` [n·cm⁻²·s⁻¹] sets the Xe-135 level; ``None`` uses the saturation
    (high-flux) limit — the maximum Xe worth. Sm-149 is flux-independent at
    equilibrium (it only burns out by absorption).

    The cross sections default to 2200 m/s (one-velocity) values, which over-predict Xe
    in a real lattice. Pass spectrum-averaged one-group cross sections (barns) — from
    :func:`spectrum_averaged_xs` on a clean run — to make the ratios spectrum-consistent.
    """
    gamma_xe = GAMMA_I135 + GAMMA_XE135
    sig_f = (sigma_f_u235 if sigma_f_u235 else SIGMA_F_U235) * _BARN_TO_CM2
    sig_a_xe = (sigma_a_xe if sigma_a_xe else SIGMA_A_XE) * _BARN_TO_CM2
    sig_a_sm = (sigma_a_sm if sigma_a_sm else SIGMA_A_SM) * _BARN_TO_CM2
    if flux is None or flux <= 0:
        xe = gamma_xe * sig_f / sig_a_xe                      # saturation
    else:
        xe = gamma_xe * sig_f * flux / (LAMBDA_XE + sig_a_xe * flux)
    sm = GAMMA_PM149 * sig_f / sig_a_sm
    return xe, sm


def spectrum_averaged_xs(energy_edges, flux, cross_sections,
                         temperature: str | None = None) -> dict:
    """Spectrum-averaged one-group cross sections (barns) for U-235 fission and
    Xe-135 / Sm-149 capture, folded from a clean run's flux spectrum:

        σ̄ = Σ_g σ(E_g)·φ_g / Σ_g φ_g

    Uses the flux spectrum a clean run already tallies + the pointwise data in the
    active library — no trace nuclides, no extra run. Returns {} if unavailable.
    Keys: ``sigma_f_u235``, ``sigma_a_xe``, ``sigma_a_sm``.
    """
    import numpy as np
    import openmc.data

    edges = np.asarray(energy_edges, dtype=float)
    phi = np.asarray(flux, dtype=float)
    if phi.size == 0 or phi.sum() <= 0 or edges.size != phi.size + 1:
        return {}
    e_mid = np.sqrt(np.maximum(edges[:-1] * edges[1:], 1e-12))   # log-midpoint (eV)

    try:
        library = openmc.data.DataLibrary.from_xml(cross_sections)
    except Exception:  # noqa: BLE001
        return {}

    def averaged(nuclide: str, mt: int):
        entry = library.get_by_material(nuclide, data_type="neutron")
        if entry is None:
            return None
        try:
            nd = openmc.data.IncidentNeutron.from_hdf5(entry["path"])
            temps = list(nd.temperatures)
            temp = temperature if temperature in temps else temps[0]
            sigma = nd[mt].xs[temp](e_mid)
        except Exception:  # noqa: BLE001 — missing reaction / temperature
            return None
        return float((sigma * phi).sum() / phi.sum())

    out = {
        "sigma_f_u235": averaged("U235", 18),    # MT 18 = fission
        "sigma_a_xe": averaged("Xe135", 102),    # MT 102 = radiative capture (dominant a)
        "sigma_a_sm": averaged("Sm149", 102),
    }
    return {k: v for k, v in out.items() if v is not None}


def add_to_fuel(fuel: openmc.Material, xe_ratio: float, sm_ratio: float) -> openmc.Material:
    """Return a copy of ``fuel`` with equilibrium Xe-135/Sm-149 added at the given
    ratios to its U-235. Returns the fuel unchanged if it has no U-235 (nothing to
    poison, e.g. a fast metal without the thermal chain)."""
    densities = fuel.get_nuclide_atom_densities()   # {nuclide: atom/b-cm}
    n_u235 = float(densities.get("U235", 0.0))
    if n_u235 <= 0.0:
        return fuel
    n_xe = max(xe_ratio, 0.0) * n_u235
    n_sm = max(sm_ratio, 0.0) * n_u235

    poisoned = openmc.Material(name=f"{fuel.name} (+Xe/Sm)")
    for nuclide, dens in densities.items():
        poisoned.add_nuclide(nuclide, float(dens))
    if n_xe > 0:
        poisoned.add_nuclide("Xe135", n_xe)
    if n_sm > 0:
        poisoned.add_nuclide("Sm149", n_sm)
    poisoned.set_density("atom/b-cm", sum(float(d) for d in densities.values()) + n_xe + n_sm)
    for entry in getattr(fuel, "_sab", []):
        poisoned.add_s_alpha_beta(entry[0] if isinstance(entry, tuple) else entry)
    if fuel.temperature is not None:
        poisoned.temperature = fuel.temperature
    return poisoned


def is_available(cross_sections: str | None) -> bool:
    """True when the active library carries the poison nuclides."""
    from . import materials

    return set(REQUIRED_NUCLIDES) <= materials.available_names(cross_sections)
