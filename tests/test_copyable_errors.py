"""Error/status text surfaced in the app is copyable (⌘C / right-click / selection)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_make_selectable_sets_flags(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    from nbeast.gui.uikit import make_selectable

    label = make_selectable(QLabel("Error: something broke"))
    flags = label.textInteractionFlags()
    assert flags & Qt.TextSelectableByMouse
    assert flags & Qt.TextSelectableByKeyboard


def test_copyable_list_copies_selection_and_all(qapp):
    from PySide6.QtWidgets import QApplication

    from nbeast.gui.uikit import CopyableListWidget

    lst = CopyableListWidget()
    for line in ("first", "Error: boom", "third"):
        lst.addItem(line)
    lst.item(1).setSelected(True)
    lst.copy_selected()
    assert QApplication.clipboard().text() == "Error: boom"
    lst.copy_all()
    assert QApplication.clipboard().text() == "first\nError: boom\nthird"
    # no selection → copy_selected falls back to everything
    lst.clearSelection()
    lst.copy_selected()
    assert QApplication.clipboard().text() == "first\nError: boom\nthird"
    lst.close()


def test_ctrl_c_copies(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    from nbeast.gui.uikit import CopyableListWidget

    lst = CopyableListWidget()
    lst.addItem("copy me via keyboard")
    lst.item(0).setSelected(True)
    QApplication.clipboard().clear()
    event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_C, Qt.ControlModifier)
    lst.keyPressEvent(event)
    assert QApplication.clipboard().text() == "copy me via keyboard"
    lst.close()


def test_messages_strip_error_is_copyable(qapp):
    from PySide6.QtWidgets import QApplication

    from nbeast.gui.messages import MessagesStrip
    from nbeast.gui.uikit import CopyableListWidget

    strip = MessagesStrip()
    assert isinstance(strip.list, CopyableListWidget)
    strip.log("Error: reactor exploded", "error")
    assert strip.list.item(0).toolTip() == "Error: reactor exploded"   # full text on hover
    strip.list.copy_all()
    assert "reactor exploded" in QApplication.clipboard().text()
    strip.close()


def test_mainwindow_run_error_lands_in_copyable_log(qapp, tmp_path):
    from PySide6.QtWidgets import QApplication

    from nbeast.gui.main_window import MainWindow

    win = MainWindow(run_root=tmp_path, project_dir=tmp_path / "p")
    win._on_failed("subprocess died: FI_PROVIDER=tcp not found")
    win.messages.list.copy_all()
    assert "subprocess died" in QApplication.clipboard().text()
    win.close()


def test_dialog_status_labels_are_selectable(qapp, tmp_path):
    from PySide6.QtCore import Qt

    from nbeast.gui.data_library import DataLibraryDialog
    from nbeast.gui.main_window import MainWindow
    from nbeast.gui.mgxs_dialog import MgxsDialog
    from nbeast.gui.moderation_dialog import ModerationDialog
    from nbeast.gui.poisoning_dialog import PoisoningDialog
    from nbeast.gui.report_center import ReportCenterDialog
    from nbeast.gui.sweep_dialog import SweepDialog

    win = MainWindow(run_root=tmp_path, project_dir=tmp_path / "p")
    win.set_template("Pin cell")
    for cls in (SweepDialog, ModerationDialog, PoisoningDialog, MgxsDialog, ReportCenterDialog):
        dialog = cls(win, parent=win)
        assert dialog.status.textInteractionFlags() & Qt.TextSelectableByMouse
        dialog.close()
    dl = DataLibraryDialog(active_xml=win._cross_sections, starter_xml=win._starter_xml)
    assert dl.status.textInteractionFlags() & Qt.TextSelectableByMouse
    dl.close()
    win.close()
