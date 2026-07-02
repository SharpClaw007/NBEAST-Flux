"""Moderation curve — k-eff, reactivity, and source-driven power across the full
range from fully-flooded to voided moderator (or lattice pitch).

Each point is a full OpenMC eigenvalue run (reusing the sweep engine). The result is
the classic under/over-moderation story: k rises out of the voided (undermoderated)
regime, and — for the subcritical branch — the source multiplication M = 1/(1−k)
climbs toward the critical crossing, a genuine relative power proxy.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from nbeast.core import reactivity
from nbeast.core.sweep import sweep_values

from .sweep_dialog import SweepController


class ModerationDialog(QDialog):
    """Applicable to templates with a moderator (pin cell, assembly)."""

    studyResult = Signal(object)   # a core.studies.StudyResult when the sweep completes

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main = main_window
        self.setWindowTitle("Moderation curve (reactivity + source-driven power)")
        self.resize(780, 720)
        self._points: list[tuple[float, float, float]] = []

        self.controller = SweepController(self)
        self.controller.point.connect(self._on_point)
        self.controller.progress.connect(lambda m: self.status.setText(m))
        self.controller.finished.connect(self._on_finished)
        self.controller.failed.connect(self._on_failed)

        self._build_ui()
        self._on_knob_changed()

    # ---- UI ---------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        intro = QLabel(
            "Sweep the moderation from voided to flooded and watch criticality respond. "
            "k-effective and reactivity are what the geometry sets; the lower plot shows "
            "the source-driven power proxy M = 1/(1−k), which diverges at the critical "
            "crossing (above it the reactor is self-sustaining — power is operational)."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #555;")
        layout.addWidget(intro)

        top = QHBoxLayout()
        self.knob_combo = QComboBox()
        self.knob_combo.addItem("Moderator density (% of nominal)", "density")
        if any(p.key == "pitch" for p in self.main.spec.parameters):
            self.knob_combo.addItem("Lattice pitch (moderator-to-fuel ratio)", "pitch")
        self.knob_combo.currentIndexChanged.connect(self._on_knob_changed)
        top.addWidget(QLabel("Moderation knob:"))
        top.addWidget(self.knob_combo, 1)
        layout.addLayout(top)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.lo_spin = QDoubleSpinBox()
        self.hi_spin = QDoubleSpinBox()
        for s in (self.lo_spin, self.hi_spin):
            s.setDecimals(2)
            s.setRange(0.0, 1e6)
        self.n_spin = QSpinBox()
        self.n_spin.setRange(3, 50)
        self.n_spin.setValue(9)
        self.batches_spin = QSpinBox()
        self.batches_spin.setRange(10, 100_000)
        self.batches_spin.setValue(60)
        self.particles_spin = QSpinBox()
        self.particles_spin.setRange(100, 10_000_000)
        self.particles_spin.setSingleStep(500)
        self.particles_spin.setValue(1500)
        form.addRow("From:", self.lo_spin)
        form.addRow("To:", self.hi_spin)
        form.addRow("Points:", self.n_spin)
        form.addRow("Batches / point:", self.batches_spin)
        form.addRow("Particles / batch:", self.particles_spin)
        layout.addLayout(form)

        controls = QHBoxLayout()
        self.run_btn = QPushButton("Run")
        self.run_btn.setDefault(True)
        self.run_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.controller.cancel)
        self.export_btn = QPushButton("Export CSV")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export_csv)
        controls.addWidget(self.run_btn)
        controls.addWidget(self.stop_btn)
        controls.addStretch(1)
        controls.addWidget(self.export_btn)
        layout.addLayout(controls)

        self.status = QLabel("Ready.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #555;")
        layout.addWidget(self.status)

        self.k_plot = self._make_plot("k-effective")
        self.k_plot.addLine(y=1.0, pen=pg.mkPen("#c0392b", style=Qt.DashLine))  # critical
        self.k_curve = self.k_plot.plot(
            [], [], pen=pg.mkPen("#1f77b4", width=2), symbol="o", symbolSize=6,
            symbolBrush="#1f77b4", symbolPen="#1f77b4",
        )
        layout.addWidget(self.k_plot, stretch=1)

        self.m_plot = self._make_plot("source power ∝ M = 1/(1−k)")
        self.m_plot.setLogMode(y=True)
        self.m_plot.setXLink(self.k_plot)
        self.m_curve = self.m_plot.plot(
            [], [], pen=pg.mkPen("#e67e22", width=2), symbol="o", symbolSize=6,
            symbolBrush="#e67e22", symbolPen="#e67e22",
        )
        layout.addWidget(self.m_plot, stretch=1)

    def _make_plot(self, ylabel: str) -> pg.PlotWidget:
        plot = pg.PlotWidget()
        plot.setBackground("w")
        plot.setLabel("left", ylabel)
        plot.showGrid(x=True, y=True, alpha=0.25)
        for name in ("left", "bottom"):
            plot.getAxis(name).setPen("#666")
            plot.getAxis(name).setTextPen("#333")
        return plot

    # ---- reactions --------------------------------------------------------
    def _knob(self) -> str:
        return self.knob_combo.currentData()

    def _on_knob_changed(self) -> None:
        if self._knob() == "density":
            self.lo_spin.setValue(0.0)
            self.hi_spin.setValue(100.0)
            xlabel = "moderator density (% of nominal)"
        else:
            p = next(p for p in self.main.spec.parameters if p.key == "pitch")
            cur = self.main._param_values[self.main._template].get("pitch", p.default)
            self.lo_spin.setValue(max(p.minimum, cur * 0.6))
            self.hi_spin.setValue(min(p.maximum, cur * 2.2))
            xlabel = "lattice pitch (cm)"
        self.k_plot.setLabel("bottom", xlabel)
        self.m_plot.setLabel("bottom", xlabel)

    def _make_builder(self):
        from .main_window import _inactive_for

        main = self.main
        spec = main.spec
        knob = self._knob()
        base = dict(main._param_values[main._template])
        mats = dict(main._material_values[main._template])
        batches = self.batches_spin.value()
        particles = self.particles_spin.value()
        inactive = _inactive_for(batches)
        seed = main.seed_spin.value()

        def builder(x: float):
            params = dict(base)
            extra = {}
            if knob == "density":
                extra["moderator_density"] = x / 100.0    # % -> fraction
            else:
                params["pitch"] = x
            return spec.build(batches=batches, particles=particles, inactive=inactive,
                              seed=seed, **mats, **params, **extra)

        return builder

    def _start(self) -> None:
        if self.controller.running:
            return
        values = sweep_values(self.lo_spin.value(), self.hi_spin.value(), self.n_spin.value())
        self._reset()
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status.setText("Starting…")
        self.controller.start(("sweep", values), self._make_builder(),
                              self.main._run_root / "moderation", self.main._cross_sections)

    def _reset(self) -> None:
        self._points = []
        self.export_btn.setEnabled(False)
        self.k_curve.setData([], [])
        self.m_curve.setData([], [])

    def _on_point(self, x: float, k: float, std: float) -> None:
        self._points.append((x, k, std))
        ordered = sorted(self._points, key=lambda t: t[0])
        xs = [t[0] for t in ordered]
        self.k_curve.setData(xs, [t[1] for t in ordered])
        m_pts = [(t[0], reactivity.subcritical_multiplication(t[1])) for t in ordered]
        m_pts = [(px, m) for px, m in m_pts if m is not None]
        if m_pts:
            self.m_curve.setData([p[0] for p in m_pts], [p[1] for p in m_pts])

    def _on_finished(self, summary) -> None:
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.export_btn.setEnabled(bool(self._points))
        n = len(self._points)
        crossings = self._critical_crossings()
        msg = f"{'Stopped' if summary.get('stopped') else 'Complete'} — {n} points."
        if crossings:
            where = ", ".join(f"{c:g}" for c in crossings)
            msg += f"  Critical (k=1) near: {where}."
        else:
            ks = [k for _x, k, _s in self._points]
            if ks and max(ks) < 1:
                msg += "  Stays subcritical over this range."
            elif ks and min(ks) > 1:
                msg += "  Stays supercritical over this range."
        self.status.setText(msg)
        from datetime import datetime, timezone

        from nbeast.core.studies import StudyResult

        self.studyResult.emit(StudyResult(
            ok=bool(self._points), summary=msg.rstrip("."), points=list(self._points),
            scalars={"critical_at": crossings[0]} if crossings else {},
            created_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))

    def _critical_crossings(self) -> list[float]:
        """Linear-interpolated x where k crosses 1 between adjacent points."""
        pts = sorted(self._points, key=lambda t: t[0])
        out = []
        for (x0, k0, _), (x1, k1, _) in zip(pts, pts[1:]):
            if (k0 - 1.0) * (k1 - 1.0) < 0 and k1 != k0:
                out.append(x0 + (1.0 - k0) * (x1 - x0) / (k1 - k0))
        return out

    def _on_failed(self, message: str) -> None:
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status.setText(f"Error: {message}")

    def _export_csv(self) -> None:
        if not self._points:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export moderation data",
                                              "moderation.csv", "CSV (*.csv)")
        if not path:
            return
        import csv

        with open(path, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([self._knob(), "keff", "keff_std", "reactivity_pcm", "subcrit_mult"])
            for x, k, std in sorted(self._points, key=lambda t: t[0]):
                writer.writerow([x, k, std, reactivity.reactivity_pcm(k),
                                 reactivity.subcritical_multiplication(k)])
        self.status.setText(f"Exported to {path}")

    def closeEvent(self, event) -> None:
        self.controller.stop_and_wait()
        super().closeEvent(event)
