"""Phase 3 viz: a GUI run produces a spectrum + flux mesh, renderable headlessly.

The embedded 3D QtInteractor needs a real display, so it's verified manually; here
we validate everything up to the pixels: statepoint, spectrum data, flux VTK, and
an off-screen flux PNG. FluxViewport is checked to be headless-safe.
"""

import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")
pytest.importorskip("pyvista")

_XS = os.environ.get("OPENMC_CROSS_SECTIONS")
requires_data = pytest.mark.skipif(
    not (_XS and pathlib.Path(_XS).exists()),
    reason="OPENMC_CROSS_SECTIONS not set or missing",
)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_flux_viewport_headless_safe(qapp):
    """The 3D viewport must not crash under headless mode, even given a path."""
    from nbeast.gui.viewport3d import FluxViewport

    view = FluxViewport()
    view.show_field("/does/not/matter.vtk", scalar="flux", title="Flux")  # guard returns first
    assert view._interactor is None  # no GL widget created headlessly
    view.close()


@requires_data
def test_run_produces_spectrum_flux_and_png(qapp, tmp_path):
    from PySide6.QtCore import QEventLoop, QTimer

    from nbeast.gui import render
    from nbeast.gui.main_window import MainWindow

    win = MainWindow(run_root=tmp_path)
    win.set_template("Pin cell")
    win.batches_spin.setValue(40)
    win.particles_spin.setValue(1000)

    loop = QEventLoop()
    win.controller.finished.connect(lambda *_: loop.quit())
    win.controller.failed.connect(lambda *_: loop.quit())
    QTimer.singleShot(120_000, loop.quit)
    win.start_run()
    loop.exec()

    result = win.last_result
    assert result is not None and result.error is None
    assert result.statepoint and pathlib.Path(result.statepoint).exists()
    assert win.spectrum_view.has_data, "spectrum not populated"

    vtk = pathlib.Path(result.statepoint).parent / "flux.vtk"
    assert vtk.exists(), "flux VTK not written"

    png = render.flux_to_png(vtk, tmp_path / "flux.png")
    assert png.exists() and png.stat().st_size > 0

    # Results field toggle: fission map is available and renders.
    assert all(not i.isDisabled() for i in win.model_tree.result_items())
    win._show_field("fission", switch_tab=False)
    fission_vtk = pathlib.Path(result.statepoint).parent / "fission.vtk"
    assert fission_vtk.exists(), "fission VTK not written"
    fpng = render.flux_to_png(
        fission_vtk, tmp_path / "fission.png", scalar="fission", title="Fission rate"
    )
    assert fpng.exists() and fpng.stat().st_size > 0
    win.close()
