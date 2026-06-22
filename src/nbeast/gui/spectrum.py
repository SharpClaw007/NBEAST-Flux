"""Flux energy-spectrum plot (pyqtgraph), flux-per-lethargy vs energy (log-E)."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QVBoxLayout, QWidget


class SpectrumView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._plot = pg.PlotWidget()
        self._plot.setBackground("w")
        self._plot.setLogMode(x=True, y=False)  # log energy axis
        self._plot.setTitle("Flux energy spectrum")
        self._plot.setLabel("bottom", "energy (eV)")
        self._plot.setLabel("left", "flux per unit lethargy (a.u.)")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._curve = self._plot.plot([], [], pen=pg.mkPen(width=2))
        layout.addWidget(self._plot)

        self._has_data = False

    @property
    def has_data(self) -> bool:
        return self._has_data

    def clear(self) -> None:
        self._curve.setData([], [])
        self._has_data = False

    def set_spectrum(self, energy_edges, flux) -> None:
        edges = np.asarray(energy_edges, dtype=float)
        values = np.asarray(flux, dtype=float)
        midpoints = np.sqrt(edges[:-1] * edges[1:])
        lethargy = np.log(edges[1:] / edges[:-1])
        per_lethargy = np.divide(
            values, lethargy, out=np.zeros_like(values), where=lethargy > 0
        )
        self._curve.setData(midpoints, per_lethargy)
        self._has_data = bool(values.size)
