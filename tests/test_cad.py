"""CAD engine: presets, material specs, env discovery (fast, no DAGMC envs needed)."""

import os
import pathlib

import pytest

from nbeast.core import cad


def test_material_presets():
    assert "heu" in cad.MATERIAL_PRESETS
    for preset in cad.MATERIAL_PRESETS.values():
        assert {"label", "density", "nuclides"} <= preset.keys()


def test_material_specs_unique_and_ordered():
    specs = cad.material_specs(["heu", "water", "heu"])
    assert [s["name"] for s in specs] == ["heu", "water"]
    assert specs[0]["density"] == 18.74
    assert specs[0]["nuclides"][0]["nuclide"] == "U235"


def test_is_available_returns_bool():
    assert isinstance(cad.is_available(), bool)


def test_env_discovery_does_not_raise():
    for fn in (cad.cad_python, cad.dagmc_python):
        result = fn()
        assert result is None or isinstance(result, pathlib.Path)


def test_cad_worker_dose_filters_are_log_log():
    """_cad_run.py executes in the dagmc env (not importable here), so lock in the
    ICRP dose-coefficient interpolation scheme at the source level: every dose tally
    must use the log-log filter helper, never a bare EnergyFunctionFilter."""
    src = (pathlib.Path(cad.__file__).parent / "_cad_run.py").read_text()
    assert 'interpolation = "log-log"' in src
    # both dose tallies route through the helper; no bare filter construction remains
    assert src.count("_dose_filter()") >= 2
    assert "EnergyFunctionFilter(energies_dose, coeffs_dose)]" not in src


def test_conda_exe_and_channel_url():
    assert cad.conda_exe() is None or isinstance(cad.conda_exe(), pathlib.Path)
    assert cad.DEFAULT_CHANNEL_URL.startswith("https://")
    assert cad.DEFAULT_CHANNEL_URL.endswith(".tar.gz")


@pytest.mark.skipif(
    not (cad.is_available() and os.environ.get("NBEAST_CAD_E2E")),
    reason="opt-in (NBEAST_CAD_E2E) end-to-end requiring the DAGMC envs",
)
def test_end_to_end(tmp_path):
    import subprocess

    step = tmp_path / "sphere.step"
    subprocess.run(
        [str(cad.cad_python()), "-c",
         f"import cadquery as cq; cq.exporters.export(cq.Workplane().sphere(8.7), '{step}')"],
        check=True,
    )
    info = cad.inspect_step(step)
    assert info["n_solids"] == 1
    assert info["extent"] == pytest.approx(17.4, abs=1.0)  # sphere of r=8.7 -> ~17.4 across
    h5m = cad.generate_h5m(step, ["heu"], tmp_path / "m.h5m", max_mesh_size=3.0, min_mesh_size=0.5)
    res = cad.run_model(h5m, cad.material_specs(["heu"]), batches=20, inactive=5, particles=1000)
    assert 0.7 < res["keff"] < 1.2
    assert len(res["flux"]) == 100
    assert len(res["flux_map"]) == 50 and len(res["flux_map"][0]) == 50
