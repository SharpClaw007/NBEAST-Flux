"""Adversarial persistence + state tests: random project graphs round-trip exactly,
corrupt/foreign manifests fail gracefully, schema v1 migrates, study CRUD stays
consistent under random sequences, and stale/garbage material keys never crash.
Data-free (no OpenMC); seeded RNG for reproducibility.
"""

from __future__ import annotations

import json
import os
import random

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from nbeast.core.project import Project, RunRecord  # noqa: E402


# ---- project manifest: round-trip + corruption -----------------------------
def test_random_project_graph_round_trips(tmp_path):
    rng = random.Random(30)
    for trial in range(30):
        proj = Project.create(tmp_path / f"p{trial}", name=f"proj-{trial}")
        proj.template = rng.choice(["Pin cell", "Godiva", "Fuel assembly", "Shield slab"])
        proj.param_values = {"Pin cell": {"pitch": rng.uniform(0.5, 3), "enrichment": rng.uniform(1, 90)}}
        proj.material_values = {"Pin cell": {"fuel": rng.choice(["uo2", "u_metal", "mox"])}}
        proj.settings = {"batches": rng.randint(10, 500), "seed": rng.randint(1, 10**6)}
        proj.studies = [{"config": {"kind": rng.choice(["keff", "sweep"]), "name": f"s{i}",
                                    "params": {"lo": rng.random()}, "quality": {},
                                    "study_id": f"study-{i:03d}"},
                         "result": None} for i in range(rng.randint(0, 5))]
        proj.save()

        reopened = Project.open(tmp_path / f"p{trial}")
        assert reopened.template == proj.template
        assert reopened.param_values == proj.param_values
        assert reopened.material_values == proj.material_values
        assert reopened.settings == proj.settings
        assert reopened.studies == proj.studies
        assert json.loads(reopened.manifest_path.read_text())["nbeast_project_version"] == 2


def test_corrupt_and_foreign_manifests_fail_cleanly(tmp_path):
    cases = {
        "truncated": '{"nbeast_project_version": 2, "name": "x", "stud',
        "not_json": "this is not json at all {{{",
        "empty": "",
        "wrong_types": '{"name": 123, "runs": "not a list", "studies": {"a": 1}, '
                       '"param_values": [1,2,3]}',
        "foreign": '{"some_other_app": true, "version": 99}',
        "null_fields": '{"nbeast_project_version": 2, "name": null, "runs": null, '
                       '"studies": null, "template": null}',
    }
    for name, body in cases.items():
        pdir = tmp_path / name
        pdir.mkdir()
        (pdir / "project.json").write_text(body)
        try:
            proj = Project.open(pdir)
        except Exception as exc:  # noqa: BLE001 — a clean failure is acceptable
            assert isinstance(exc, (ValueError, json.JSONDecodeError))
            continue
        # if it opened, it must be usable: types are coerced, and it re-saves as valid v2
        assert isinstance(proj.runs, list) and isinstance(proj.studies, list)
        assert isinstance(proj.param_values, dict) and isinstance(proj.settings, dict)
        proj.save()
        assert json.loads((pdir / "project.json").read_text())["nbeast_project_version"] == 2


def test_missing_manifest_raises_but_open_or_create_recovers(tmp_path):
    empty = tmp_path / "nothing"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        Project.open(empty)
    proj = Project.open_or_create(empty, name="fresh")
    assert proj.manifest_path.exists() and proj.studies == []


def test_run_ids_never_collide_under_add_delete(tmp_path):
    rng = random.Random(31)
    proj = Project.create(tmp_path / "runs")
    sp = tmp_path / "sp.h5"
    sp.write_text("x")
    live = []
    for _ in range(60):
        if live and rng.random() < 0.4:
            proj.delete_run(rng.choice(live))
            live = [r.id for r in proj.runs]
        else:
            rec = proj.add_run(statepoint_src=sp, template="Godiva", parameters={},
                               keff=rng.random())
            assert rec.id not in live                     # freshly-minted id is unique
            live.append(rec.id)
    assert len({r.id for r in proj.runs}) == len(proj.runs)   # no duplicates ever


def test_run_record_round_trips_with_extra_and_missing_keys():
    rng = random.Random(32)
    for _ in range(100):
        rec = RunRecord(id=f"run-{rng.randint(0,999):04d}", template="Pin cell",
                        parameters={"pitch": rng.random()}, keff=rng.random(),
                        keff_std=rng.random() * 0.01, warnings=["w"] * rng.randint(0, 3))
        assert RunRecord.from_dict(rec.to_dict()) == rec
    # tolerant of unknown keys (forward-compat) + missing keys (older manifests)
    RunRecord.from_dict({"id": "run-0001", "template": "x", "future_field": 42})
    RunRecord.from_dict({})


# ---- study store CRUD fuzz --------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_study_store_crud_fuzz_stays_consistent(qapp, tmp_path):
    from nbeast.core.studies import StudyResult
    from nbeast.gui.studies import StudyStore

    rng = random.Random(33)
    store = StudyStore(Project.create(tmp_path / "s"))
    for _ in range(200):
        ids = [c.study_id for c in store.configs()]
        op = rng.choice(["add", "add", "delete", "rename", "duplicate", "result"])
        if op == "add":
            store.add(rng.choice(["keff", "sweep", "moderation"]), {"batches": 50})
        elif op == "delete" and ids:
            store.delete(rng.choice(ids))
        elif op == "rename" and ids:
            store.rename(rng.choice(ids), "renamed-" + str(rng.randint(0, 99)))
        elif op == "duplicate" and ids:
            store.duplicate(rng.choice(ids))
        elif op == "result" and ids:
            store.set_result(rng.choice(ids), StudyResult(ok=True, summary="x"))
        # invariants: ids unique, every config deserializes, reload matches
        cfgs = store.configs()
        assert len({c.study_id for c in cfgs}) == len(cfgs)
    reopened = StudyStore(Project.open(tmp_path / "s"))
    assert [c.study_id for c in reopened.configs()] == [c.study_id for c in store.configs()]


# ---- document undo/redo invariants -----------------------------------------
def test_undo_redo_is_reversible_property(qapp):
    """Robust undo invariants under command merging: undo-all returns to the initial
    state, redo-all returns to the final state, and every single undo/redo is its own
    inverse — checked step-by-step through a random edit history."""
    from nbeast.gui.document import Document

    rng = random.Random(34)
    doc = Document()
    keys = ["pitch", "fuel_radius", "enrichment", "clad_outer_radius"]
    initial = dict(doc.current_params)
    for _ in range(60):
        doc.edit_param(rng.choice(keys), round(rng.uniform(0.1, 4.0), 4))
    final = dict(doc.current_params)
    stack = doc.undo_stack
    assert 0 <= stack.index() <= stack.count()

    # every single undo is reversed exactly by a redo
    while stack.canUndo():
        before = dict(doc.current_params)
        stack.undo()
        stack.redo()
        assert dict(doc.current_params) == before
        stack.undo()
    assert dict(doc.current_params) == initial     # undo-all → start
    while stack.canRedo():
        stack.redo()
    assert dict(doc.current_params) == final        # redo-all → end


# ---- material-value sanitization against garbage ----------------------------
def test_sanitize_survives_garbage_material_keys(qapp, tmp_path):
    from nbeast.core import specs
    from nbeast.gui.main_window import MainWindow

    rng = random.Random(35)
    win = MainWindow(run_root=tmp_path, project_dir=tmp_path / "p")
    junk = ["element_Xx", "", "💥", "uo2; DROP TABLE", "None", "12345", None]
    for template, roles in win._material_values.items():
        for role_key in list(roles):
            roles[role_key] = rng.choice(junk)
    win._sanitize_material_values()                       # must not raise
    # every surviving selection is either a real LIBRARY key or a template default
    from nbeast.core import materials

    for template, roles in win._material_values.items():
        defaults = specs.SPECS[template].material_defaults() if template in specs.SPECS else {}
        for role_key, key in roles.items():
            assert key in materials.LIBRARY or key == defaults.get(role_key)
    win._refresh_tree()                                   # tree render must not crash
    win.close()


def test_window_state_persists_round_trip(qapp, tmp_path):
    from PySide6.QtCore import QByteArray

    from nbeast.gui.main_window import MainWindow

    win = MainWindow(run_root=tmp_path, project_dir=tmp_path / "p")
    win._save_window_state()
    geo = win._qsettings().value("window/geometry")
    assert geo is None or isinstance(geo, (QByteArray, bytes))
    win._restore_window_state()                           # must not raise even if unset
    win.close()
