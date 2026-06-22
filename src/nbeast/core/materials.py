"""Preset material library for NBEAST v1 (criticality).

Each preset returns a fresh ``openmc.Material``. Keeping these as small factory
functions (rather than module-level singletons) means callers can freely tweak
density/temperature without mutating shared state, and the GUI can introspect
``PRESETS`` to populate its material picker.
"""

from __future__ import annotations

import openmc


def uo2(enrichment: float = 3.2, density: float = 10.4) -> openmc.Material:
    """Uranium dioxide fuel at the given U-235 enrichment (wt%)."""
    m = openmc.Material(name=f"UO2 ({enrichment:g}% enr.)")
    m.add_element("U", 1.0, enrichment=enrichment)
    m.add_element("O", 2.0)
    m.set_density("g/cm3", density)
    return m


def water(density: float = 1.0, with_sab: bool = True) -> openmc.Material:
    """Light-water moderator. Includes the H-in-H2O thermal-scattering kernel,
    which is mandatory for accurate thermal-reactor results."""
    m = openmc.Material(name="Water")
    m.add_element("H", 2.0)
    m.add_element("O", 1.0)
    m.set_density("g/cm3", density)
    if with_sab:
        m.add_s_alpha_beta("c_H_in_H2O")
    return m


def zircaloy(density: float = 6.55) -> openmc.Material:
    """Zirconium cladding (approximated as pure Zr for v1)."""
    m = openmc.Material(name="Zircaloy")
    m.add_element("Zr", 1.0)
    m.set_density("g/cm3", density)
    return m


def heu_metal_godiva() -> openmc.Material:
    """Highly enriched uranium metal — Godiva (ICSBEP HEU-MET-FAST-001).

    Atom densities (atoms/b-cm) from the benchmark specification; used as the
    validated fast-criticality reference (bare sphere, k_eff ~= 1.0).
    """
    n_u234 = 4.9184e-4
    n_u235 = 4.4994e-2
    n_u238 = 2.4984e-3
    m = openmc.Material(name="HEU metal (Godiva)")
    m.add_nuclide("U234", n_u234)
    m.add_nuclide("U235", n_u235)
    m.add_nuclide("U238", n_u238)
    m.set_density("atom/b-cm", n_u234 + n_u235 + n_u238)
    return m


# Registry the GUI can enumerate. Maps a stable key -> (label, factory).
PRESETS = {
    "uo2": ("UO₂ fuel", uo2),
    "water": ("Light water", water),
    "zircaloy": ("Zircaloy cladding", zircaloy),
    "heu_metal_godiva": ("HEU metal (Godiva)", heu_metal_godiva),
}
