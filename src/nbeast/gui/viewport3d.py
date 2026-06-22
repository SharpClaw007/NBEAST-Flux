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

    @staticmethod
    def _headless() -> bool:
        return os.environ.get("QT_QPA_PLATFORM", "") == "offscreen"

    def set_vtk(self, vtk_path) -> None:
        self._vtk_path = str(vtk_path)
        self.render_flux()

    def render_flux(self) -> None:
        if not self._vtk_path:
            return
        if self._headless():
            self._placeholder.setText("3D flux view is unavailable in headless mode.")
            return
        try:
            import pyvista as pv
            from pyvistaqt import QtInteractor

            if self._interactor is None:
                self._interactor = QtInteractor(self)
                self._layout.addWidget(self._interactor)
                self._placeholder.hide()
            grid = pv.read(self._vtk_path)
            self._interactor.clear()
            self._interactor.add_mesh(grid, scalars="flux", cmap="viridis")
            self._interactor.view_xy()
            self._interactor.reset_camera()
        except Exception as exc:  # noqa: BLE001 — never let viz kill the app
            self._placeholder.show()
            self._placeholder.setText(f"3D view error: {exc}")
