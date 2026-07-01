"""Ultimate headless smoke test — every template, settings edits, material edge
cases, the CAD template + guards, rapid switching, nonsensical inputs, and every
dialog construction. Data-free (no OpenMC runs); catches wiring/mismatch bugs."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from nbeast.core import specs  # noqa: E402

REAL_TEMPLATES = list(specs.SPECS.keys())          # Pin cell, Godiva, Assembly, Shield
EIGEN_TEMPLATES = [t for t in REAL_TEMPLATES if specs.SPECS[t].run_mode == "eigenvalue"]


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _no_modal_dialogs(monkeypatch):
    """Neutralize every blocking dialog so the harness never hangs."""
    from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No, raising=False)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok, raising=False)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: "")
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("", False))


def _win(tmp_path):
    from nbeast.gui.main_window import MainWindow

    win = MainWindow(run_root=tmp_path, project_dir=tmp_path / "proj")
    # CAD import/setup are modal + env-dependent; stub them so selecting CAD is safe.
    win._open_cad_import = lambda: win.statusBar().showMessage("cad dialog (stubbed)")
    win._open_cad_setup = lambda: None
    return win


def _reset_materials(win):
    if win.spec is not None:
        win._material_values[win._template] = win.spec.material_defaults()


# --------------------------------------------------------------------------
def test_every_template_builds(qapp, tmp_path):
    win = _win(tmp_path)
    for t in REAL_TEMPLATES:
        win.set_template(t)
        _reset_materials(win)
        model = win._build_model()
        assert model.settings.run_mode == specs.SPECS[t].run_mode
        assert len(model.materials) >= 1
    win.close()


def test_settings_editors_extremes(qapp, tmp_path):
    win = _win(tmp_path)
    settings = next(win.model_tree.topLevelItem(i)
                    for i in range(win.model_tree.topLevelItemCount())
                    if win.model_tree.topLevelItem(i).text(0) == "Settings")
    win._on_tree_click(settings, 0)
    assert win.properties.rowCount() == 4
    # push editors past their bounds — spin boxes must clamp, not crash
    win._batches_editor.setValue(10 ** 9)
    assert win.batches_spin.value() == win.batches_spin.maximum()
    win._batches_editor.setValue(-5)
    assert win.batches_spin.value() == win.batches_spin.minimum()
    win._particles_editor.setValue(10 ** 9)   # within int32, far above the spin's max
    assert win.particles_spin.value() == win.particles_spin.maximum()
    win.close()


def test_param_editors_clamp_nonsensical_input(qapp, tmp_path):
    from PySide6.QtWidgets import QDoubleSpinBox

    win = _win(tmp_path)
    win.set_template("Pin cell")
    geom = next(win.model_tree.topLevelItem(i)
                for i in range(win.model_tree.topLevelItemCount())
                if win.model_tree.topLevelItem(i).text(0) == "Geometry")
    win._on_tree_click(geom, 0)
    editor = next(win.properties.cellWidget(r, 1) for r in range(win.properties.rowCount())
                  if isinstance(win.properties.cellWidget(r, 1), QDoubleSpinBox))
    editor.setValue(1e9)      # absurd pitch
    assert editor.value() == editor.maximum()
    editor.setValue(-1e9)
    assert editor.value() == editor.minimum()
    # model still builds at the clamped extreme
    win._build_model()
    win.close()


def test_material_swap_and_needs_data_run_guard(qapp, tmp_path):
    from nbeast.core import materials

    win = _win(tmp_path)
    win._cross_sections = os.environ.get("OPENMC_CROSS_SECTIONS")
    win.set_template("Pin cell")
    _reset_materials(win)
    # swap to an available material — build reflects it
    win._on_material_selected("fuel", "u_metal")
    assert any("U metal" in m.name for m in win._build_model().materials)
    # a needs-data material blocks the run with a clear message (no crash)
    if win._cross_sections:  # only meaningful when a real library is active
        win._on_material_selected("clad", "steel_304")
        win.start_run()
        assert not win.controller.running
    win.close()


def test_cad_template_guards(qapp, tmp_path):
    from nbeast.gui.main_window import CAD_TEMPLATE

    win = _win(tmp_path)
    win.set_template(CAD_TEMPLATE)
    assert win._is_cad and win.spec is None
    groups = [win.model_tree.topLevelItem(i).text(0)
              for i in range(win.model_tree.topLevelItemCount())]
    assert groups == ["Materials", "Geometry", "Settings"]
    # parametric-only features must no-op gracefully for CAD (no crash, no dialog)
    win._open_sweep()
    win._open_mgxs()
    win._open_depletion()
    win.show_tracks()
    win.start_run()          # routes to the (stubbed) CAD dialog
    win.export_report(tmp_path / "rep")   # guarded — just a message
    # settings still editable under CAD
    settings = next(win.model_tree.topLevelItem(i)
                    for i in range(win.model_tree.topLevelItemCount())
                    if win.model_tree.topLevelItem(i).text(0) == "Settings")
    win._on_tree_click(settings, 0)
    assert win.properties.rowCount() == 4
    win.close()


def test_analysis_tools_guarded_off_eigenvalue(qapp, tmp_path):
    """Sweep / multigroup / depletion are eigenvalue-only — they must refuse the
    fixed-source shield and the CAD template without opening (or crashing)."""
    from nbeast.gui.main_window import CAD_TEMPLATE

    win = _win(tmp_path)
    for template in ("Shield slab", CAD_TEMPLATE):
        win.set_template(template)
        for opener in (win._open_sweep, win._open_mgxs, win._open_depletion):
            opener()
            assert not win.controller.running
            msg = win.statusBar().currentMessage().lower()
            assert "eigenvalue" in msg or "parametric template" in msg
    win.close()


def test_rapid_template_switching(qapp, tmp_path):
    from nbeast.gui.main_window import CAD_TEMPLATE

    win = _win(tmp_path)
    sequence = [*REAL_TEMPLATES, CAD_TEMPLATE, *reversed(REAL_TEMPLATES), CAD_TEMPLATE, "Pin cell"]
    for t in sequence:
        win.set_template(t)
    assert win._template == "Pin cell" and not win._is_cad
    win._build_model()
    win.close()


def test_all_dialogs_construct_per_eigen_template(qapp, tmp_path):
    from nbeast.gui.compare_dialog import CompareDialog
    from nbeast.gui.mgxs_dialog import MgxsDialog
    from nbeast.gui.sweep_dialog import SweepDialog
    from nbeast.core.project import Project, RunRecord

    win = _win(tmp_path)
    for t in EIGEN_TEMPLATES:
        win.set_template(t)
        _reset_materials(win)
        SweepDialog(win, parent=win).close()
        MgxsDialog(win, parent=win).close()
    # compare dialog with two fabricated records
    proj = Project.create(tmp_path / "cmp")
    a = RunRecord(id="run-0001", template="Godiva", parameters={"radius": 8.5}, keff=0.97, keff_std=0.001)
    b = RunRecord(id="run-0002", template="Godiva", parameters={"radius": 9.0}, keff=1.03, keff_std=0.001)
    CompareDialog(a, b, proj).close()
    win.close()


def test_load_examples_and_history(qapp, tmp_path):
    win = _win(tmp_path)
    for key in ("godiva", "pincell", "assembly", "shield"):
        win.load_example(key)
    # archive a fabricated run into the project + reflect in history
    sp = tmp_path / "sp.h5"
    sp.write_text("x")
    win.project.add_run(statepoint_src=sp, template="Godiva", parameters={"radius": 8.7},
                        keff=0.998, keff_std=0.0009)
    win._refresh_history()
    assert win.history_panel.list.count() == 1
    win.close()
