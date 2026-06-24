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

    def _ensure_interactor(self):
        from pyvistaqt import QtInteractor

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
