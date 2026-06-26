"""Tier-1 trust layer: uncertainties, Shannon entropy, and convergence checks.

The heuristic + live-entropy-math tests are data-free (fast); one integration
test runs real OpenMC and is skipped without a cross-section library.
"""

import os
import pathlib

import numpy as np
import pytest

_XS = os.environ.get("OPENMC_CROSS_SECTIONS")
requires_data = pytest.mark.skipif(
    not (_XS and pathlib.Path(_XS).exists()),
    reason="OPENMC_CROSS_SECTIONS not set or missing",
)


# ---- convergence heuristics (data-free) ----------------------------------
def test_clean_run_has_no_warnings():
    from nbeast.core.results import _convergence_warnings

    entropy = np.concatenate([np.linspace(2, 6, 20), 6 + 0.01 * np.random.default_rng(0).standard_normal(40)])
    warns = _convergence_warnings(
        keff_std=0.0005, entropy=entropy, n_inactive=20, n_active=40,
        mean_rel=0.03, max_rel=0.10,
    )
    assert warns == []


def test_high_keff_uncertainty_warns():
    from nbeast.core.results import _convergence_warnings

    warns = _convergence_warnings(0.004, None, 20, 40, 0.02, 0.05)
    assert any("uncertainty is high" in w for w in warns)


def test_noisy_flux_warns():
    from nbeast.core.results import _convergence_warnings

    warns = _convergence_warnings(0.0005, None, 20, 40, 0.35, 0.9)
    assert any("statistically noisy" in w for w in warns)


def test_too_few_inactive_warns():
    from nbeast.core.results import _convergence_warnings

    warns = _convergence_warnings(0.0005, None, 2, 40, 0.02, 0.05)
    assert any("inactive batches" in w for w in warns)


def test_unconverged_entropy_warns():
    from nbeast.core.results import _convergence_warnings

    # Entropy still climbing steeply across the active region => not converged.
    entropy = np.concatenate([np.linspace(2, 4, 10), np.linspace(4, 8, 40)])
    warns = _convergence_warnings(0.0005, entropy, 10, 40, 0.02, 0.05)
    assert any("not be converged" in w for w in warns)


# ---- live entropy from a (synthetic) source bank (data-free) --------------
def _sites(coords, wgt=1.0):
    dt = np.dtype([("r", [("x", "f8"), ("y", "f8"), ("z", "f8")]), ("wgt", "f8")])
    arr = np.zeros(len(coords), dtype=dt)
    for i, (x, y, z) in enumerate(coords):
        arr["r"]["x"][i], arr["r"]["y"][i], arr["r"]["z"][i] = x, y, z
    arr["wgt"] = wgt
    return arr


def test_live_entropy_math(tmp_path, monkeypatch):
    import json

    from nbeast.core.worker import _make_entropy_fn

    monkeypatch.chdir(tmp_path)
    # 2x2x1 mesh over the unit square => 4 bins, max entropy log2(4) = 2 bits.
    (tmp_path / "entropy_mesh.json").write_text(json.dumps({
        "lower_left": [0, 0, 0], "upper_right": [1, 1, 1], "dimension": [2, 2, 1],
    }))
    fn = _make_entropy_fn()
    assert fn is not None

    # All sites in one bin -> entropy 0.
    assert fn(_sites([(0.1, 0.1, 0.5)] * 8)) == pytest.approx(0.0, abs=1e-9)
    # One site per bin (uniform) -> entropy = log2(4) = 2 bits.
    uniform = _sites([(0.25, 0.25, 0.5), (0.75, 0.25, 0.5), (0.25, 0.75, 0.5), (0.75, 0.75, 0.5)])
    assert fn(uniform) == pytest.approx(2.0, abs=1e-9)


def test_entropy_fn_absent_without_mesh(tmp_path, monkeypatch):
    from nbeast.core.worker import _make_entropy_fn

    monkeypatch.chdir(tmp_path)
    assert _make_entropy_fn() is None


# ---- entropy mesh sizing (data-free) -------------------------------------
def test_entropy_mesh_collapses_infinite_axis():
    from nbeast.core import benchmarks, tallies

    pin = benchmarks.pincell()
    mesh = tallies.add_entropy_mesh(pin, n=8)
    assert tuple(mesh.dimension) == (8, 8, 1)  # z is unbounded -> single bin
    assert pin.settings.entropy_mesh is mesh

    sphere = benchmarks.godiva()
    smesh = tallies.add_entropy_mesh(sphere, n=8)
    assert tuple(smesh.dimension) == (8, 8, 8)  # fully bounded


# ---- end-to-end uncertainty + diagnostics (needs data) -------------------
@requires_data
def test_uncertainty_and_diagnostics(tmp_path, monkeypatch):
    from nbeast.core import benchmarks, results, tallies

    monkeypatch.chdir(tmp_path)
    model = benchmarks.godiva(particles=2000, batches=40, inactive=10, seed=1)
    tallies.add_flux_spectrum(model, n_groups=40)
    tallies.add_flux_mesh(model, (10, 10, 10), (-9, -9, -9), (9, 9, 9))
    tallies.add_entropy_mesh(model)
    sp_path = model.run(output=False)

    with results.Results(sp_path) as r:
        spec = r.flux_spectrum()
        assert spec.flux_std.shape == spec.flux.shape
        assert (spec.flux_std > 0).any()
        assert (spec.rel_err >= 0).all()

        mean, std, rel = r.field_values("flux")
        assert mean.shape == std.shape == rel.shape

        ent = r.entropy()
        assert ent is not None and ent.size == 40

        diag = r.diagnostics()
        assert diag.n_inactive == 10 and diag.n_active == 30
        assert diag.keff_std > 0 and diag.keff_pcm > 0
        assert diag.flux_max_rel_err is not None
        # summary always renders without error
        assert any("k-effective" in line for line in diag.summary_lines())

        # the rel-err VTK carries both arrays
        vtk = r.field_to_vtk(tmp_path / "flux.vtk", "flux")
        import pyvista as pv

        grid = pv.read(str(vtk))
        names = set(grid.cell_data.keys()) | set(grid.point_data.keys())
        assert "flux" in names and "flux_rel_err" in names
