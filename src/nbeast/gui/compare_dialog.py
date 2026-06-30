"""Side-by-side comparison of two saved runs.

Shows the change in k-effective with its combined uncertainty (so the user can
tell a real reactivity effect from Monte Carlo noise), a parameter-by-parameter
diff, and the two flux spectra overlaid. The numbers come from
:mod:`nbeast.core.compare`; the spectra are read from each run's archived statepoint.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QDialog,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from nbeast.core import compare

_PEN_A = pg.mkPen("#1f77b4", width=2)
_PEN_B = pg.mkPen("#d62728", width=2)


class CompareDialog(QDialog):
    def __init__(self, record_a, record_b, project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Compare runs")
        self.resize(720, 620)
        self._project = project

        data = compare.compare(record_a, record_b)
        layout = QVBoxLayout(self)

        ka = "n/a" if data["keff_a"] is None else f"{data['keff_a']:.5f}"
        kb = "n/a" if data["keff_b"] is None else f"{data['keff_b']:.5f}"
        header = QLabel(
            f"<b>A</b>: {data['label_a']} &nbsp; k = {ka}<br>"
            f"<b>B</b>: {data['label_b']} &nbsp; k = {kb}<br>"
            f"<b>{data['delta'].summary()}</b>"
        )
        header.setTextFormat(pg.QtCore.Qt.RichText)
        layout.addWidget(header)

        layout.addWidget(QLabel("Parameter diff (changed first):"))
        layout.addWidget(self._build_param_table(data["params"]))

        layout.addWidget(QLabel("Flux spectra (per lethargy):"))
        layout.addWidget(self._build_spectrum_plot(record_a, record_b))

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    # ---- widgets ----------------------------------------------------------
    def _build_param_table(self, rows) -> QTableWidget:
        table = QTableWidget(len(rows), 3)
        table.setHorizontalHeaderLabels(["Parameter", "A", "B"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        for r, row in enumerate(rows):
            cells = [QTableWidgetItem(str(row.key)),
                     QTableWidgetItem(_fmt(row.a)),
                     QTableWidgetItem(_fmt(row.b))]
            for cell in cells:
                if row.changed:
                    cell.setBackground(QColor("#fff3cd"))  # highlight what changed
            for c, cell in enumerate(cells):
                table.setItem(r, c, cell)
        table.setMaximumHeight(220)
        return table

    def _build_spectrum_plot(self, record_a, record_b) -> pg.PlotWidget:
        plot = pg.PlotWidget()
        plot.setLogMode(x=True, y=False)
        plot.setLabel("bottom", "energy", units="eV")
        plot.setLabel("left", "flux per lethargy (a.u.)")
        plot.addLegend()
        for record, pen, name in ((record_a, _PEN_A, "A"), (record_b, _PEN_B, "B")):
            mids, per_lethargy = self._spectrum(record)
            if mids is not None:
                plot.plot(mids, per_lethargy, pen=pen, name=f"{name}: {record.title()}")
        return plot

    def _spectrum(self, record):
        """(energy midpoints, flux-per-lethargy) for a run, or (None, None)."""
        sp = self._project.statepoint_path(record)
        if sp is None or not Path(sp).exists():
            return None, None
        from nbeast.core.results import Results

        try:
            with Results(str(sp)) as results:
                spec = results.flux_spectrum()
            edges = np.asarray(spec.energy_edges, dtype=float)
            flux = np.asarray(spec.flux, dtype=float)
            mids = np.sqrt(edges[:-1] * edges[1:])
            lethargy = np.log(edges[1:] / edges[:-1])
            per_lethargy = np.divide(flux, lethargy, out=np.zeros_like(flux), where=lethargy > 0)
            return mids, per_lethargy
        except Exception:  # noqa: BLE001 — a missing/old spectrum just drops the curve
            return None, None


def _fmt(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)
