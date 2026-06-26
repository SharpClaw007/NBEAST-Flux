"""Provenance capture: versions, seed, parameters recorded for reproducibility."""

import json


def test_capture_basic_fields():
    from nbeast.core import provenance

    meta = provenance.capture(template="Godiva", parameters={"radius": 8.74})
    assert meta.nbeast_version and meta.openmc_version
    assert meta.template == "Godiva"
    assert meta.parameters == {"radius": 8.74}
    assert meta.created_utc.endswith("Z")
    assert meta.machine  # platform.machine() is always non-empty


def test_capture_reads_model_settings():
    from nbeast.core import benchmarks, provenance

    model = benchmarks.godiva(batches=33, inactive=7, particles=1234, seed=42)
    meta = provenance.capture(template="Godiva", parameters={}, model=model)
    assert meta.batches == 33
    assert meta.inactive == 7
    assert meta.particles == 1234
    assert meta.seed == 42
    assert "seed: 42" in " ".join(meta.summary_lines())


def test_data_library_label_from_path():
    from nbeast.core import provenance

    meta = provenance.capture(
        template=None, parameters={},
        cross_sections="/data/endfb-viii.0-hdf5/cross_sections.xml",
    )
    assert meta.data_library == "endfb-viii.0-hdf5"


def test_to_json_roundtrips(tmp_path):
    from nbeast.core import benchmarks, provenance

    model = benchmarks.godiva(seed=5)
    meta = provenance.capture(template="Godiva", parameters={"radius": 8.74}, model=model)
    path = meta.to_json(tmp_path / "provenance.json")
    assert path.exists()
    loaded = json.loads(path.read_text())
    assert loaded["seed"] == 5
    assert loaded["template"] == "Godiva"
    assert loaded["openmc_version"] == meta.openmc_version


def test_export_deck_writes_provenance(tmp_path):
    from nbeast.core import benchmarks, export, provenance

    model = benchmarks.godiva(seed=9)
    meta = provenance.capture(template="Godiva", parameters={}, model=model)
    export.export_deck(model, tmp_path / "deck", metadata=meta)
    assert (tmp_path / "deck" / "model.xml").exists()
    assert (tmp_path / "deck" / "run.py").exists()
    assert (tmp_path / "deck" / "provenance.json").exists()
    assert json.loads((tmp_path / "deck" / "provenance.json").read_text())["seed"] == 9
