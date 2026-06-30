"""Tier-3 raw mesh-data export (NumPy / CSV / HDF5).

``cell_centers`` ordering is checked data-free; a single integration test runs real
OpenMC and round-trips all three formats (skipped without a cross-section library).
"""

import os
import pathlib

import numpy as np
import pytest

from nbeast.core.results import cell_centers

_XS = os.environ.get("OPENMC_CROSS_SECTIONS")
requires_data = pytest.mark.skipif(
    not (_XS and pathlib.Path(_XS).exists()),
    reason="OPENMC_CROSS_SECTIONS not set or missing",
)


def test_cell_centers_order_and_values():
    # 2x3x1 mesh over [0,2]x[0,3]x[0,1]: cells 0.5 wide in x, y; one z layer.
    centers = cell_centers((2, 3, 1), (0, 0, 0), (2, 3, 1))
    assert centers.shape == (6, 3)
    # x varies fastest, then y (matches OpenMC mesh-cell flat order)
    assert np.allclose(centers[0], [0.5, 0.5, 0.5])
    assert np.allclose(centers[1], [1.5, 0.5, 0.5])   # next x
    assert np.allclose(centers[2], [0.5, 1.5, 0.5])   # x wraps, y advances
    assert np.allclose(centers[5], [1.5, 2.5, 0.5])


@requires_data
def test_raw_export_roundtrip(tmp_path, monkeypatch):
    import openmc

    from nbeast.core import benchmarks, results, tallies

    monkeypatch.chdir(tmp_path)
    model = benchmarks.godiva(particles=400, batches=12, inactive=3, seed=1)
    tallies.add_flux_spectrum(model, n_groups=20)
    mesh = tallies.add_flux_mesh(model, (3, 4, 5), (-9, -9, -9), (9, 9, 9))
    sp_path = model.run(output=False)

    # cell_centers must match OpenMC's own centroids in the same flat order
    expected = np.asarray(mesh.centroids).transpose(2, 1, 0, 3).reshape(-1, 3)
    assert np.allclose(cell_centers((3, 4, 5), (-9, -9, -9), (9, 9, 9)), expected)

    with results.Results(sp_path) as r:
        arrays = r.mesh_arrays()
        assert arrays["dimension"] == (3, 4, 5)
        flux_mean = arrays["data"]["flux"]["mean"]
        assert flux_mean.shape == (60,)

        # NumPy
        npz = r.export_mesh_data(tmp_path / "raw.npz")
        z = np.load(npz, allow_pickle=True)
        assert np.allclose(z["flux_mean"], flux_mean)
        assert "flux_std" in z and "flux_rel_err" in z
        assert "spectrum_flux" in z  # spectrum bundled in
        assert tuple(z["dimension"]) == (3, 4, 5)

        # HDF5
        import h5py

        h5 = r.export_mesh_data(tmp_path / "raw.h5")
        with h5py.File(h5) as f:
            assert np.allclose(f["scores/flux/mean"][:], flux_mean)
            assert tuple(f["mesh"].attrs["dimension"]) == (3, 4, 5)
            assert "spectrum" in f

        # CSV — one row per cell, with coordinates and uncertainties
        csv_path = r.export_mesh_data(tmp_path / "raw.csv")
        lines = csv_path.read_text().splitlines()
        header = [ln for ln in lines if not ln.startswith("#")][0]
        assert "flux_mean" in header and "flux_std" in header and "x_cm" in header
        data_rows = [ln for ln in lines if not ln.startswith("#")][1:]
        assert len(data_rows) == 60


@requires_data
def test_raw_export_bad_format(tmp_path, monkeypatch):
    from nbeast.core import benchmarks, results, tallies

    monkeypatch.chdir(tmp_path)
    model = benchmarks.godiva(particles=300, batches=8, inactive=2, seed=1)
    tallies.add_flux_mesh(model, (2, 2, 2), (-9, -9, -9), (9, 9, 9))
    sp_path = model.run(output=False)
    with results.Results(sp_path) as r:
        with pytest.raises(ValueError):
            r.export_mesh_data(tmp_path / "raw.txt", fmt="txt")
