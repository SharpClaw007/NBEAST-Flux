"""Validated reference cases — they triple as starter examples, tutorials, and
regression tests. Each returns a runnable ``openmc.model.Model``.
"""

from __future__ import annotations

import openmc

from . import templates

# Godiva critical radius (ICSBEP HEU-MET-FAST-001), cm.
GODIVA_RADIUS = 8.7407

# Expected k-eff for the built-in benchmarks (for tests / UI "known-good" badges).
EXPECTED_KEFF = {
    "godiva": 1.0,
}


def godiva(radius: float = GODIVA_RADIUS, material: str = "heu_metal_godiva",
           **kwargs) -> openmc.model.Model:
    """Bare HEU metal sphere; k_eff ~= 1.0 at the benchmark radius. The
    fast-criticality trust anchor (radius and material are adjustable for studies)."""
    return templates.bare_sphere(material, radius=radius, **kwargs)


def pincell(**kwargs) -> openmc.model.Model:
    """PWR UO2/water pin cell; k_inf ~= 1.41 at 3.2% enrichment."""
    return templates.pin_cell(**kwargs)


def assembly(**kwargs) -> openmc.model.Model:
    """N×N PWR fuel assembly (reflective); k_inf ~= the pin-cell value."""
    return templates.assembly(**kwargs)
