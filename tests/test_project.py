"""Tier-3 project save/load + persistent run history (data-free)."""

from pathlib import Path

from nbeast.core.project import Project, RunRecord


def _fake_statepoint(tmp_path: Path, text: str = "sp") -> Path:
    p = tmp_path / "src_statepoint.h5"
    p.write_text(text)
    return p


def test_create_open_roundtrip(tmp_path):
    proj = Project.create(tmp_path / "proj", name="study A")
    assert (tmp_path / "proj" / "project.json").exists()
    proj.update_state(template="Godiva",
                      param_values={"Godiva": {"radius": 8.74}},
                      settings={"batches": 80, "particles": 1500, "seed": 3})

    reopened = Project.open(tmp_path / "proj")
    assert reopened.name == "study A"
    assert reopened.template == "Godiva"
    assert reopened.param_values["Godiva"]["radius"] == 8.74
    assert reopened.settings["seed"] == 3


def test_open_or_create(tmp_path):
    p = tmp_path / "p"
    first = Project.open_or_create(p)
    first.update_state(template="Pin cell")
    second = Project.open_or_create(p)  # opens the existing one, not a fresh project
    assert second.template == "Pin cell"


def test_open_missing_raises(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        Project.open(tmp_path / "nope")


def test_add_run_copies_statepoint_and_assigns_ids(tmp_path):
    proj = Project.create(tmp_path / "proj")
    sp = _fake_statepoint(tmp_path)
    model_xml = tmp_path / "model.xml"
    model_xml.write_text("<model/>")

    r1 = proj.add_run(statepoint_src=sp, model_xml_src=model_xml, template="Godiva",
                      parameters={"radius": 8.7}, batches=80, inactive=16, particles=2000,
                      seed=1, keff=0.998, keff_std=0.0009, warnings=["w"])
    r2 = proj.add_run(statepoint_src=sp, template="Godiva", parameters={"radius": 9.0},
                      keff=1.05, keff_std=0.001)

    assert r1.id == "run-0001" and r2.id == "run-0002"
    archived = proj.statepoint_path(r1)
    assert archived.exists() and archived.read_text() == "sp"
    assert (proj.runs_dir / "run-0001" / "model.xml").exists()
    assert r1.keff_pcm == 90.0  # 0.0009 * 1e5

    # survives reopen
    reopened = Project.open(tmp_path / "proj")
    assert len(reopened.runs) == 2
    assert reopened.statepoint_path(reopened.get_run("run-0001")).exists()


def test_delete_run_removes_files(tmp_path):
    proj = Project.create(tmp_path / "proj")
    sp = _fake_statepoint(tmp_path)
    rec = proj.add_run(statepoint_src=sp, template="Godiva", parameters={})
    run_dir = proj.runs_dir / rec.id
    assert run_dir.exists()

    assert proj.delete_run(rec.id) is True
    assert not run_dir.exists()
    assert proj.get_run(rec.id) is None
    assert proj.delete_run("run-9999") is False  # no-op on unknown id


def test_next_id_after_deletion_does_not_collide(tmp_path):
    proj = Project.create(tmp_path / "proj")
    sp = _fake_statepoint(tmp_path)
    a = proj.add_run(statepoint_src=sp, template="X", parameters={})
    b = proj.add_run(statepoint_src=sp, template="X", parameters={})
    proj.delete_run(a.id)
    c = proj.add_run(statepoint_src=sp, template="X", parameters={})
    assert c.id == "run-0003"  # max existing (run-0002) + 1, not a reused id
    assert {b.id, c.id} == {"run-0002", "run-0003"}


def test_run_record_title_and_tolerant_load():
    rec = RunRecord(id="run-0001", template="Godiva", parameters={}, keff=1.0, keff_std=0.0)
    assert "Godiva" in rec.title() and "1.0" in rec.title()
    assert RunRecord(id="x", template="t", parameters={}, label="My label").title() == "My label"
    # from_dict ignores unknown keys (forward/backward compatibility)
    rec2 = RunRecord.from_dict({"id": "run-0002", "template": "t", "unknown_field": 5})
    assert rec2.id == "run-0002" and rec2.template == "t"
