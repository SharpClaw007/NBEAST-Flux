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


def test_setup_dialog_constructs(qapp):
    from nbeast.gui.cad_setup import CadSetupDialog

    dialog = CadSetupDialog()
    assert dialog.install_btn.isEnabled()
    dialog._append("log line")
    assert "log line" in dialog.log.toPlainText()
    dialog.close()


def test_flux_map_array_headless(qapp):
    from nbeast.gui.viewport3d import FluxViewport

    view = FluxViewport()
    # under the offscreen platform this falls back to the placeholder (no crash)
    view.show_field_array([[0.1, 0.2], [0.3, 0.4]], (0, 0), (1, 1), title="CAD flux map")
    assert "CAD flux map" in view._placeholder.text()
    view.close()


def test_volume_render_headless(qapp):
    from nbeast.gui.viewport3d import FluxViewport

    view = FluxViewport()
    view.show_field_volume([1.0] * 8, (2, 2, 2), (0, 0, 0), (1, 1, 1), title="Scalar flux")
    assert "Scalar flux" in view._placeholder.text()
    view.close()
