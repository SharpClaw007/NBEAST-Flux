"""G0 foundation: the Document, undo/redo, and project schema v2 migration."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


# ---- Document + undo stack --------------------------------------------------
def test_edit_param_is_undoable(qapp):
    from nbeast.gui.document import Document

    doc = Document()
    template = doc.template
    original = doc.param_values[template]["pitch"]
    doc.edit_param("pitch", 1.40)
    assert doc.param_values[template]["pitch"] == 1.40
    doc.undo_stack.undo()
    assert doc.param_values[template]["pitch"] == original
    doc.undo_stack.redo()
    assert doc.param_values[template]["pitch"] == 1.40


def test_consecutive_edits_of_one_field_merge(qapp):
    """Dragging a spinbox emits many valueChanged — they must collapse into ONE undo
    step whose undo restores the pre-drag value."""
    from nbeast.gui.document import Document

    doc = Document()
    original = doc.current_params["pitch"]
    for v in (1.30, 1.35, 1.40, 1.45):
        doc.edit_param("pitch", v)
    assert doc.undo_stack.count() == 1
    doc.undo_stack.undo()
    assert doc.current_params["pitch"] == original


def test_edits_of_different_fields_do_not_merge(qapp):
    from nbeast.gui.document import Document

    doc = Document()
    doc.edit_param("pitch", 1.40)
    doc.edit_param("fuel_radius", 0.41)
    assert doc.undo_stack.count() == 2
    doc.undo_stack.undo()                       # undoes fuel_radius only
    assert doc.current_params["pitch"] == 1.40


def test_edit_material_is_undoable_and_signals(qapp):
    from nbeast.gui.document import Document

    doc = Document()
    events = []
    doc.material_changed.connect(lambda t, r: events.append((t, r)))
    old = doc.current_materials["fuel"]
    doc.edit_material("fuel", "u_metal")
    assert doc.current_materials["fuel"] == "u_metal"
    assert events and events[-1][1] == "fuel"
    doc.undo_stack.undo()
    assert doc.current_materials["fuel"] == old


def test_noop_edit_pushes_nothing(qapp):
    from nbeast.gui.document import Document

    doc = Document()
    doc.edit_param("pitch", doc.current_params["pitch"])
    doc.edit_material("fuel", doc.current_materials["fuel"])
    assert doc.undo_stack.count() == 0


# ---- MainWindow integration ---------------------------------------------------
def test_mainwindow_edits_route_through_undo(qapp, tmp_path):
    from nbeast.gui.main_window import MainWindow

    win = MainWindow(run_root=tmp_path, project_dir=tmp_path / "p")
    win.set_template("Pin cell")
    original = win._param_values["Pin cell"]["pitch"]
    win.set_param("pitch", 1.5)
    assert win._param_values["Pin cell"]["pitch"] == 1.5
    win.doc.undo_stack.undo()
    assert win._param_values["Pin cell"]["pitch"] == original
    # tree reflects the undone value (refresh happens via the doc signal)
    texts = []
    root = win.model_tree.model_root
    for i in range(root.childCount()):
        top = root.child(i)
        texts += [top.child(j).text(0) for j in range(top.childCount())]
    assert any(f"{original:.2f}".rstrip("0") in t or f"{original}" in t
               for t in texts if "pitch" in t.lower() or "Pitch" in t)
    win.close()


def test_mainwindow_material_undo(qapp, tmp_path):
    from nbeast.gui.main_window import MainWindow

    win = MainWindow(run_root=tmp_path, project_dir=tmp_path / "p")
    win.set_template("Pin cell")
    old = win._material_values["Pin cell"]["fuel"]
    win._on_material_selected("fuel", "u_metal")
    assert win._material_values["Pin cell"]["fuel"] == "u_metal"
    win.doc.undo_stack.undo()
    assert win._material_values["Pin cell"]["fuel"] == old
    win.close()


# ---- project schema v2 --------------------------------------------------------
def test_project_v2_round_trips_studies(tmp_path):
    from nbeast.core.project import Project

    proj = Project.create(tmp_path / "p2", name="v2")
    proj.studies = [{"kind": "sweep", "name": "pitch sweep", "params": {"key": "pitch"}}]
    proj.save()
    reopened = Project.open(tmp_path / "p2")
    assert reopened.studies == proj.studies
    assert json.loads(reopened.manifest_path.read_text())["nbeast_project_version"] == 2


def test_v1_project_migrates_transparently(tmp_path):
    """A captured v1 manifest (no studies key, version 1) opens cleanly with
    studies == [] and is rewritten as v2 on the next save."""
    from nbeast.core.project import Project

    pdir = tmp_path / "old"
    pdir.mkdir()
    (pdir / "project.json").write_text(json.dumps({
        "nbeast_project_version": 1,
        "name": "legacy",
        "created_utc": "2026-06-01T00:00:00Z",
        "template": "Pin cell",
        "param_values": {"Pin cell": {"pitch": 1.26}},
        "material_values": {"Pin cell": {"fuel": "uo2"}},
        "settings": {"batches": 100},
        "runs": [],
    }))
    proj = Project.open(pdir)
    assert proj.studies == []
    assert proj.template == "Pin cell"
    proj.save()
    assert json.loads((pdir / "project.json").read_text())["nbeast_project_version"] == 2
