"""Neutron-track generation, reading, and rendering."""

import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_XS = os.environ.get("OPENMC_CROSS_SECTIONS")
requires_data = pytest.mark.skipif(
    not (_XS and pathlib.Path(_XS).exists()),
    reason="OPENMC_CROSS_SECTIONS not set or missing",
)


@requires_data
def test_generate_and_read_tracks(tmp_path):
    from nbeast.core import benchmarks, tracks

    path = tracks.generate(benchmarks.godiva(), n_particles=8, run_dir=tmp_path / "tr")
    assert path.exists()

    polylines = tracks.read_polylines(path, max_polylines=50)
    assert len(polylines) > 0
    first = polylines[0]
    assert first["points"].ndim == 2 and first["points"].shape[1] == 3
    assert first["points"].shape[0] >= 2
    assert first["energy"].shape[0] == first["points"].shape[0]


@requires_data
def test_tracks_render_png(tmp_path):
    pytest.importorskip("pyvista")
    from nbeast.core import benchmarks, tracks
    from nbeast.gui import render

    path = tracks.generate(benchmarks.godiva(), n_particles=8, run_dir=tmp_path / "tr")
    png = render.tracks_to_png(tracks.read_polylines(path), tmp_path / "tracks.png")
    assert png.exists() and png.stat().st_size > 0


@requires_data
def test_gui_show_tracks(tmp_path):
    pytest.importorskip("PySide6")
    pytest.importorskip("pyqtgraph")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])  # noqa: F841
    from nbeast.gui.main_window import MainWindow

    win = MainWindow(run_root=tmp_path)
    win.set_template("Godiva")
    win.show_tracks()
    message = win.statusBar().currentMessage().lower()
    assert "failed" not in message and "showing" in message
    win.close()
