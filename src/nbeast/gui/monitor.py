"""Live convergence monitor — k-effective vs batch (pyqtgraph).

This is the analogue of Caedium's residuals plot: the running k-eff estimate
streamed per batch. (Shannon entropy will join it once we wire an entropy source;
openmc.lib does not expose it directly — see docs/phase0-notes.md.)
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

_CAPTION = (
    "k-effective is the neutron multiplication factor — k = 1 is exactly critical "
    "(self-sustaining), k > 1 supercritical, k < 1 subcritical. It should settle to a "
    "steady value as the run proceeds; the noisy first cycles are 'inactive' batches, "
    "discarded while the fission source distribution converges."
)


class ConvergenceMonitor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._plot = pg.PlotWidget()
        self._plot.setBackground("w")
        self._plot.setTitle("k-effective convergence")
        self._plot.setLabel("bottom", "batch")
        self._plot.setLabel("left", "k-effective")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._curve = self._plot.plot([], [], pen=pg.mkPen(width=2), symbol="o", symbolSize=4)
        layout.addWidget(self._plot)

        caption = QLabel(_CAPTION)
        caption.setWordWrap(True)
        caption.setStyleSheet("color: #555; padding: 4px;")
        layout.addWidget(caption)

        self._batches: list[int] = []
        self._keffs: list[float] = []

    @property
    def point_count(self) -> int:
        return len(self._batches)

    def reset(self) -> None:
        self._batches.clear()
        self._keffs.clear()
        self._curve.setData([], [])

    def add_point(self, batch: int, keff: float, std: float | None = None) -> None:
        self._batches.append(batch)
        self._keffs.append(keff)
        self._curve.setData(self._batches, self._keffs)
