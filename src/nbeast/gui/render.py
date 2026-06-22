"""Off-screen flux rendering (no GL window).

Renders a flux VTK file to a PNG via pyvista's off-screen plotter. Works
headlessly (used in tests today; the basis for report-export images later).
"""

from __future__ import annotations

from pathlib import Path


def flux_to_png(vtk_path, png_path, title: str = "Scalar flux") -> Path:
    import pyvista as pv

    grid = pv.read(str(vtk_path))
    plotter = pv.Plotter(off_screen=True)
    plotter.add_mesh(grid, scalars="flux", cmap="viridis")
    plotter.view_xy()
    plotter.add_text(title, font_size=10)
    plotter.screenshot(str(png_path))
    plotter.close()
    return Path(png_path)
