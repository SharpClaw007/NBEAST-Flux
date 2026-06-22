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
def test_pincell_reasonable(tmp_path, monkeypatch):
    """UO2/water pin cell k_inf lands in the expected PWR range (~1.41)."""
    import openmc

    from nbeast.core import benchmarks

    monkeypatch.chdir(tmp_path)
    model = benchmarks.pincell(particles=2000, batches=80, inactive=20)
    sp_path = model.run(output=False)
    with openmc.StatePoint(sp_path) as sp:
        k = sp.keff

    assert 1.30 < k.nominal_value < 1.50, f"pin-cell k_inf out of range: {k}"
