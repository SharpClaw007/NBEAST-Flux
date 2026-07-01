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


def test_autoinspect_no_manual_inspect_button(qapp):
    """Importing a CAD file should go straight to material selection — the manual
    Inspect button is hidden and inspection auto-triggers."""
    from nbeast.gui.cad_import import CadImportDialog

    dialog = CadImportDialog(cross_sections=None)
    assert dialog.inspect_btn.isHidden()
    dialog.step_edit.setText("/no/such/file.step")
    dialog._inspect()
    assert "does not exist" in dialog.status.text()   # graceful, no crash
    dialog.step_edit.setText("")
    dialog._inspect()                                  # empty path is a no-op
    dialog.close()


def test_cad_dialog_is_nonmodal_single_instance(qapp, tmp_path):
    """The CAD panel is non-modal (so the main 3D viewport stays live for previews,
    which otherwise crashes the GL context) and only one opens at a time."""
    from nbeast.gui.main_window import MainWindow

    win = MainWindow(run_root=tmp_path, project_dir=tmp_path / "p")
    win._open_cad_import()
    assert win._cad_dialog is not None and not win._cad_dialog.isModal()
    first = win._cad_dialog
    win._open_cad_import()
    assert win._cad_dialog is first                    # reused, not stacked
    win.close()                                        # closeEvent tears it down
    assert win._cad_dialog is None


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
