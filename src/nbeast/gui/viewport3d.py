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

    def _ensure_interactor(self):
        from pyvistaqt import QtInteractor

        if self._interactor is None:
            self._interactor = QtInteractor(self)
            self._layout.addWidget(self._interactor)
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
            from pyvistaqt import QtInteractor

            from .render import flat_flux_surface

            if self._interactor is None:
                self._interactor = QtInteractor(self)
                self._layout.addWidget(self._interactor)
                self._placeholder.hide()
            surface = flat_flux_surface(self._vtk_path)
            self._interactor.clear()
            self._interactor.add_mesh(surface, scalars=self._scalar, cmap="viridis", show_edges=False)
            self._interactor.add_text(self._title, font_size=10, name="title")
            self._interactor.enable_parallel_projection()
            self._interactor.view_xy()
            self._interactor.reset_camera()
        except Exception as exc:  # noqa: BLE001 — never let viz kill the app
            self._placeholder.show()
            self._placeholder.setText(f"3D view error: {exc}")
