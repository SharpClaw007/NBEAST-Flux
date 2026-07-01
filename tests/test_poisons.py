"""Equilibrium Xe-135 / Sm-149 poisoning (composition math — no cross-section data)."""

import math

from nbeast.core import materials, poisons


def test_equilibrium_ratios_saturation():
    xe, sm = poisons.equilibrium_ratios()
    # sanity: Xe/U235 ~1e-5, Sm/U235 ~1e-4 (order of magnitude fixes the worth)
    assert 5e-6 < xe < 5e-5
    assert 5e-5 < sm < 5e-4
    # Sm is flux-independent; Xe below saturation is smaller
    xe_lo, sm_lo = poisons.equilibrium_ratios(flux=1e13)
    assert xe_lo < xe
    assert math.isclose(sm_lo, sm)
    # very high flux → Xe approaches saturation
    xe_hi, _ = poisons.equilibrium_ratios(flux=1e18)
    assert math.isclose(xe_hi, xe, rel_tol=1e-3)


def test_add_to_fuel_places_poisons_at_target_ratio():
    fuel = materials.build("uo2", enrichment=3.2)
    xe, sm = poisons.equilibrium_ratios()
    poisoned = poisons.add_to_fuel(fuel, xe, sm)
    dens = poisoned.get_nuclide_atom_densities()
    assert "Xe135" in dens and "Sm149" in dens
    assert math.isclose(dens["Xe135"] / dens["U235"], xe, rel_tol=1e-3)
    assert math.isclose(dens["Sm149"] / dens["U235"], sm, rel_tol=1e-3)
    # keeps the thermal-scattering kernel + does not mutate the original
    assert "Xe135" not in fuel.get_nuclide_atom_densities()


def test_add_to_fuel_noop_without_u235():
    water = materials.build("water")
    assert poisons.add_to_fuel(water, 1e-5, 1e-4) is water


def test_poison_data_gated_on_bundle():
    # the curated H/O/U/Zr library does not carry Xe-135/Sm-149
    assert poisons.REQUIRED_NUCLIDES == ("Xe135", "Sm149")
    assert poisons.is_available(None) is False
