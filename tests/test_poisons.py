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


def test_equilibrium_ratios_accepts_spectrum_averaged_xs():
    """Spectrum-averaged σ overrides feed straight into the equilibrium ratios, replacing
    the mismatched 2200 m/s pair with a spectrum-consistent σ_f(U235)/σ_a set. Check the
    plumbing against the closed form: saturation Xe ∝ σ_f/σ_a, Sm ∝ σ_f/σ_a(Sm)."""
    xe_default, sm_default = poisons.equilibrium_ratios()
    # saturation Xe ∝ 1/σ_a(Xe): halving σ_a(Xe) doubles the equilibrium ratio
    xe_soft, _ = poisons.equilibrium_ratios(sigma_a_xe=poisons.SIGMA_A_XE / 2)
    assert math.isclose(xe_soft, xe_default * 2, rel_tol=1e-6)
    # both ratios ∝ σ_f(U235): doubling it doubles both
    xe_hi, sm_hi = poisons.equilibrium_ratios(sigma_f_u235=poisons.SIGMA_F_U235 * 2)
    assert math.isclose(xe_hi, xe_default * 2, rel_tol=1e-6)
    assert math.isclose(sm_hi, sm_default * 2, rel_tol=1e-6)


def test_spectrum_averaged_xs_handles_missing_gracefully():
    # bad/empty spectrum or no data → empty dict, never raises
    assert poisons.spectrum_averaged_xs([], [], None) == {}
    assert poisons.spectrum_averaged_xs([1.0, 2.0], [0.0], "nonexistent.xml") == {}


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
