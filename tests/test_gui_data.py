"""Data-manager dialog: token parsing + headless construction."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_split_tokens():
    from nbeast.gui.data_manager import _split_tokens

    elements, nuclides = _split_tokens("U O H Zr Pu239 B10")
    assert elements == ["U", "O", "H", "Zr"]
    assert nuclides == ["Pu239", "B10"]


def test_dialog_constructs_and_presets(qapp):
    from nbeast.gui.data_manager import DataManagerDialog

    dialog = DataManagerDialog(active_xml="/tmp/example/cross_sections.xml")
    assert dialog.elements_edit.text(), "default preset should populate elements"
    dialog.preset_combo.setCurrentText("Actinides")
    assert "Pu" in dialog.elements_edit.text()
    dialog.close()
