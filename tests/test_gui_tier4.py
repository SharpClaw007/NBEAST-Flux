"""Headless GUI checks for Tier-4: fixed-source handling, richer result fields,
and the multigroup / depletion dialogs (data-free)."""

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


def _win(tmp_path):
    from nbeast.gui.main_window import MainWindow

    return MainWindow(run_root=tmp_path, project_dir=tmp_path / "p")


def test_shield_template_builds_fixed_source(qapp, tmp_path):
    win = _win(tmp_path)
    win.set_template("Shield slab")
    assert win._is_fixed_source
    model = win._build_model()
    assert model.settings.run_mode == "fixed source"
    assert model.settings.entropy_mesh is None        # no source-convergence diagnostic
    names = [t.name for t in model.tallies]
    assert "dose_mesh" in names                        # shielding dose map present
    win.close()


def test_monitor_handles_missing_keff(qapp):
    from nbeast.gui.monitor import ConvergenceMonitor

    mon = ConvergenceMonitor()
    mon.add_point(1, None, None, None)                 # fixed-source: no k-eff
    mon.add_point(2, None, None, None)
    assert mon.point_count == 2
    assert mon._keffs == []                            # nothing plotted on the k curve
    mon.close()


def test_results_picker_has_richer_fields(qapp, tmp_path):
    from PySide6.QtCore import Qt

    win = _win(tmp_path)
    scores = {win.results_list.item(i).data(Qt.UserRole)
              for i in range(win.results_list.count())}
    assert {"absorption", "nu-fission", "heating", "dose"} <= scores
    win.close()


def test_field_source_mapping(qapp, tmp_path):
    win = _win(tmp_path)
    assert win._field_source("dose") == ("dose_mesh", "flux", "dose")
    assert win._field_source("heating") == ("flux_mesh", "heating", "heating")
    assert win._field_source("flux_rel_err") == ("flux_mesh", "flux", "flux")
    win.close()


def test_mgxs_dialog_gating(qapp, tmp_path):
    from nbeast.gui.mgxs_dialog import MgxsDialog

    win = _win(tmp_path)
    win.set_template("Pin cell")
    md = MgxsDialog(win, parent=win)
    assert md.structure_combo.count() == 4
    assert md.run_btn.isEnabled()
    md.close()

    win.set_template("Shield slab")
    md2 = MgxsDialog(win, parent=win)
    assert not md2.run_btn.isEnabled()                 # mgxs needs an eigenvalue model
    md2.close()
    win.close()


def test_depletion_setup_dialog_builds(qapp, tmp_path, monkeypatch):
    from nbeast.core import depletion
    from nbeast.gui.depletion_setup import DepletionSetupDialog

    monkeypatch.setattr(depletion, "chain_path", lambda: None)
    dialog = DepletionSetupDialog()
    assert "No depletion chain" in dialog.status.text()
    dialog.close()


def test_depletion_dialog_gating(qapp, tmp_path):
    from nbeast.gui.depletion_dialog import DepletionDialog

    win = _win(tmp_path)
    win.set_template("Pin cell")
    dd = DepletionDialog(win, parent=win)
    assert dd.run_btn.isEnabled()
    assert dd.integrator_combo.count() == 2
    assert len(dd._config().timesteps_days) == dd.steps_spin.value()
    dd.close()

    win.set_template("Shield slab")
    dd2 = DepletionDialog(win, parent=win)
    assert not dd2.run_btn.isEnabled()                 # no fuel to deplete
    dd2.close()
    win.close()
