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
    filt = next(f for f in dose.filters if isinstance(f, openmc.EnergyFunctionFilter))
    # ICRP-116 coefficients are interpolated log-log by convention. The filter default
    # is linear-linear, which distorts thermal/epithermal dose — lock the scheme in.
    assert filt.interpolation == "log-log"


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
def test_doppler_coefficient_sign_and_magnitude(tmp_path, monkeypatch):
    """Hotter fuel broadens U-238 capture resonances → lower k. Beyond the sign, the
    294→900 K coefficient must land in a physical band: NBEAST's validated value is
    −3.59 pcm/K (validation.md), and the Mosteller benchmark reference is −2.2 to
    −4.2 pcm/K across enrichments. Assert −1.5 to −5.5 pcm/K — catches a broken or
    wrong-magnitude Doppler, wide enough for CI-quality statistics."""
    import openmc

    from nbeast.core import templates

    monkeypatch.chdir(tmp_path)

    def keff(temp):
        m = templates.pin_cell(batches=60, inactive=15, particles=3000, seed=1,
                               temperature=temp)
        with openmc.StatePoint(m.run(output=False, cwd=str(tmp_path))) as sp:
            return float(sp.keff.nominal_value)

    k_cold, k_hot = keff(294.0), keff(900.0)
    assert k_hot < k_cold                                   # sign
    coef = (k_hot - k_cold) / (k_hot * k_cold) / (900.0 - 294.0) * 1e5   # pcm/K
    assert -5.5 < coef < -1.5, f"Doppler coefficient out of band: {coef:.2f} pcm/K"


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
        assert r.absolute_factor("flux", None, "flux_mesh") == 1.0
        rate = r.source_rate(65_000.0)                        # ~one PWR pin
        assert rate is not None and rate > 0
        flux, _s, _r = r.field_values("flux", "flux_mesh")
        peak = float(flux.max()) * r.absolute_factor("flux", rate, "flux_mesh")
        assert 1e12 < peak < 1e17                             # physical PWR-pin flux scale
        # fixed-source style: a source rate normalizes directly; fission power is an output
        assert r.fission_power(rate) is not None and r.fission_power(rate) > 0


@requires_data
def test_field_extruded_volume_is_exact_z_uniform(tmp_path, monkeypatch):
    """A z-invariant (infinite-z) pin cell's slice extrudes to a 3D block where every
    z-layer is identical — i.e. the reconstruction is exact, not an approximation."""
    import numpy as np

    from nbeast.core import results, tallies, templates

    monkeypatch.chdir(tmp_path)
    m = templates.pin_cell(batches=30, inactive=8, particles=1200, seed=1)
    tallies.add_flux_slice_mesh(m, n=20)
    sp = m.run(output=False, cwd=str(tmp_path))
    with results.Results(sp) as r:
        vals, dims, lower, upper, _rel = r.field_extruded_volume("flux", "flux_mesh")
        assert dims == (20, 20, 20) and vals.size == 8000
        layers = vals.reshape(dims[2], dims[1], dims[0])  # (k, j, i) from x-fastest flat
        assert np.allclose(layers[0], layers[-1])          # every z-layer identical
        assert upper[2] > lower[2]                          # a real display z-extent


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
    uo2 = next(table["domains"][d] for d in table["domains"] if "UO2" in d)
    assert uo2["nu-fission"]["mean"][1] > uo2["nu-fission"]["mean"][0]  # thermal ν-fission ≫ fast
    # complete diffusion set: transport, diffusion coefficient, and a 2×2 scatter matrix
    assert "transport" in uo2 and "diffusion" in uo2
    assert uo2["nu-scatter matrix"]["matrix"] is True
    assert len(uo2["nu-scatter matrix"]["mean"]) == 2 and len(uo2["nu-scatter matrix"]["mean"][0]) == 2
    out = mgxs_gen.export_constants(table, tmp_path / "mgxs.csv")
    assert out.exists() and out.read_text().count("\n") > 5
    assert "1->2" in out.read_text()   # scatter matrix present in the CSV


@requires_data
def test_two_group_constants_reproduce_kinf(tmp_path, monkeypatch):
    """The exported few-group set is a *usable* diffusion set: an infinite-medium
    two-group solve (leakage-free, so k∞) from the homogenized constants reproduces the
    continuous-energy Monte Carlo k∞. This is the claim that makes 'diffusion codes
    consume this' true — a single flux-weighted domain over the whole pin cell.
    """
    import numpy as np

    from nbeast.core import mgxs_gen, results, templates

    monkeypatch.chdir(tmp_path)
    m = templates.pin_cell(batches=80, inactive=20, particles=4000, seed=3)
    lib = mgxs_gen.build_library(m, structure="CASMO-2", domain_type="universe")
    sp = m.run(output=False, cwd=str(tmp_path))
    table = mgxs_gen.load_constants(lib, sp)
    with results.Results(sp) as r:
        k_mc = float(r.keff.nominal_value)

    per = next(iter(table["domains"].values()))   # one homogenized set for the whole cell
    absorption = np.asarray(per["absorption"]["mean"], float)
    nufiss = np.asarray(per["nu-fission"]["mean"], float)
    chi = np.asarray(per["chi"]["mean"], float)
    scatter = np.asarray(per["nu-scatter matrix"]["mean"], float)  # [g_in][g_out]
    chi = chi / chi.sum() if chi.sum() > 0 else chi

    # Infinite-medium eigenproblem M φ = (1/k) χ νΣfᵀ φ. Use the *consistent* P0 balance
    # (removal = absorption + out-scatter), not the "total" XS — openmc.mgxs 'total'
    # carries angular moments that don't close a P0 diffusion balance. Removal operator:
    #   M[g][g]  = Σa,g + Σ_g' Σs(g→g')      (absorption + total out-scatter)
    #   M[g][g'] = −Σs(g'→g)                  (in-scatter), so M = diag(Σa+rowΣs) − Sᵀ.
    removal = np.diag(absorption + scatter.sum(axis=1)) - scatter.T
    fission = np.outer(chi, nufiss)
    k = float(np.max(np.linalg.eigvals(np.linalg.solve(removal, fission)).real))

    # Agreement to ~1% (≈450 pcm here) — the known two-group collapse/P0 consistency
    # error, not a pipeline error. This is the row that makes the diffusion claim real.
    assert abs(k - k_mc) < 1.0e-2, f"two-group k∞ {k:.5f} vs MC {k_mc:.5f}"
