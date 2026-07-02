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

    combo = dialog.table.cellWidget(0, 1)
    assert combo.count() == len(cad.MATERIAL_PRESETS)
    assert combo.currentData() in cad.MATERIAL_PRESETS
    # each solid gets a distinct default material + its cell is tinted that colour
    assert dialog.table.cellWidget(0, 1).currentData() != dialog.table.cellWidget(1, 1).currentData()
    assert dialog.table.item(0, 0).background().color().isValid()
    dialog.close()


def test_dialog_embeds_colour_coded_preview(qapp):
    """The importer shows its own preview pane and recolors a solid when its material
    changes — so it's clear what material maps to which part."""
    from nbeast.gui.cad_import import CadImportDialog

    dialog = CadImportDialog(cross_sections=None)
    assert hasattr(dialog, "preview_label")             # preview lives in the dialog
    dialog._on_inspected(3)
    # distinct default materials so the parts read apart at a glance
    tags = [dialog.table.cellWidget(i, 1).currentData() for i in range(3)]
    assert len(set(tags)) == 3
    before = dialog.table.item(0, 0).background().color().name()
    # rendering with solids present must not raise (headless -> placeholder text)
    dialog._stls = ["a.stl", "b.stl", "c.stl"]
    dialog._render_preview()
    assert "solid" in dialog.preview_label.text().lower()
    # changing a material recolors that solid's cell and re-renders (no crash)
    combo = dialog.table.cellWidget(0, 1)
    combo.setCurrentIndex((combo.currentIndex() + 1) % combo.count())
    assert dialog.table.item(0, 0).background().color().name() != before
    dialog.close()


def test_cad_results_render_volumetrically(qapp, tmp_path):
    """A CAD run offers a 2D-slice + a 3D entry per field; the 3D entry routes through
    the volumetric renderer (on the geometry)."""
    from nbeast.gui.main_window import MainWindow

    win = MainWindow(run_root=tmp_path, project_dir=tmp_path / "p")
    win._statepoint = "sp.h5"
    win._cad_result = True
    win._rebuild_results_list()
    scores = set(win.model_tree.result_scores())
    assert {"flux", "flux__3d", "fission", "fission__3d"} <= scores

    routed = []
    win._show_cad_field = lambda score, switch_tab=True: routed.append(score)
    for base in ("flux", "fission", "dose", "heating"):
        win._on_result_selected(base + "__3d")
    assert routed == ["flux", "fission", "dose", "heating"]
    win.close()


def test_viewport_finalize_is_idempotent(qapp):
    """finalize() releases the VTK interactor and is safe to call repeatedly / early —
    the dialog uses it on close to avoid a segfault when the embedded view is destroyed."""
    from nbeast.gui.viewport3d import FluxViewport

    view = FluxViewport()
    view.finalize()          # no interactor yet — must not raise
    view.finalize()
    assert view._interactor is None
    view.close()


def test_cad_dialog_close_is_clean(qapp):
    from nbeast.gui.cad_import import CadImportDialog

    dialog = CadImportDialog(cross_sections=None)
    dialog._on_inspected(2)
    dialog.close()           # closeEvent -> teardown + preview finalize, no crash


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


def test_worker_callback_runs_on_main_thread(qapp):
    """Regression: the 3D preview connected a lambda to the worker's `done` signal,
    which PySide wired as a DIRECT connection — the callback (and its _teardown,
    which waits on + destroys the thread) ran on the worker thread and aborted the
    app with 'QThread: Destroyed while thread is still running'. Callbacks must run
    on the GUI thread regardless of lambda vs. bound method."""
    from PySide6.QtCore import QEventLoop, QThread, QTimer
    from nbeast.gui.cad_import import CadImportDialog

    dialog = CadImportDialog(cross_sections=None)
    seen = {}
    loop = QEventLoop()

    def on_done(value):
        seen["value"] = value
        seen["on_main"] = QThread.currentThread() == qapp.thread()
        dialog._teardown()          # the exact call that crashed off-main
        loop.quit()

    dialog._start(lambda: 42, lambda v: on_done(v))   # lambda on_done = old crash path
    QTimer.singleShot(4000, loop.quit)                # safety net
    loop.exec()

    assert seen.get("value") == 42
    assert seen.get("on_main") is True                # ran on the GUI thread → no abort
    dialog.close()


def test_setup_dialog_constructs(qapp):
    from nbeast.gui.cad_setup import CadSetupDialog

    dialog = CadSetupDialog()
    assert dialog.install_btn.isEnabled()
    dialog._append("log line")
    assert "log line" in dialog.log.toPlainText()
    dialog.close()


def test_material_legend_entries(qapp):
    """The CAD legend collapses per-solid colours/labels into unique rows with counts."""
    from nbeast.gui.viewport3d import FluxViewport

    entries = FluxViewport._material_legend_entries(
        ["#c9a227", "#7fb8d8", "#7fb8d8"], ["HEU", "Water", "Water"]
    )
    assert entries == [("HEU", "#c9a227"), ("Water (×2)", "#7fb8d8")]
    assert FluxViewport._material_legend_entries(["#fff"], None) == []
    # show_cad with labels is safe headless (falls back to placeholder, no crash)
    view = FluxViewport()
    view.show_cad(["a.stl", "b.stl"], ["#c9a227", "#7fb8d8"], labels=["HEU", "Water"])
    view.close()


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
