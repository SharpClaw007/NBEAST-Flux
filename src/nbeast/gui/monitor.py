"""Live convergence monitor — k-effective + Shannon entropy vs batch (pyqtgraph).

This is the analogue of Caedium's residuals plot: two stacked, x-linked traces.
**k-effective** (top) is the running eigenvalue estimate. **Shannon entropy**
(bottom) measures how spread-out the fission source is — it should rise and then
*plateau*; tallying (active batches) should only begin after it has levelled off.
A dashed line marks the inactive→active boundary so you can see whether the source
converged in time. Entropy is computed live from the source bank (openmc.lib does
not expose it — see docs/phase0-notes.md).
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

_CAPTION = (
    "k-effective is the neutron multiplication factor — k = 1 is exactly critical "
    "(self-sustaining), k > 1 supercritical, k < 1 subcritical. The Shannon entropy "
    "below tracks fission-source convergence: it should flatten out before the dashed "
    "line (where the discarded 'inactive' batches end and tallying begins). If it is "
    "still rising at the line, add inactive batches."
)


class ConvergenceMonitor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._k_plot = pg.PlotWidget()
        self._k_plot.setBackground("w")
        self._k_plot.setTitle("k-effective convergence")
        self._k_plot.setLabel("left", "k-effective")
        self._k_plot.showGrid(x=True, y=True, alpha=0.3)
        self._k_curve = self._k_plot.plot([], [], pen=pg.mkPen(width=2), symbol="o", symbolSize=4)
        layout.addWidget(self._k_plot, stretch=1)

        self._h_plot = pg.PlotWidget()
        self._h_plot.setBackground("w")
        self._h_plot.setTitle("Shannon entropy (fission-source convergence)")
        self._h_plot.setLabel("bottom", "batch")
        self._h_plot.setLabel("left", "entropy (bits)")
        self._h_plot.showGrid(x=True, y=True, alpha=0.3)
        self._h_plot.setXLink(self._k_plot)  # share the batch axis
        self._h_curve = self._h_plot.plot(
            [], [], pen=pg.mkPen("#c0392b", width=2), symbol="o", symbolSize=3
        )
        layout.addWidget(self._h_plot, stretch=1)

        caption = QLabel(_CAPTION)
        caption.setWordWrap(True)
        caption.setStyleSheet("color: #555; padding: 4px;")
        layout.addWidget(caption)

        self._batches: list[int] = []
        self._keffs: list[float] = []
        self._ent_batches: list[int] = []
        self._entropy: list[float] = []
        self._inactive_lines: list[tuple] = []  # (plot, line) pairs

    @property
    def point_count(self) -> int:
        return len(self._batches)

    @property
    def has_entropy(self) -> bool:
        return bool(self._entropy)

    def reset(self) -> None:
        self._batches.clear()
        self._keffs.clear()
        self._ent_batches.clear()
        self._entropy.clear()
        self._k_curve.setData([], [])
        self._h_curve.setData([], [])
        for plot, line in self._inactive_lines:
            plot.removeItem(line)
        self._inactive_lines.clear()

    def mark_inactive(self, n_inactive: int) -> None:
        """Draw the dashed inactive→active boundary on both plots."""
        if n_inactive <= 0:
            return
        for plot in (self._k_plot, self._h_plot):
            line = pg.InfiniteLine(
                pos=n_inactive + 0.5, angle=90,
                pen=pg.mkPen("#888", style=Qt.DashLine),
            )
            plot.addItem(line)
            self._inactive_lines.append((plot, line))

    def add_point(
        self, batch: int, keff: float, std: float | None = None, entropy: float | None = None
    ) -> None:
        self._batches.append(batch)
        self._keffs.append(keff)
        self._k_curve.setData(self._batches, self._keffs)
        if entropy is not None:
            self._ent_batches.append(batch)
            self._entropy.append(entropy)
            self._h_curve.setData(self._ent_batches, self._entropy)
