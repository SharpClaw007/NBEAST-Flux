"""Run a depletion / burnup calculation and plot k-effective vs burnup.

Configures a burnup history (steps × length, power or source rate, integrator) for
the current eigenvalue fuel model, runs it in an isolated subprocess off the UI
thread, and plots how k-effective evolves as the fuel burns. Available only when a
depletion chain is configured (see :class:`DepletionSetupDialog`).
"""

from __future__ import annotations

from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from nbeast.core import depletion
from nbeast.core.depletion import DepletionConfig, DepletionRunner


class _DepletionWorker(QObject):
    started = Signal(int)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, runner, model, config, run_dir, fuel_id, fuel_vol):
        super().__init__()
        self._runner = runner
        self._args = (model, config, run_dir, fuel_id, fuel_vol)

    @Slot()
    def run(self):
        try:
            model, config, run_dir, fuel_id, fuel_vol = self._args
            result = self._runner.run(
                model, config, run_dir, fuel_id=fuel_id, fuel_vol=fuel_vol,
                on_start=lambda n: self.started.emit(n),
            )
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class DepletionDialog(QDialog):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main = main_window
        self.setWindowTitle("Depletion / burnup")
        self.resize(720, 620)
        self._thread = None
        self._worker = None
        self._result = None
        self._runner = None

        self._build_ui()
        if self.main._is_fixed_source:
            self.run_btn.setEnabled(False)
            self.status.setText("Depletion needs a fuel (eigenvalue) model — pick a "
                                "reactor template, not the shield slab.")

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        banner = QLabel(
            "⚠ <b>Workflow validated; burnup numbers are not benchmarked.</b> The depletion "
            "pipeline is verified end-to-end, but NBEAST has not validated its k-vs-burnup "
            "or inventory <i>values</i> against a depletion benchmark (e.g. VERA). Treat "
            "results as exploratory, and check against a validated depletion code before use."
        )
        banner.setWordWrap(True)
        banner.setTextFormat(Qt.RichText)
        banner.setStyleSheet(
            "background:#5a4a00; color:#ffe9a8; border:1px solid #8a7300;"
            "border-radius:4px; padding:6px;")
        layout.addWidget(banner)

        form = QFormLayout()

        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(1, 200)
        self.steps_spin.setValue(5)
        form.addRow("Burnup steps:", self.steps_spin)

        self.step_days_spin = QDoubleSpinBox()
        self.step_days_spin.setRange(0.1, 3650.0)
        self.step_days_spin.setValue(30.0)
        self.step_days_spin.setSuffix(" days/step")
        form.addRow("Step length:", self.step_days_spin)

        self.norm_combo = QComboBox()
        self.norm_combo.addItems(["Power (MW)", "Source rate (n/s)"])
        self.norm_combo.currentIndexChanged.connect(self._on_norm_changed)
        form.addRow("Normalization:", self.norm_combo)

        self.value_spin = QDoubleSpinBox()
        self.value_spin.setRange(1e-6, 1e30)
        self.value_spin.setDecimals(4)
        self.value_spin.setValue(1.0)  # MW
        form.addRow("Value:", self.value_spin)

        self.integrator_combo = QComboBox()
        self.integrator_combo.addItems(list(depletion.INTEGRATORS))
        form.addRow("Integrator:", self.integrator_combo)

        self.batches_spin = QSpinBox()
        self.batches_spin.setRange(10, 100_000)
        self.batches_spin.setValue(40)
        form.addRow("Batches/step:", self.batches_spin)

        self.particles_spin = QSpinBox()
        self.particles_spin.setRange(100, 10_000_000)
        self.particles_spin.setSingleStep(500)
        self.particles_spin.setValue(1000)
        form.addRow("Particles/batch:", self.particles_spin)
        layout.addLayout(form)

        controls = QHBoxLayout()
        self.run_btn = QPushButton("Run burnup")
        self.run_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._cancel)
        self.export_btn = QPushButton("Export CSV")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export)
        for b in (self.run_btn, self.stop_btn, self.export_btn):
            controls.addWidget(b)
        layout.addLayout(controls)

        self.status = QLabel(f"Chain: {depletion.chain_path()}")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.plot = pg.PlotWidget()
        self.plot.setLabel("left", "k-effective")
        self.plot.setLabel("bottom", "burnup time", units="days")
        self.plot.addLine(y=1.0, pen=pg.mkPen("#888", style=pg.QtCore.Qt.DashLine))
        self._curve = self.plot.plot([], [], pen=pg.mkPen("#1f77b4", width=2),
                                     symbol="o", symbolSize=6)
        layout.addWidget(self.plot, stretch=1)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["days", "k-effective"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setMaximumHeight(160)
        layout.addWidget(self.table)

    def _on_norm_changed(self) -> None:
        if self.norm_combo.currentIndex() == 0:
            self.value_spin.setValue(1.0)       # MW
        else:
            self.value_spin.setValue(1.0e16)    # n/s

    # ---- run --------------------------------------------------------------
    def _config(self) -> DepletionConfig:
        steps = [self.step_days_spin.value()] * self.steps_spin.value()
        if self.norm_combo.currentIndex() == 0:
            return DepletionConfig(steps, normalization="power",
                                   power_watts=self.value_spin.value() * 1.0e6,
                                   integrator=self.integrator_combo.currentText())
        return DepletionConfig(steps, normalization="source-rate",
                               source_rate=self.value_spin.value(),
                               integrator=self.integrator_combo.currentText())

    def _start(self) -> None:
        if self._thread is not None:
            return
        from .main_window import _inactive_for

        batches = self.batches_spin.value()
        model = self.main._build_base_model(
            batches, self.particles_spin.value(), _inactive_for(batches),
            seed=self.main.seed_spin.value(),
        )
        fuel = depletion.fuel_material(model)
        try:
            vol = depletion.fuel_volume(self.main.spec.key,
                                        self.main._param_values[self.main._template])
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        if fuel is None:
            self.status.setText("No depletable (fuel) material in this model.")
            return

        self._runner = DepletionRunner(cross_sections=self.main._cross_sections)
        self._worker = _DepletionWorker(
            self._runner, model, self._config(), self.main._run_root / "depletion",
            fuel.id, vol,
        )
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.started.connect(self._on_started)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)

        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.export_btn.setEnabled(False)
        self.status.setText("Depleting — this can take several minutes…")
        self._thread.start()

    def _on_started(self, steps: int) -> None:
        self.status.setText(f"Depleting {steps} steps — this can take several minutes…")

    @Slot(object)
    def _on_finished(self, result) -> None:
        self._teardown()
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._result = result
        if result.error:
            self.status.setText(f"Depletion failed: {result.error}")
            return
        if not result.keff:
            self.status.setText("Depletion produced no results (cancelled?).")
            return
        self._curve.setData(result.days, result.keff)
        self.table.setRowCount(len(result.days))
        for r, (d, k) in enumerate(zip(result.days, result.keff)):
            self.table.setItem(r, 0, QTableWidgetItem(f"{d:g}"))
            self.table.setItem(r, 1, QTableWidgetItem(f"{k:.5f}"))
        self.export_btn.setEnabled(True)
        self.status.setText(f"Done — {len(result.days)} burnup points.")

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._teardown()
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status.setText(f"Error: {message}")

    def _cancel(self) -> None:
        if self._runner is not None:
            self._runner.cancel()
        self.status.setText("Stopping…")

    def _teardown(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._thread = self._worker = None

    def _export(self) -> None:
        if not self._result or not self._result.keff:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export burnup data", "burnup.csv",
                                              "CSV (*.csv)")
        if not path:
            return
        import csv

        with open(path, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["days", "keff", "keff_std"])
            for d, k, s in zip(self._result.days, self._result.keff, self._result.keff_std):
                writer.writerow([d, k, s])
        self.status.setText(f"Exported to {path}")

    def closeEvent(self, event) -> None:
        self._cancel()
        self._teardown()
        super().closeEvent(event)
