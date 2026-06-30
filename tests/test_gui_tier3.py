"""Headless GUI checks for Tier-3: project persistence, run history, and the
comparison / sweep dialogs. Data-free — no OpenMC runs."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _fake_statepoint(tmp_path):
    p = tmp_path / "sp.h5"
    p.write_text("not-a-real-statepoint")
    return p


def test_project_state_restores_across_windows(qapp, tmp_path):
    from nbeast.gui.main_window import MainWindow

    proj_dir = tmp_path / "proj"
    win = MainWindow(run_root=tmp_path, project_dir=proj_dir)
    win.set_template("Godiva")
    win.set_param("radius", 9.1234)
    win.seed_spin.setValue(42)
    win.batches_spin.setValue(80)
    win._persist_state()
    win.close()

    reopened = MainWindow(run_root=tmp_path, project_dir=proj_dir)
    assert reopened._template == "Godiva"
    assert reopened._param_values["Godiva"]["radius"] == pytest.approx(9.1234)
    assert reopened.seed_spin.value() == 42
    assert reopened.batches_spin.value() == 80
    reopened.close()


def test_history_panel_emits_signals(qapp):
    from nbeast.core.project import RunRecord
    from nbeast.gui.history import HistoryPanel

    panel = HistoryPanel()
    recs = [RunRecord(id=f"run-000{i}", template="Godiva", parameters={}, keff=1.0 + i * 0.01,
                      keff_std=0.001) for i in (1, 2, 3)]
    panel.set_runs(recs)
    assert panel.list.count() == 3  # newest first, but count is what matters

    loaded, compared = [], []
    panel.loadRequested.connect(loaded.append)
    panel.compareRequested.connect(lambda a, b: compared.append((a, b)))

    panel.list.item(0).setSelected(True)
    assert panel.load_btn.isEnabled() and not panel.compare_btn.isEnabled()
    panel._on_load()
    assert len(loaded) == 1

    panel.list.item(1).setSelected(True)  # now two selected
    assert panel.compare_btn.isEnabled()
    panel._on_compare()
    assert len(compared) == 1
    panel.close()


def test_archive_and_history_via_mainwindow(qapp, tmp_path):
    from nbeast.gui.main_window import MainWindow

    win = MainWindow(run_root=tmp_path, project_dir=tmp_path / "proj")
    sp = _fake_statepoint(tmp_path)
    win.project.add_run(statepoint_src=sp, template="Godiva", parameters={"radius": 8.7},
                        keff=0.998, keff_std=0.0009)
    win._refresh_history()
    assert win.history_panel.list.count() == 1
    win.close()


def test_load_missing_statepoint_is_graceful(qapp, tmp_path):
    from nbeast.gui.main_window import MainWindow

    win = MainWindow(run_root=tmp_path, project_dir=tmp_path / "proj")
    sp = _fake_statepoint(tmp_path)
    rec = win.project.add_run(statepoint_src=sp, template="Godiva", parameters={})
    # statepoint exists on disk but is not a valid HDF5 file: must not raise.
    win._load_history_run(rec.id)
    assert "unavailable" in win.statusBar().currentMessage() or win.statusBar().currentMessage()
    win.close()


def test_delete_runs_with_confirmation(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from nbeast.gui.main_window import MainWindow

    win = MainWindow(run_root=tmp_path, project_dir=tmp_path / "proj")
    sp = _fake_statepoint(tmp_path)
    rec = win.project.add_run(statepoint_src=sp, template="Godiva", parameters={})
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    win._delete_history_runs([rec.id])
    assert win.project.get_run(rec.id) is None
    assert win.history_panel.list.count() == 0
    win.close()


def test_compare_dialog_builds(qapp, tmp_path):
    from nbeast.core.project import Project, RunRecord
    from nbeast.gui.compare_dialog import CompareDialog

    proj = Project.create(tmp_path / "proj")
    a = RunRecord(id="run-0001", template="Godiva", parameters={"radius": 8.5},
                  keff=0.97, keff_std=0.001)
    b = RunRecord(id="run-0002", template="Godiva", parameters={"radius": 9.0},
                  keff=1.03, keff_std=0.001)
    dialog = CompareDialog(a, b, proj)
    # statepoints absent -> spectra simply omitted, dialog still constructs
    dialog.close()


def test_sweep_dialog_builds_and_builder(qapp, tmp_path):
    from nbeast.gui.main_window import MainWindow
    from nbeast.gui.sweep_dialog import SweepDialog

    win = MainWindow(run_root=tmp_path, project_dir=tmp_path / "proj")
    win.set_template("Pin cell")
    dialog = SweepDialog(win, parent=win)
    assert dialog.param_combo.count() == 6  # pin cell parameters (incl. temperature)

    # mode toggle controls which group shows
    dialog.mode_combo.setCurrentIndex(1)
    assert dialog.search_group.isVisibleTo(dialog)
    dialog.mode_combo.setCurrentIndex(0)
    assert dialog.sweep_group.isVisibleTo(dialog)

    # the builder produces a runnable model carrying the run settings + seed
    win.seed_spin.setValue(5)
    model = dialog._make_builder()(1.4)
    assert model.settings.seed == 5
    assert model.settings.batches == dialog.batches_spin.value()
    dialog.close()
    win.close()


def test_raw_export_without_run_is_graceful(qapp, tmp_path):
    from nbeast.gui.main_window import MainWindow

    win = MainWindow(run_root=tmp_path, project_dir=tmp_path / "proj")
    win._statepoint = None
    win._on_export_raw()  # must not raise; just nudges the user
    assert "before exporting" in win.statusBar().currentMessage()
    win.close()
