"""Tier-4 physics breadth: temperature/Doppler, fixed-source/shielding, richer
tallies, multigroup XS, and the depletion gate.

Data-free tests check structure; ``@requires_data`` tests run real OpenMC and are
skipped without a cross-section library. Live depletion needs a chain file too, so
it is exercised separately (see the manual validation) and only gated logic is
tested here.
"""

import json
import os
import pathlib

import pytest

_XS = os.environ.get("OPENMC_CROSS_SECTIONS")
requires_data = pytest.mark.skipif(
    not (_XS and pathlib.Path(_XS).exists()),
    reason="OPENMC_CROSS_SECTIONS not set or missing",
)


# ---- temperature / Doppler (data-free) ------------------------------------
def test_temperature_sets_settings():
    from nbeast.core import templates

    m = templates.pin_cell(temperature=900.0)
    assert m.settings.temperature["default"] == 900.0
    assert m.settings.temperature["method"] == "nearest"
    # None leaves the data default untouched
    assert templates.pin_cell().settings.temperature in (None, {})


def test_temperature_is_a_template_parameter():
    from nbeast.core import specs

    for label in ("Pin cell", "Godiva", "Fuel assembly"):
        keys = [p.key for p in specs.SPECS[label].parameters]
        assert "temperature" in keys


# ---- fixed-source / shielding (data-free) ---------------------------------
def test_shield_template_is_fixed_source():
    from nbeast.core import specs

    spec = specs.SPECS["Shield slab"]
    assert spec.run_mode == "fixed source"
    model = spec.build(thickness=25.0, source_energy=2.0)
    assert model.settings.run_mode == "fixed source"
    assert model.settings.inactive in (None, 0)


def test_run_meta_records_mode(tmp_path):
    from nbeast.core import templates
    from nbeast.core.runner import _write_run_meta

    _write_run_meta(templates.shield_slab(), tmp_path)
    assert json.loads((tmp_path / "run_meta.json").read_text())["run_mode"] == "fixed source"
    _write_run_meta(templates.pin_cell(), tmp_path)
    assert json.loads((tmp_path / "run_meta.json").read_text())["run_mode"] == "eigenvalue"


def test_worker_reads_run_mode(tmp_path, monkeypatch):
    from nbeast.core.worker import _read_run_mode

    monkeypatch.chdir(tmp_path)
    assert _read_run_mode() == "eigenvalue"  # no file -> default
    (tmp_path / "run_meta.json").write_text('{"run_mode": "fixed source"}')
    assert _read_run_mode() == "fixed source"


def test_fixed_source_diagnostics_render():
    from nbeast.core.results import Diagnostics, _fixed_source_warnings

    diag = Diagnostics(keff=None, keff_std=None, n_inactive=0, n_active=20,
                       flux_mean_rel_err=0.05, run_mode="fixed source")
    assert diag.keff_pcm is None
    lines = diag.summary_lines()
    assert any("fixed-source" in ln for ln in lines)
    assert _fixed_source_warnings(0.5)  # noisy flux warns
    assert _fixed_source_warnings(0.02) == []


# ---- richer tallies (data-free structure) ---------------------------------
def test_slice_mesh_carries_reaction_and_heating_scores():
    from nbeast.core import tallies, templates

    m = templates.pin_cell()
    tallies.add_flux_slice_mesh(m, n=10)
    mesh_tally = [t for t in m.tallies if t.name == "flux_mesh"][0]
    for score in ("flux", "fission", "absorption", "nu-fission", "heating"):
        assert score in mesh_tally.scores


def test_finite_coerces_nonfinite():
    import numpy as np

    from nbeast.core.results import _finite

    out = _finite(np.array([1.0, np.nan, np.inf, -np.inf, 2.0]))
    assert np.isfinite(out).all()
    assert list(out) == [1.0, 0.0, 0.0, 0.0, 2.0]


def test_dose_mesh_has_energy_function_filter():
    import openmc

    from nbeast.core import tallies, templates

    m = templates.pin_cell()
    tallies.add_dose_mesh(m, n=10)
    dose = [t for t in m.tallies if t.name == "dose_mesh"][0]
    assert any(isinstance(f, openmc.EnergyFunctionFilter) for f in dose.filters)


# ---- multigroup XS (data-free) --------------------------------------------
def test_mgxs_group_bounds():
    from nbeast.core.mgxs_gen import _group_bounds

    # ascending edges; group 1 is the highest-energy band
    bounds = _group_bounds([0.0, 0.625, 2.0e7], 2)
    assert bounds[0] == (0.625, 2.0e7)
    assert bounds[1] == (0.0, 0.625)


# ---- depletion gate (data-free) -------------------------------------------
def test_depletion_unavailable_without_chain(monkeypatch):
    from nbeast.core import depletion

    monkeypatch.delenv("OPENMC_DEPLETION_CHAIN", raising=False)
    monkeypatch.setattr(depletion, "chain_path", lambda: None)
    assert depletion.is_available() is False


def test_depletion_available_with_chain(tmp_path, monkeypatch):
    from nbeast.core import depletion

    chain = tmp_path / "chain.xml"
    chain.write_text("<depletion_chain/>")
    monkeypatch.setenv("OPENMC_DEPLETION_CHAIN", str(chain))
    monkeypatch.setattr("openmc.config", {})  # no configured chain -> falls back to env
    assert depletion.chain_path() == str(chain)
    assert depletion.is_available() is True


def test_fuel_volume_rules():
    import math

    from nbeast.core import depletion

    assert depletion.fuel_volume("godiva", {"radius": 3.0}) == pytest.approx(
        (4.0 / 3.0) * math.pi * 27.0)
    assert depletion.fuel_volume("pin_cell", {"fuel_radius": 0.4}) == pytest.approx(
        math.pi * 0.16)
    assert depletion.fuel_volume("assembly", {"fuel_radius": 0.4, "n_side": 3}) == pytest.approx(
        math.pi * 0.16 * 9)
    with pytest.raises(ValueError):
        depletion.fuel_volume("shield_slab", {})


def test_depletion_config_values():
    from nbeast.core.depletion import DepletionConfig

    power = DepletionConfig([5.0, 5.0, 5.0], normalization="power", power_watts=2.0e6)
    assert power.values() == [2.0e6, 2.0e6, 2.0e6]
    src = DepletionConfig([5.0, 5.0], normalization="source-rate", source_rate=1e16)
    assert src.values() == [1e16, 1e16]


def test_fuel_material_picks_fissionable():
    from nbeast.core import depletion, templates

    fuel = depletion.fuel_material(templates.pin_cell())
    assert "UO2" in fuel.name


# ---- integration (need data) ----------------------------------------------
@requires_data
def test_doppler_feedback_negative(tmp_path, monkeypatch):
    import openmc

    from nbeast.core import templates

    monkeypatch.chdir(tmp_path)

    def keff(temp):
        m = templates.pin_cell(batches=40, inactive=10, particles=1200, seed=1,
                               temperature=temp)
        with openmc.StatePoint(m.run(output=False, cwd=str(tmp_path))) as sp:
            return float(sp.keff.nominal_value)

    assert keff(900.0) < keff(294.0)  # hotter fuel -> more capture -> lower k


@requires_data
def test_shield_fixed_source_run(tmp_path):
    from nbeast.core import results, specs, tallies
    from nbeast.core.runner import Runner

    spec = specs.SPECS["Shield slab"]
    model = spec.build(batches=15, particles=2000, inactive=0, seed=1,
                       thickness=20.0, source_energy=2.0, temperature=294.0)
    tallies.add_flux_slice_mesh(model, n=20)
    tallies.add_dose_mesh(model, n=20)
    updates = []
    res = Runner().run(model, tmp_path / "sh", on_batch=updates.append)

    assert res.keff is None                 # fixed source -> no k-effective
    assert updates and updates[0].keff is None
    assert res.statepoint
    with results.Results(res.statepoint) as r:
        assert r.run_mode == "fixed source"
        flux, _, _ = r.field_values("flux")
        dose, _, _ = r.field_values("flux", "dose_mesh")
        assert (flux > 0).any() and (dose > 0).any()
        assert r.diagnostics().keff is None


@requires_data
def test_heating_field_finite_and_vtk_clean(tmp_path, monkeypatch):
    """Regression: 'heating' is NaN in water cells (no KERMA data) — those NaNs once
    wrote `nan` into the VTK and crashed the renderer. The field must come back
    finite and the VTK must contain no `nan`."""
    import numpy as np

    from nbeast.core import results, tallies, templates

    monkeypatch.chdir(tmp_path)
    m = templates.pin_cell(batches=30, inactive=8, particles=2000, seed=1)
    tallies.add_flux_slice_mesh(m, n=20)   # water cells -> NaN heating before the fix
    sp = m.run(output=False, cwd=str(tmp_path))
    with results.Results(sp) as r:
        mean, std, rel = r.field_values("heating")
        assert np.isfinite(mean).all() and np.isfinite(std).all() and np.isfinite(rel).all()
        vtk = r.field_to_vtk(tmp_path / "heating.vtk", score="heating",
                             name="flux_mesh", label="heating")
    assert "nan" not in vtk.read_text().lower()  # the exact crash trigger


@requires_data
def test_power_normalization_gives_absolute_flux(tmp_path, monkeypatch):
    """A reactor power turns per-source maps into absolute rates; 0 stays relative.
    The peak pin flux must land on a physical PWR scale."""
    from nbeast.core import results, tallies, templates

    monkeypatch.chdir(tmp_path)
    m = templates.pin_cell(batches=40, inactive=10, particles=2000, seed=1)
    tallies.add_power_norm(m)
    tallies.add_flux_slice_mesh(m, n=20)
    sp = m.run(output=False, cwd=str(tmp_path))
    with results.Results(sp) as r:
        assert r.source_rate(0.0) is None                    # 0 power -> relative
        assert r.absolute_factor("flux", 0.0, "flux_mesh") == 1.0
        rate = r.source_rate(65_000.0)                        # ~one PWR pin
        assert rate is not None and rate > 0
        flux, _s, _r = r.field_values("flux", "flux_mesh")
        peak = float(flux.max()) * r.absolute_factor("flux", 65_000.0, "flux_mesh")
        assert 1e12 < peak < 1e17                             # physical PWR-pin flux scale


@requires_data
def test_mgxs_generation(tmp_path, monkeypatch):
    from nbeast.core import mgxs_gen, templates

    monkeypatch.chdir(tmp_path)
    m = templates.pin_cell(batches=40, inactive=10, particles=1200, seed=1)
    lib = mgxs_gen.build_library(m, structure="CASMO-2", domain_type="material")
    sp = m.run(output=False, cwd=str(tmp_path))
    table = mgxs_gen.load_constants(lib, sp)
    assert table["n_groups"] == 2
    assert any("UO2" in d for d in table["domains"])
    nuf = next(table["domains"][d]["nu-fission"]["mean"] for d in table["domains"] if "UO2" in d)
    assert nuf[1] > nuf[0]  # thermal ν-fission exceeds fast for UO2
    out = mgxs_gen.export_constants(table, tmp_path / "mgxs.csv")
    assert out.exists() and out.read_text().count("\n") > 5
