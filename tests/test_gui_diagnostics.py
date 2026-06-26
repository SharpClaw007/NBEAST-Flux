"""Headless GUI checks for the Tier-1 trust UI: seed control, entropy monitor,
spectrum uncertainty band."""

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


def test_monitor_streams_entropy_and_marks_inactive(qapp):
    from nbeast.gui.monitor import ConvergenceMonitor

    mon = ConvergenceMonitor()
    mon.mark_inactive(5)
    assert len(mon._inactive_lines) == 2  # one per stacked plot
    for b in range(1, 11):
        mon.add_point(b, 1.0 + 0.001 * b, 0.001, entropy=2.0 + 0.1 * b)
    assert mon.point_count == 10
    assert mon.has_entropy
    mon.reset()
    assert mon.point_count == 0 and not mon.has_entropy
    assert mon._inactive_lines == []
    mon.close()


def test_monitor_without_entropy(qapp):
    from nbeast.gui.monitor import ConvergenceMonitor

    mon = ConvergenceMonitor()
    mon.add_point(1, 1.0, 0.001)  # entropy omitted
    assert mon.point_count == 1 and not mon.has_entropy
    mon.close()


def test_spectrum_band(qapp):
    from nbeast.gui.spectrum import SpectrumView

    view = SpectrumView()
    edges = [1e-3, 1e-1, 1e1, 1e3, 1e5]
    flux = [1.0, 2.0, 3.0, 4.0]
    std = [0.1, 0.2, 0.3, 0.4]
    view.set_spectrum(edges, flux, std)
    assert view.has_data
    # band endpoints populated when std supplied
    assert view._hi.xData is not None and len(view._hi.xData) == 4
    view.clear()
    assert not view.has_data
    view.close()


def test_seed_control_threads_into_model(qapp, tmp_path):
    from nbeast.gui.main_window import MainWindow

    win = MainWindow(run_root=tmp_path)
    win.set_template("Godiva")
    win.seed_spin.setValue(123)
    model = win._build_model()
    assert model.settings.seed == 123
    assert model.settings.entropy_mesh is not None  # diagnostic enabled
    win.close()
