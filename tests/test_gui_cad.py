"""CAD import dialog: headless construction + per-solid material table."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_dialog_constructs_and_populates(qapp):
    from nbeast.core import cad
    from nbeast.gui.cad_import import CadImportDialog

    dialog = CadImportDialog(cross_sections="/tmp/x.xml")
    assert dialog.table.rowCount() == 0
    assert not dialog.run_btn.isEnabled()

    # simulate an inspect result of 2 solids
    dialog._on_inspected(2)
    assert dialog.table.rowCount() == 2
    assert dialog.run_btn.isEnabled()
    assert dialog.preview_btn.isEnabled()

    combo = dialog.table.cellWidget(0, 1)
    assert combo.count() == len(cad.MATERIAL_PRESETS)
    assert combo.currentData() in cad.MATERIAL_PRESETS
    dialog.close()
