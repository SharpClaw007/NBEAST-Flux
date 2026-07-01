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
