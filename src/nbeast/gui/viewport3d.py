"""Embedded 3D flux viewport (pyvistaqt).

The VTK ``QtInteractor`` needs a real GL context, so it is created **lazily**
(only when there's something to show) and **skipped under the headless/offscreen
Qt platform** — that keeps automated tests safe while still rendering in a real
desktop session.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class FluxViewport(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._placeholder = QLabel("Run a simulation to see the flux map here.")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._layout.addWidget(self._placeholder)

        caption = QLabel(
            "Spatial map of the selected field on a slice through the model. "
            "Switch fields (scalar flux, fission rate, neutron tracks) in the Results "
            "panel. Drag to rotate, scroll to zoom."
        )
        caption.setWordWrap(True)
        caption.setStyleSheet("color: #555; padding: 4px;")
        self._layout.addWidget(caption)

        self._interactor = None
        self._vtk_path: str | None = None
        self._scalar = "flux"
        self._title = "Flux"
        self._tracks = None

    @staticmethod
    def _headless() -> bool:
        return os.environ.get("QT_QPA_PLATFORM", "") == "offscreen"

    def show_field(self, vtk_path, scalar: str = "flux", title: str = "Flux") -> None:
        self._tracks = None
        self._vtk_path = str(vtk_path)
        self._scalar = scalar
        self._title = title
        self.render_flux()

    def show_tracks(self, polylines, title: str = "Neutron tracks") -> None:
        self._vtk_path = None
        self._tracks = polylines
        self._title = title
        self._render_tracks()

    def show_cad(self, stl_paths, colors=None, title: str = "CAD geometry") -> None:
        """Render imported CAD solids (per-solid STLs), coloured by material."""
        self._vtk_path = None
        self._tracks = None
        self._title = title
        if self._headless():
            self._placeholder.setText(f"{title}: 3D view unavailable in headless mode.")
            return
        try:
            import pyvista as pv

            interactor = self._ensure_interactor()
            interactor.clear()
            for i, path in enumerate(stl_paths):
                color = colors[i] if colors and i < len(colors) else None
                interactor.add_mesh(pv.read(path), color=color, show_edges=True, opacity=0.6)
            interactor.add_text(title, font_size=10, name="title")
            interactor.view_isometric()
            interactor.reset_camera()
        except Exception as exc:  # noqa: BLE001 — never let viz kill the app
            self._placeholder.show()
            self._placeholder.setText(f"3D view error: {exc}")

    def show_field_volume(self, values, dims, lower_left, upper_right, *,
                          log: bool = True, stls=None, colors=None,
                          title: str = "Scalar flux") -> None:
        """Publication-style 3D volume render of a field (log scale + colorbar +
        opacity transfer function), with optional semi-transparent geometry overlay.

        `values` is the flattened mesh field (x fastest, matching OpenMC); `dims` is
        (nx, ny, nz). `stls`/`colors` overlay the geometry (e.g. CAD solids).
        """
        self._vtk_path = None
        self._tracks = None
        self._title = title
        if self._headless():
            self._placeholder.setText(f"{title}: 3D view unavailable in headless mode.")
            return
        try:
            import numpy as np
            import pyvista as pv

            nx, ny, nz = (int(d) for d in dims)
            field = np.asarray(values, dtype=float).ravel()
            label = title
            if log:
                positive = field[field > 0]
                floor = positive.min() if positive.size else 1e-30
                field = np.log10(np.where(field > 0, field, floor))
                label = f"log₁₀ {title}"

            # Clip the colour/opacity window to the *real* data so the empty/low
            # cells don't compress the gradient (they fall below clim -> transparent).
            real = field[field > field.min() + 1e-9]
            lo = float(np.percentile(real, 2)) if real.size else float(field.min())
            hi = float(field.max())

            grid = pv.ImageData()
            grid.dimensions = (nx, ny, nz)  # points at mesh-cell centres
            llx, lly, llz = lower_left
            urx, ury, urz = upper_right
            grid.origin = (llx, lly, llz)
            grid.spacing = (
                (urx - llx) / max(nx - 1, 1),
                (ury - lly) / max(ny - 1, 1),
                (urz - llz) / max(nz - 1, 1),
            )
            grid.point_data["flux"] = field

            interactor = self._ensure_interactor()
            interactor.clear()
            if stls:
                for i, path in enumerate(stls):
                    color = colors[i] if colors and i < len(colors) else "lightgray"
                    interactor.add_mesh(pv.read(path), color=color, opacity=0.12, show_edges=False)
            interactor.add_volume(
                grid, scalars="flux", cmap="inferno",
                opacity=[0.0, 0.04, 0.12, 0.30, 0.60, 0.92],  # graded glow, low = transparent
                clim=[lo, hi],
                scalar_bar_args={"title": label},
            )
            interactor.add_text(title, font_size=10, name="title")
            interactor.view_isometric()
            interactor.reset_camera()
        except Exception as exc:  # noqa: BLE001
            self._placeholder.show()
            self._placeholder.setText(f"3D view error: {exc}")

    def show_field_array(self, values, lower_left, upper_right, title: str = "Flux map") -> None:
        """Render a 2D field (e.g. a z-integrated CAD flux map) from a raw array."""
        self._vtk_path = None
        self._tracks = None
        self._title = title
        if self._headless():
            self._placeholder.setText(f"{title}: 3D view unavailable in headless mode.")
            return
        try:
            import numpy as np
            import pyvista as pv

            arr = np.asarray(values, dtype=float)  # (ny, nx)
            ny, nx = arr.shape
            llx, lly = lower_left
            urx, ury = upper_right
            grid = pv.ImageData()
            grid.dimensions = (nx + 1, ny + 1, 1)
            grid.origin = (llx, lly, 0.0)
            grid.spacing = ((urx - llx) / nx, (ury - lly) / ny, 1.0)
            grid.cell_data["flux"] = arr.ravel()

            interactor = self._ensure_interactor()
            interactor.clear()
            interactor.add_mesh(grid, scalars="flux", cmap="viridis", show_edges=False)
            interactor.add_text(title, font_size=10, name="title")
            interactor.enable_parallel_projection()
            interactor.view_xy()
            interactor.reset_camera()
        except Exception as exc:  # noqa: BLE001
            self._placeholder.show()
            self._placeholder.setText(f"3D view error: {exc}")

    def _ensure_interactor(self):
        from pyvistaqt import QtInteractor

        from ._vtkquiet import quiet

        quiet()
        if self._interactor is None:
            self._interactor = QtInteractor(self)
            self._layout.insertWidget(0, self._interactor)  # above the caption
            self._placeholder.hide()
        return self._interactor

    def _render_tracks(self) -> None:
        if not self._tracks:
            return
        if self._headless():
            self._placeholder.setText(f"{self._title}: 3D view unavailable in headless mode.")
            return
        try:
            from .render import draw_tracks

            interactor = self._ensure_interactor()
            interactor.clear()
            draw_tracks(interactor, self._tracks)
            interactor.add_text(self._title, font_size=10, name="title")
            interactor.view_isometric()
            interactor.reset_camera()
        except Exception as exc:  # noqa: BLE001
            self._placeholder.show()
            self._placeholder.setText(f"3D view error: {exc}")

    def render_flux(self) -> None:
        if not self._vtk_path:
            return
        if self._headless():
            self._placeholder.setText(f"{self._title}: 3D view unavailable in headless mode.")
            return
        try:
            from .render import flat_flux_surface

            interactor = self._ensure_interactor()
            surface = flat_flux_surface(self._vtk_path)
            interactor.clear()
            interactor.add_mesh(surface, scalars=self._scalar, cmap="viridis", show_edges=False)
            interactor.add_text(self._title, font_size=10, name="title")
            interactor.enable_parallel_projection()
            interactor.view_xy()
            interactor.reset_camera()
        except Exception as exc:  # noqa: BLE001 — never let viz kill the app
            self._placeholder.show()
            self._placeholder.setText(f"3D view error: {exc}")
