"""Display unit system: SI/US conversions + honest colorbar labels, plus physics
anchors for the *absolute* normalization (energy conservation + a dose hand-calc).
The anchors run real OpenMC and skip without a cross-section library."""

import math
import os
import pathlib

import pytest

from nbeast.core import units

_XS = os.environ.get("OPENMC_CROSS_SECTIONS")
requires_data = pytest.mark.skipif(
    not (_XS and pathlib.Path(_XS).exists()),
    reason="OPENMC_CROSS_SECTIONS not set or missing",
)


def test_length_conversions_roundtrip():
    assert units.length_unit("SI") == "cm"
    assert units.length_unit("US") == "in"
    assert math.isclose(units.cm_to_display(2.54, "US"), 1.0)
    assert math.isclose(units.cm_to_display(1.26, "SI"), 1.26)
    assert math.isclose(units.display_to_cm(1.0, "US"), 2.54)
    # round-trip
    assert math.isclose(units.display_to_cm(units.cm_to_display(3.7, "US"), "US"), 3.7)
    assert units.is_length("cm") and not units.is_length("wt%") and not units.is_length("K")


def test_colorbar_titles_are_honest():
    # relative by default — never claim absolute units
    assert units.colorbar_title("flux", "SI", absolute=False) == "Scalar flux\n(relative · per source n)"
    assert units.colorbar_title("flux", "US", absolute=False) == "Scalar flux\n(relative · per source n)"
    # absolute units convert with the system
    assert units.colorbar_title("flux", "SI", absolute=True) == "Scalar flux\n(n·cm⁻²·s⁻¹)"
    assert units.colorbar_title("flux", "US", absolute=True) == "Scalar flux\n(n·in⁻²·s⁻¹)"
    assert units.colorbar_title("dose", "US", absolute=True) == "Neutron dose rate\n(rem·h⁻¹)"
    # relative error is dimensionless in both systems
    assert units.colorbar_title("flux_rel_err", "US", absolute=True) == "Scalar flux\n(relative error)"


def test_field_factors():
    # no conversion unless absolute AND US
    assert units.field_factor("flux", "SI", absolute=True) == 1.0
    assert units.field_factor("flux", "US", absolute=False) == 1.0
    # area/volume scale by inch powers; dose Sv->rem is ×100
    assert math.isclose(units.field_factor("flux", "US", absolute=True), units.CM_PER_INCH ** 2)
    assert math.isclose(units.field_factor("fission", "US", absolute=True), units.CM_PER_INCH ** 3)
    assert math.isclose(units.field_factor("dose", "US", absolute=True), 100.0)
    assert units.field_factor("flux_rel_err", "US", absolute=True) == 1.0


# ---- physics anchors for the absolute-unit normalization -------------------
@requires_data
def test_energy_conservation_heating_vs_kappa(tmp_path, monkeypatch):
    """The absolute-unit chain rests on kappa-fission (recoverable fission energy). As an
    independent energy-conservation check, the whole-geometry KERMA 'heating' score must
    integrate to ~the same total. On Godiva (all-U, so KERMA data exists for every cell —
    unlike water, which has none) heating/kappa ≈ 0.91: KERMA with photon transport OFF
    deposits neutron + local photon energy, ~9% short of kappa-fission's full Q-value
    (the un-transported photon energy). This bounds the local-deposition assumption."""
    import openmc

    from nbeast.core import benchmarks, tallies

    monkeypatch.chdir(tmp_path)
    m = benchmarks.godiva(batches=60, inactive=15, particles=3000, seed=1)
    tallies.add_power_norm(m)                      # kappa-fission (eV/source)
    heat = openmc.Tally(name="heat_total")
    heat.scores = ["heating"]                      # KERMA (eV/source), whole geometry
    m.tallies.append(heat)
    with openmc.StatePoint(m.run(output=False)) as sp:
        kappa = float(sp.get_tally(name="power_norm").get_values(scores=["kappa-fission"]).sum())
        deposited = float(sp.get_tally(name="heat_total").get_values(scores=["heating"]).sum())

    assert 0.85 < deposited / kappa < 1.02, f"heating/kappa = {deposited / kappa:.4f}"


@requires_data
def test_dose_tally_equals_icrp_coefficient(tmp_path, monkeypatch):
    """Dose hand-calc anchor: in a near-void, a monoenergetic beam stays at its source
    energy, so the dose tally / flux tally must equal the ICRP-116 fluence-to-dose
    coefficient at that energy. Validates both the dose normalization and the log-log
    EnergyFunctionFilter (at a tabulated grid point, log-log returns the exact value)."""
    import numpy as np
    import openmc

    monkeypatch.chdir(tmp_path)
    energy = 1.0e6  # 1 MeV, a tabulated ICRP grid point
    mat = openmc.Material()
    mat.add_nuclide("H1", 1.0)
    mat.set_density("g/cm3", 1e-8)                 # near-void: negligible scattering
    sphere = openmc.Sphere(r=20.0, boundary_type="vacuum")
    geom = openmc.Geometry([openmc.Cell(fill=mat, region=-sphere)])
    settings = openmc.Settings()
    settings.run_mode = "fixed source"
    settings.batches, settings.particles = 20, 20000
    settings.source = openmc.IndependentSource(energy=openmc.stats.Discrete([energy], [1.0]))

    energies, coeffs = openmc.data.dose_coefficients("neutron", "AP")
    dose_filter = openmc.EnergyFunctionFilter(energies, coeffs)
    dose_filter.interpolation = "log-log"
    flux_t = openmc.Tally(name="flux")
    flux_t.scores = ["flux"]
    dose_t = openmc.Tally(name="dose")
    dose_t.filters = [dose_filter]
    dose_t.scores = ["flux"]
    model = openmc.Model(geom, openmc.Materials([mat]), settings,
                         openmc.Tallies([flux_t, dose_t]))
    with openmc.StatePoint(model.run(output=False)) as sp:
        flux = float(sp.get_tally(name="flux").get_values(scores=["flux"]).sum())
        dose = float(sp.get_tally(name="dose").get_values(scores=["flux"]).sum())

    expected = float(np.exp(np.interp(np.log(energy), np.log(energies), np.log(coeffs))))
    assert math.isclose(dose / flux, expected, rel_tol=0.01), (
        f"dose/flux = {dose / flux:.4f} vs ICRP coeff {expected:.4f} pSv·cm²")
