"""Headless smoke tests for the GUI (QT_QPA_PLATFORM=offscreen).

The 3D viewport is a placeholder for now, so no GL context is needed and these
run headlessly. The streaming test exercises the full path: toolbar -> build
model -> RunController/QThread -> Runner subprocess -> live monitor -> k-eff.
"""

import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Skip the whole module (rather than error) if the GUI stack isn't installed.
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

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


def test_mainwindow_constructs(qapp):
    """Window builds with no cross-section data; tree + tabs populate."""
    from nbeast.gui.main_window import MainWindow

    win = MainWindow()
    assert win.windowTitle()
    assert win.model_tree.topLevelItemCount() == 3  # Materials, Geometry, Settings
    assert win.tabs.count() == 3  # Convergence + Flux map + Spectrum

    win.set_template("Godiva")
    # Godiva has a single material -> one child under "Materials".
    materials_node = win.model_tree.topLevelItem(0)
    assert materials_node.text(0) == "Materials"
    assert materials_node.childCount() == 1
    win.close()


@requires_data
def test_run_streams_to_monitor(qapp, tmp_path):
    """A short Godiva run streams batches into the monitor and yields a k-eff."""
    from PySide6.QtCore import QEventLoop, QTimer

    from nbeast.gui.main_window import MainWindow

    win = MainWindow(run_root=tmp_path)
    win.set_template("Godiva")
    win.batches_spin.setValue(30)
    win.particles_spin.setValue(1000)

    loop = QEventLoop()
    win.controller.finished.connect(lambda *_: loop.quit())
    win.controller.failed.connect(lambda *_: loop.quit())
    QTimer.singleShot(120_000, loop.quit)  # safety net

    win.start_run()
    loop.exec()

    assert win.last_result is not None, "run did not finish"
    assert win.last_result.error is None, win.last_result.error
    assert win.monitor.point_count > 0, "no batches reached the monitor"
    assert win.last_result.keff is not None
    assert abs(win.last_result.keff - 1.0) < 0.03  # Godiva ~ critical
    win.close()
