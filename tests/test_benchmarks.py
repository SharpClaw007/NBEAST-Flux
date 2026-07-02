"""Regression tests for the validated benchmarks.

Headline: Godiva must return k_eff ~= 1.0. These run real OpenMC and need a
cross-section library; they skip (not fail) when one isn't configured, and CI
provides one. See conftest.py for the PATH / FI_PROVIDER setup.
"""

import os
import pathlib

import pytest

_XS = os.environ.get("OPENMC_CROSS_SECTIONS")
requires_data = pytest.mark.skipif(
    not (_XS and pathlib.Path(_XS).exists()),
    reason="OPENMC_CROSS_SECTIONS not set or missing",
)


@requires_data
def test_godiva_critical(tmp_path, monkeypatch):
    """Bare HEU sphere is critical: k_eff within ~1000 pcm of 1.0."""
    import openmc

    from nbeast.core import benchmarks

    monkeypatch.chdir(tmp_path)
    model = benchmarks.godiva(particles=5000, batches=120, inactive=20)
    sp_path = model.run(output=False)
    with openmc.StatePoint(sp_path) as sp:
        k = sp.keff

    assert abs(k.nominal_value - 1.0) < 0.01, f"Godiva k_eff off: {k}"
    # And statistically consistent with 1.0 (within ~4 sigma + a small data margin).
    assert abs(k.nominal_value - 1.0) < 4 * k.std_dev + 0.004, f"Godiva k_eff: {k}"


@requires_data
def test_jezebel_critical(tmp_path, monkeypatch):
    """Faithful Jezebel (PU-MET-FAST-001): bare δ-phase Pu-Ga sphere, k_eff ~= 1.0.
    Skips unless Pu + Ga data is present (not in the bundled H/O/U/Zr library)."""
    import openmc

    from nbeast.core import benchmarks, materials

    available = materials.available_names(_XS)
    if not set(benchmarks.JEZEBEL_NUCLIDES) <= available:
        pytest.skip("Jezebel needs Pu + Ga cross sections (not in the bundle)")

    monkeypatch.chdir(tmp_path)
    model = benchmarks.jezebel(particles=5000, batches=120, inactive=20)
    with openmc.StatePoint(model.run(output=False)) as sp:
        k = sp.keff
    assert abs(k.nominal_value - 1.0) < 0.01, f"Jezebel k_eff off: {k}"
    assert abs(k.nominal_value - 1.0) < 4 * k.std_dev + 0.005, f"Jezebel k_eff: {k}"


@requires_data
def test_mosteller_pincell_doppler(tmp_path, monkeypatch):
    """Mosteller Doppler-defect benchmark (LA-UR-07-0922) at 3.9 wt%. Validates a real
    published thermal pin cell: absolute k∞ near the cross-code reference, and a
    physical Doppler coefficient from the HFP−HZP pair. Skips unless Boron is installed
    (borated moderator; not in the bundle). Absolute k runs ~1 % high at low enrichment
    because the bundled H-in-H2O kernel is 294 K-only (snapped) — the *defect* is
    kernel-insensitive, which is what this asserts most tightly."""
    import openmc

    from nbeast.core import benchmarks, materials

    if not {"B10", "B11"} <= materials.available_names(_XS):
        pytest.skip("Mosteller needs Boron (borated moderator) — not in the bundle")

    monkeypatch.chdir(tmp_path)

    def keff(fuel_temp):
        m = benchmarks.mosteller_pincell(enrichment=3.9, fuel_temp=fuel_temp,
                                         particles=4000, batches=100, inactive=25, seed=1)
        with openmc.StatePoint(m.run(output=False)) as sp:
            return float(sp.keff.nominal_value)

    k_hfp, k_hzp = keff(900.0), keff(600.0)
    ref_hfp = benchmarks.MOSTELLER_KEFF[3.9]["HFP"][0]                 # 1.23048 (ENDF/B-VII.0)
    assert abs(k_hfp - ref_hfp) < 0.012, f"Mosteller 3.9% HFP k {k_hfp:.5f} vs {ref_hfp}"
    coef = (k_hfp - k_hzp) / (k_hfp * k_hzp) / 300.0 * 1e5             # pcm/K, ref −2.20
    assert -4.0 < coef < -1.2, f"Mosteller Doppler coefficient {coef:.2f} pcm/K"


@requires_data
def test_pincell_regression(tmp_path, monkeypatch):
    """UO2/water pin cell k∞. Regression pin to NBEAST's own validated output
    (validation.md: 1.41303 ± 86 pcm) — NOT an external truth. A window of ±~1200 pcm
    around 1.413 (was ±10000): tight enough that a few-percent density error or an
    enrichment slip (3.2 → ~2.5 %, ≈ −4000 pcm) fails, loose enough for CI-quality σ."""
    import openmc

    from nbeast.core import benchmarks

    monkeypatch.chdir(tmp_path)
    model = benchmarks.pincell(particles=2000, batches=80, inactive=20, seed=1)
    with openmc.StatePoint(model.run(output=False)) as sp:
        k = sp.keff
    assert 1.401 < k.nominal_value < 1.425, f"pin-cell k∞ regression: {k}"


@requires_data
def test_assembly_equals_pincell(tmp_path, monkeypatch):
    """The internal-consistency check as a test: a reflective N×N assembly is an
    infinite lattice of identical pins, so its k∞ must equal the single pin cell's to
    within combined statistics (validation.md shows ~1 pcm). Catches lattice/boundary
    regressions the loose range window would miss."""
    import openmc

    from nbeast.core import benchmarks

    monkeypatch.chdir(tmp_path)
    with openmc.StatePoint(
        benchmarks.pincell(particles=3000, batches=80, inactive=20, seed=1).run(output=False)
    ) as sp:
        k_pin, s_pin = float(sp.keff.nominal_value), float(sp.keff.std_dev)
    with openmc.StatePoint(
        benchmarks.assembly(n_side=3, particles=1500, batches=80, inactive=20, seed=1).run(output=False)
    ) as sp:
        k_asm, s_asm = float(sp.keff.nominal_value), float(sp.keff.std_dev)

    combined = (s_pin ** 2 + s_asm ** 2) ** 0.5
    assert abs(k_pin - k_asm) < 4 * combined + 5e-4, (
        f"assembly k∞ {k_asm:.5f} vs pin {k_pin:.5f} (Δ {(k_asm-k_pin)*1e5:.0f} pcm)")
