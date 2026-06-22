"""Phase 0 / Spike C: flux mesh tally -> VTK -> embedded-style 3D render.

1. Run the pin cell with a regular-mesh flux tally.
2. Export the flux field to VTK via OpenMC's own writer (correct cell ordering).
3. Render it off-screen with pyvista -> PNG (proves the data -> viz path).
4. Construct a pyvistaqt QtInteractor under the offscreen Qt platform
   (proves the widget that will live inside the PySide6 GUI can be created).

Run:
    QT_QPA_PLATFORM=offscreen OPENMC_CROSS_SECTIONS=.../cross_sections.xml \
        python spikes/flux_mesh.py
"""

import os
import pathlib
import sys

os.environ.setdefault("FI_PROVIDER", "tcp")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import openmc

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pincell import build_model

RUN_DIR = pathlib.Path(__file__).parent / "run_mesh"
OUT_PNG = pathlib.Path(__file__).parent / "flux_mesh.png"


def run_with_mesh_tally() -> str:
    model = build_model()

    h = 0.63  # half-pitch (matches pincell)
    mesh = openmc.RegularMesh()
    mesh.dimension = (40, 40, 1)
    mesh.lower_left = (-h, -h, -1.0)
    mesh.upper_right = (h, h, 1.0)

    flux_tally = openmc.Tally(name="flux")
    flux_tally.filters = [openmc.MeshFilter(mesh)]
    flux_tally.scores = ["flux"]
    model.tallies = openmc.Tallies([flux_tally])

    RUN_DIR.mkdir(exist_ok=True)
    os.chdir(RUN_DIR)
    sp_path = model.run()

    with openmc.StatePoint(sp_path) as sp:
        t = sp.get_tally(name="flux")
        flux = t.get_values(scores=["flux"]).ravel()
    # OpenMC writes the VTK with correct mesh-cell ordering for us.
    vtk_path = RUN_DIR / "flux.vtk"
    mesh.write_data_to_vtk(str(vtk_path), {"flux": flux})
    print(f"FLUX cells={flux.size} min={flux.min():.4e} max={flux.max():.4e}")
    return str(vtk_path)


def render(vtk_path: str) -> None:
    import pyvista as pv

    grid = pv.read(vtk_path)
    print("PYVISTA read grid:", grid.n_cells, "cells;", grid.array_names)
    p = pv.Plotter(off_screen=True)
    p.add_mesh(grid, scalars="flux", cmap="viridis", show_edges=False)
    p.add_text("Pin-cell scalar flux", font_size=10)
    p.view_xy()
    p.screenshot(str(OUT_PNG))
    print(f"SCREENSHOT written: {OUT_PNG} ({OUT_PNG.stat().st_size} bytes)")


def test_qt_widget() -> None:
    from PySide6.QtWidgets import QApplication
    from pyvistaqt import QtInteractor

    app = QApplication.instance() or QApplication(sys.argv)
    interactor = QtInteractor()
    print("PYVISTAQT QtInteractor created:", type(interactor).__name__)
    interactor.close()


if __name__ == "__main__":
    vtk_path = run_with_mesh_tally()
    render(vtk_path)
    test_qt_widget()
    print("SPIKE_C_OK")
