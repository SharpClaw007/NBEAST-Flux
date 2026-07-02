"""G3: persistent studies — the serializable core + the project-backed GUI store."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ---- core (Qt-free) ---------------------------------------------------------
def test_study_config_round_trips():
    from nbeast.core.studies import StudyConfig

    c = StudyConfig(kind="sweep", name="pitch", params={"parameter": "pitch", "lo": 1.2},
                    quality={"batches": 60}, study_id="study-001")
    assert StudyConfig.from_dict(c.to_dict()) == c


def test_available_kinds_gating():
    from nbeast.core import studies

    fixed = studies.available_kinds(eigenvalue=False, moderated=False)
    assert fixed == ["keff"]                              # only a plain run
    fast = studies.available_kinds(eigenvalue=True, moderated=False)
    assert "sweep" in fast and "moderation" not in fast   # no moderator → no moderation curve
    thermal = studies.available_kinds(eigenvalue=True, moderated=True)
    assert {"moderation", "poisoning"} <= set(thermal)


def test_default_name_is_unique():
    from nbeast.core import studies

    assert studies.default_name("sweep", []) == "Parameter sweep"
    assert studies.default_name("sweep", ["Parameter sweep"]) == "Parameter sweep 2"


# ---- GUI store (project-backed) ---------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_store_persists_across_reopen(qapp, tmp_path):
    from nbeast.core.project import Project
    from nbeast.core.studies import StudyResult
    from nbeast.gui.studies import StudyStore

    proj = Project.create(tmp_path / "p")
    store = StudyStore(proj)
    config = store.add("sweep", {"batches": 60}, {"parameter": "pitch"})
    store.set_result(config.study_id, StudyResult(ok=True, summary="did a thing"))

    reopened = StudyStore(Project.open(tmp_path / "p"))
    configs = reopened.configs()
    assert len(configs) == 1 and configs[0].kind == "sweep"
    assert configs[0].params["parameter"] == "pitch"
    assert reopened.get_result(config.study_id).summary == "did a thing"


def test_store_crud(qapp, tmp_path):
    from nbeast.core.project import Project
    from nbeast.gui.studies import StudyStore

    store = StudyStore(Project.create(tmp_path / "p"))
    a = store.add("keff", {})
    b = store.add("sweep", {}, {"parameter": "pitch"})
    store.rename(a.study_id, "baseline")
    assert store.get(a.study_id).name == "baseline"
    dup = store.duplicate(b.study_id)
    assert dup.params == b.params and dup.study_id != b.study_id
    store.delete(b.study_id)
    assert {c.study_id for c in store.configs()} == {a.study_id, dup.study_id}


def test_mainwindow_has_default_keff_study_and_persists_result(qapp, tmp_path):
    from nbeast.gui.main_window import MainWindow

    win = MainWindow(run_root=tmp_path, project_dir=tmp_path / "p")
    kinds = [win.studies.get(s).kind for s in win.model_tree.study_ids()]
    assert kinds == ["keff"]                              # every project starts with one

    # add a sweep study via the tree path; it persists + shows in the tree
    win._add_study("sweep")
    assert "sweep" in [win.studies.get(s).kind for s in win.model_tree.study_ids()]

    # simulate a finished run snapshotting onto the keff study
    from nbeast.core.runner import RunResult
    win._active_study = next(s for s in win.model_tree.study_ids()
                             if win.studies.get(s).kind == "keff")
    win.last_diagnostics = None
    win._snapshot_keff_study(RunResult(keff=1.413, keff_std=0.0009, batches=[]))
    result = win.studies.get_result(win._active_study)
    assert result and "1.413" in result.summary
    win.close()
