"""Report export: a finished run produces a PDF/PNG report, CSV, and the deck."""

import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")
pytest.importorskip("pyvista")
pytest.importorskip("matplotlib")

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


@requires_data
def test_export_report(qapp, tmp_path):
    from PySide6.QtCore import QEventLoop, QTimer

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

    out = win.export_report(tmp_path / "report_out")
    assert out is not None, "export returned None (no result?)"
    for rel in ("report.pdf", "report.png", "spectrum.csv", "openmc_deck/model.xml", "openmc_deck/run.py"):
        assert (out / rel).exists(), f"missing {rel}"
    win.close()
