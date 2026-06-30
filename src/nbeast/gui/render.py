"""Off-screen flux rendering (no GL window).

Renders a flux VTK file to a PNG via pyvista's off-screen plotter. Works
headlessly (used in tests today; the basis for report-export images later).
"""

from __future__ import annotations

from pathlib import Path


def flat_flux_surface(vtk_path):
    """Read a flux mesh VTK and collapse the 1-cell-thick z-slab to a flat plane.

    The tally mesh has a physical z-thickness (for sound statistics), but a 2D
    slice should render as a flat heatmap, not an extruded slab — so we slice
    through the centre to get a zero-thickness plane that reads correctly from
    any camera angle.
    """
    import pyvista as pv

    from ._vtkquiet import quiet

    quiet()
    grid = pv.read(str(vtk_path))
    return grid.slice(normal="z")


def flux_to_png(vtk_path, png_path, scalar: str = "flux", title: str = "Scalar flux") -> Path:
    import pyvista as pv

    surface = flat_flux_surface(vtk_path)
    plotter = pv.Plotter(off_screen=True)
    plotter.add_mesh(surface, scalars=scalar, cmap="viridis", show_edges=False)
    plotter.enable_parallel_projection()
    plotter.view_xy()
    plotter.add_text(title, font_size=10)
    plotter.screenshot(str(png_path))
    plotter.close()
    return Path(png_path)


def draw_tracks(plotter, polylines) -> None:
    """Add particle-track polylines to a plotter, coloured by energy (log scale)."""
    import pyvista as pv

    from ._vtkquiet import quiet

    quiet()
    energies = [pl["energy"] for pl in polylines]
    emin = max(min(float(e.min()) for e in energies), 1e-5)
    emax = max(max(float(e.max()) for e in energies), emin * 10.0)
    for i, pl in enumerate(polylines):
        line = pv.lines_from_points(pl["points"])
        line["E"] = pl["energy"]
        plotter.add_mesh(
            line,
            scalars="E",
            cmap="plasma",
            log_scale=True,
            clim=(emin, emax),
            line_width=2,
            show_scalar_bar=(i == 0),
            scalar_bar_args={"title": "E (eV)"},
        )


def tracks_to_png(polylines, png_path, title: str = "Neutron tracks") -> Path:
    import pyvista as pv

    plotter = pv.Plotter(off_screen=True)
    draw_tracks(plotter, polylines)
    plotter.add_text(title, font_size=10)
    plotter.view_isometric()
    plotter.screenshot(str(png_path))
    plotter.close()
    return Path(png_path)
