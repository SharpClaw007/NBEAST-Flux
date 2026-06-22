"""Results reader: spectrum + mesh extraction from a real statepoint."""

import os
import pathlib

import pytest

_XS = os.environ.get("OPENMC_CROSS_SECTIONS")
requires_data = pytest.mark.skipif(
    not (_XS and pathlib.Path(_XS).exists()),
    reason="OPENMC_CROSS_SECTIONS not set or missing",
)


@requires_data
def test_spectrum_and_mesh(tmp_path, monkeypatch):
    from nbeast.core import benchmarks, results, tallies

    monkeypatch.chdir(tmp_path)
    model = benchmarks.pincell(particles=2000, batches=60, inactive=20)
    tallies.add_flux_spectrum(model, n_groups=50)
    tallies.add_flux_mesh(
        model,
        dimension=(20, 20, 1),
        lower_left=(-0.63, -0.63, -1.0),
        upper_right=(0.63, 0.63, 1.0),
    )
    sp_path = model.run(output=False)

    with results.Results(sp_path) as r:
        assert r.keff.nominal_value > 0

        spec = r.flux_spectrum()
        assert spec.flux.shape[0] == 50
        assert spec.energy_edges.shape[0] == 51
        assert (spec.flux >= 0).all() and spec.flux.sum() > 0

        vtk = r.flux_mesh_to_vtk(tmp_path / "flux.vtk")
        assert vtk.exists() and vtk.stat().st_size > 0
