"""Moderation-curve dialog + fixed-source auto-normalization (headless, data-free)."""

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


def test_moderation_dialog_constructs_for_moderated_templates(qapp, tmp_path):
    from nbeast.gui.moderation_dialog import ModerationDialog

    win = _win(tmp_path)
    win.set_template("Pin cell")
    dialog = ModerationDialog(win)
    knobs = [dialog.knob_combo.itemData(i) for i in range(dialog.knob_combo.count())]
    assert "density" in knobs and "pitch" in knobs
    # density knob defaults to 0..100 %
    dialog._on_knob_changed()
    assert dialog.lo_spin.value() == 0.0 and dialog.hi_spin.value() == 100.0
    # critical-crossing detector interpolates k=1 between bracketing points
    dialog._points = [(10.0, 0.8, 0.0), (30.0, 1.2, 0.0)]
    crossings = dialog._critical_crossings()
    assert crossings and abs(crossings[0] - 20.0) < 1e-9
    dialog.close()
    win.close()


def test_moderation_gated_off_non_moderated(qapp, tmp_path):
    win = _win(tmp_path)
    for template in ("Godiva", "Shield slab"):
        win.set_template(template)
        win._open_moderation()
        assert not win.controller.running   # refused, no dialog/run
    win.close()


def test_poisoning_dialog_gates_on_data_and_template(qapp, tmp_path):
    from nbeast.gui.poisoning_dialog import PoisoningDialog

    win = _win(tmp_path)
    win.set_template("Pin cell")
    dialog = PoisoningDialog(win)
    # bundled library lacks Xe/Sm → run disabled, download offered
    assert not dialog.run_btn.isEnabled()
    assert not dialog.download_btn.isHidden()
    # default is a finite operating flux (not saturation); saturation is the last option
    assert dialog.level_combo.currentData() == 3e13
    # the worker builds the three cases: clean, +Sm, +Xe+Sm
    from nbeast.gui.poisoning_dialog import _PoisonWorker

    worker = _PoisonWorker(
        spec=win.spec, base=dict(win._param_values["Pin cell"]),
        mats=dict(win._material_values["Pin cell"]), batches=20, particles=100,
        inactive=5, seed=1, flux=3e13, run_root=tmp_path, cross_sections=win._cross_sections)
    nuclides = [set().union(*[m.get_nuclides() for m in worker._build(p).materials])
                for p in (None, (0.0, 1e-4), (1e-5, 1e-4))]
    assert "Xe135" not in nuclides[0] and "Sm149" not in nuclides[0]
    assert "Sm149" in nuclides[1] and "Xe135" not in nuclides[1]
    assert {"Xe135", "Sm149"} <= nuclides[2]
    dialog.close()
    # not applicable to a fast metal / fixed source
    for template in ("Godiva", "Shield slab"):
        win.set_template(template)
        win._open_poisoning()
        assert not win.controller.running
    win.close()


def test_analysis_panel_replaces_menu_and_gates_per_template(qapp, tmp_path):
    from nbeast.gui.main_window import CAD_TEMPLATE

    win = _win(tmp_path)
    # the Analysis menu is gone — the tools live in the Analysis panel
    assert not any("Analysis" in a.text() for a in win.menuBar().actions())
    panel = win.analysis_panel
    assert set(panel._buttons) == {"sweep", "moderation", "poisoning", "mgxs", "depletion"}

    def enabled():
        return {k: panel._buttons[k].isEnabled() for k in panel._buttons}

    win.set_template("Pin cell")
    assert all(enabled().values())                    # everything applies to a thermal pin
    win.set_template("Godiva")
    e = enabled()
    assert e["sweep"] and e["mgxs"] and not e["moderation"] and not e["poisoning"]
    win.set_template("Shield slab")
    assert not any(enabled().values())                # fixed source: no analysis applies
    win.set_template(CAD_TEMPLATE)
    assert not any(enabled().values())                # CAD: no parametric analysis
    win.close()


def test_fixed_source_uses_source_strength(qapp, tmp_path):
    win = _win(tmp_path)

    def norm_row():
        s = next(win.model_tree.topLevelItem(i)
                 for i in range(win.model_tree.topLevelItemCount())
                 if win.model_tree.topLevelItem(i).text(0) == "Settings")
        win._on_tree_click(s, 0)
        return win.properties.item(4, 0).text(), win.properties.cellWidget(4, 1)

    # eigenvalue template -> reactor power
    win.set_template("Pin cell")
    label, widget = norm_row()
    assert "power" in label.lower()
    widget.setValue(65000.0)
    assert win._absolute_units() and win._power_w == 65000.0

    # fixed-source template -> source strength (n/s)
    win.set_template("Shield slab")
    label, widget = norm_row()
    assert "source strength" in label.lower()
    assert not win._absolute_units()
    widget.setValue(1e10)
    assert win._absolute_units() and win._source_strength == 1e10
    assert "absolute" not in win._field_bar_title("flux") or "n·cm" in win._field_bar_title("flux")
    win.close()
