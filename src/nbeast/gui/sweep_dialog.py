"""Parameter sweep & criticality search — turn the k-eff button into an instrument.

Pick one model parameter and either:

* **Sweep** it over a range and watch k-effective respond, or
* **Criticality search** for the value that drives k to a target (default 1.0).

Each evaluation is a full OpenMC eigenvalue run, executed sequentially on a worker
thread so the dialog stays responsive and cancellable. The search *numerics* live in
:mod:`nbeast.core.sweep`; this module drives the runs and plots the result.
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
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from nbeast.core.runner import Runner
from nbeast.core.sweep import CriticalitySearch, sweep_values


# ---- off-thread driver ----------------------------------------------------
class _SweepWorker(QObject):
    point = Signal(float, float, float)   # x, keff, keff_std
    progress = Signal(str)
    finished = Signal(object)             # summary dict
    failed = Signal(str)

    def __init__(self, plan, builder, run_root, cross_sections):
        super().__init__()
        self._plan = plan          # ("sweep", values) | ("search", CriticalitySearch)
        self._builder = builder
        self._run_root = Path(run_root)
        self._cross_sections = cross_sections
        self._runner: Runner | None = None
        self._stop = False

    @Slot()
    def run(self) -> None:
        try:
            mode, payload = self._plan
            if mode == "sweep":
                self._run_sweep(payload)
            else:
                self._run_search(payload)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))

    def _evaluate(self, x: float, index: int, quality: int = 1) -> tuple[float, float] | None:
        """Evaluate k at one parameter value, or None if it couldn't be run (an
        invalid configuration builds/fails without killing the whole sweep).
        ``quality`` multiplies the per-run particle count (variance-aware search
        refinement); builders that don't take it are called plain."""
        try:
            self._runner = Runner(cross_sections=self._cross_sections)
            try:
                model = self._builder(x, quality) if quality > 1 else self._builder(x)
            except TypeError:
                model = self._builder(x)
            result = self._runner.run(model, self._run_root / f"pt{index:03d}")
        except Exception as exc:  # noqa: BLE001 — bad config for this point only
            self.progress.emit(f"Skipped {x:g}: {exc}")
            return None
        if result.error or result.cancelled or result.keff is None:
            return None
        return float(result.keff), float(result.keff_std or 0.0)

    def _run_sweep(self, values) -> None:
        points = []
        for i, x in enumerate(values):
            if self._stop:
                break
            self.progress.emit(f"Run {i + 1}/{len(values)}: {x:g}")
            ev = self._evaluate(x, i)
            if ev is None:
                if self._stop:
                    break
                continue  # skip a point that couldn't be evaluated, keep going
            k, std = ev
            points.append((x, k, std))
            self.point.emit(x, k, std)
        self.finished.emit({"mode": "sweep", "points": points, "stopped": self._stop})

    def _run_search(self, search: CriticalitySearch) -> None:
        i = 0
        failed = False
        while not self._stop:
            x = search.propose()
            if x is None:
                break
            quality = search.particles_factor()   # variance-aware: σ shrinks with bracket
            self.progress.emit(
                f"Search eval {i + 1}: {x:g}"
                + (f" (particles ×{quality})" if quality > 1 else "")
            )
            ev = self._evaluate(x, i, quality)
            if ev is None:
                failed = not self._stop  # an unevaluable point breaks the search
                break
            k, std = ev
            search.submit(x, k, std)               # σ travels with k — never discarded
            self.point.emit(x, k, std)
            i += 1
        summary = dict(search.solution)
        summary["mode"] = "search"
        summary["stopped"] = self._stop
        summary["failed"] = failed
        self.finished.emit(summary)

    def cancel(self) -> None:
        self._stop = True
        if self._runner is not None:
            self._runner.cancel()


class SweepController(QObject):
    point = Signal(float, float, float)
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _SweepWorker | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None

    def start(self, plan, builder, run_root, cross_sections) -> None:
        if self.running:
            return
        self._thread = QThread()
        self._worker = _SweepWorker(plan, builder, run_root, cross_sections)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.point.connect(self.point)
        self._worker.progress.connect(self.progress)
        self._worker.finished.connect(self._finish)
        self._worker.failed.connect(self._fail)
        self._thread.start()

    @Slot(object)
    def _finish(self, summary) -> None:
        self._teardown()
        self.finished.emit(summary)

    @Slot(str)
    def _fail(self, message) -> None:
        self._teardown()
        self.failed.emit(message)

    def _teardown(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._worker = None
        self._thread = None

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def stop_and_wait(self) -> None:
        self.cancel()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(10_000)
        self._worker = None
        self._thread = None


# ---- dialog ----------------------------------------------------------------
class SweepDialog(QDialog):
    studyResult = Signal(object)   # a core.studies.StudyResult when a run completes

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main = main_window
        self.setWindowTitle("Parameter sweep / criticality search")
        self.resize(760, 640)
        self._points: list[tuple[float, float, float]] = []
        self._critical_value: float | None = None

        self.controller = SweepController(self)
        self.controller.point.connect(self._on_point)
        self.controller.progress.connect(lambda m: self.status.setText(m))
        self.controller.finished.connect(self._on_finished)
        self.controller.failed.connect(self._on_failed)

        self._build_ui()
        self._on_param_changed()
        self._on_mode_changed()

    # ---- UI ---------------------------------------------------------------
    @staticmethod
    def _compact_form() -> QFormLayout:
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)  # don't stretch fields
        form.setLabelAlignment(Qt.AlignRight)
        form.setContentsMargins(10, 8, 10, 8)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)
        return form

    @staticmethod
    def _hug(group: QGroupBox) -> QGroupBox:
        group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)  # hug content
        return group

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # --- setup row: parameter + mode side by side ---
        top = QHBoxLayout()
        self.param_combo = QComboBox()
        self._params = list(self.main.spec.parameters)
        for p in self._params:
            self.param_combo.addItem(f"{p.label} ({p.unit})" if p.unit else p.label, p.key)
        self.param_combo.currentIndexChanged.connect(self._on_param_changed)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Sweep", "Criticality search"])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        top.addWidget(QLabel("Parameter:"))
        top.addWidget(self.param_combo, 1)
        top.addSpacing(16)
        top.addWidget(QLabel("Mode:"))
        top.addWidget(self.mode_combo, 1)
        layout.addLayout(top)

        # --- mode-specific inputs (only one visible at a time) ---
        mode_row = QHBoxLayout()
        mode_row.addWidget(self._build_sweep_group())
        mode_row.addWidget(self._build_search_group())
        mode_row.addWidget(self._build_quality_group())
        layout.addLayout(mode_row)

        # --- actions ---
        controls = QHBoxLayout()
        self.run_btn = QPushButton("Run")
        self.run_btn.setDefault(True)
        self.run_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.controller.cancel)
        self.apply_btn = QPushButton("Apply to model")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._apply_critical)
        self.export_btn = QPushButton("Export CSV")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export_csv)
        controls.addWidget(self.run_btn)
        controls.addWidget(self.stop_btn)
        controls.addStretch(1)
        controls.addWidget(self.apply_btn)
        controls.addWidget(self.export_btn)
        layout.addLayout(controls)

        self.status = QLabel("Ready.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #555;")
        layout.addWidget(self.status)

        # --- results plot (light, matches the rest of the app) ---
        self.plot = pg.PlotWidget()
        self.plot.setBackground("w")
        self.plot.setLabel("left", "k-effective")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        for name in ("left", "bottom"):
            self.plot.getAxis(name).setPen("#666")
            self.plot.getAxis(name).setTextPen("#333")
        self._curve = self.plot.plot(
            [], [], pen=pg.mkPen("#1f77b4", width=2),
            symbol="o", symbolSize=7, symbolBrush="#1f77b4", symbolPen="#1f77b4",
        )
        layout.addWidget(self.plot, stretch=1)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["parameter", "k-effective", "± pcm"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setMaximumHeight(170)
        layout.addWidget(self.table)

    def _build_sweep_group(self) -> QGroupBox:
        self.sweep_group = QGroupBox("Sweep range")
        form = self._compact_form()
        self.sweep_group.setLayout(form)
        self.lo_spin = QDoubleSpinBox()
        self.hi_spin = QDoubleSpinBox()
        for s in (self.lo_spin, self.hi_spin):
            s.setDecimals(4)
            s.setRange(-1e9, 1e9)
        self.n_spin = QSpinBox()
        self.n_spin.setRange(2, 50)
        self.n_spin.setValue(7)
        form.addRow("From:", self.lo_spin)
        form.addRow("To:", self.hi_spin)
        form.addRow("Points:", self.n_spin)
        return self._hug(self.sweep_group)

    def _build_search_group(self) -> QGroupBox:
        self.search_group = QGroupBox("Criticality search")
        form = self._compact_form()
        self.search_group.setLayout(form)
        self.target_spin = QDoubleSpinBox()
        self.target_spin.setDecimals(4)
        self.target_spin.setRange(0.1, 5.0)
        self.target_spin.setValue(1.0)
        self.blo_spin = QDoubleSpinBox()
        self.bhi_spin = QDoubleSpinBox()
        for s in (self.blo_spin, self.bhi_spin):
            s.setDecimals(4)
            s.setRange(-1e9, 1e9)
        self.maxeval_spin = QSpinBox()
        self.maxeval_spin.setRange(3, 30)
        self.maxeval_spin.setValue(12)
        form.addRow("Target k:", self.target_spin)
        form.addRow("Bracket from:", self.blo_spin)
        form.addRow("Bracket to:", self.bhi_spin)
        form.addRow("Max evaluations:", self.maxeval_spin)
        return self._hug(self.search_group)

    def _build_quality_group(self) -> QGroupBox:
        group = QGroupBox("Per-run quality")
        group.setToolTip("Each point is a full transport run — kept light for speed.")
        form = self._compact_form()
        group.setLayout(form)
        self.batches_spin = QSpinBox()
        self.batches_spin.setRange(10, 100_000)
        self.batches_spin.setValue(60)
        self.particles_spin = QSpinBox()
        self.particles_spin.setRange(100, 10_000_000)
        self.particles_spin.setSingleStep(500)
        self.particles_spin.setValue(1500)
        form.addRow("Batches:", self.batches_spin)
        form.addRow("Particles/batch:", self.particles_spin)
        return self._hug(group)

    # ---- reactions --------------------------------------------------------
    def _current_param(self):
        return self._params[self.param_combo.currentIndex()]

    def _on_param_changed(self) -> None:
        p = self._current_param()
        cur = self.main._param_values[self.main._template].get(p.key, p.default)
        lo = max(p.minimum, cur * 0.7)
        hi = min(p.maximum, cur * 1.3 if cur > 0 else cur + 1.0)
        if hi <= lo:
            lo, hi = p.minimum, p.maximum
        for s in (self.lo_spin, self.hi_spin, self.blo_spin, self.bhi_spin):
            s.setDecimals(p.decimals if p.kind == "float" else 0)
            s.setSingleStep(p.step)
        self.lo_spin.setValue(lo)
        self.hi_spin.setValue(hi)
        self.blo_spin.setValue(p.minimum)
        self.bhi_spin.setValue(p.maximum)
        # Put the unit in the label text — passing it as a pyqtgraph `units` triggers
        # SI-prefix rescaling (0.1 wt% -> "100 milli-wt%"), which is nonsense here.
        self.plot.setLabel("bottom", f"{p.label} ({p.unit})" if p.unit else p.label)

    def _on_mode_changed(self) -> None:
        is_search = self.mode_combo.currentIndex() == 1
        self.search_group.setVisible(is_search)
        self.sweep_group.setVisible(not is_search)

    # ---- run --------------------------------------------------------------
    def _make_builder(self):
        from .main_window import _inactive_for

        main = self.main
        spec = main.spec
        p = self._current_param()
        base = dict(main._param_values[main._template])
        mats = dict(main._material_values[main._template])
        batches = self.batches_spin.value()
        particles = self.particles_spin.value()
        inactive = _inactive_for(batches)
        seed = main.seed_spin.value()

        def builder(x: float, quality: int = 1):
            params = dict(base)
            params[p.key] = int(round(x)) if p.kind == "int" else x
            return spec.build(batches=batches, particles=particles * int(quality),
                              inactive=inactive, seed=seed, **mats, **params)

        return builder

    def _start(self) -> None:
        if self.controller.running:
            return
        p = self._current_param()
        if self.mode_combo.currentIndex() == 1:  # criticality search
            try:
                search = CriticalitySearch(
                    self.blo_spin.value(), self.bhi_spin.value(),
                    target=self.target_spin.value(),
                    max_evals=self.maxeval_spin.value(),
                    x_min=p.minimum, x_max=p.maximum,
                )
            except ValueError as exc:
                self.status.setText(f"Invalid bracket: {exc}")
                return
            plan = ("search", search)
            self._target = self.target_spin.value()
        else:
            values = sweep_values(self.lo_spin.value(), self.hi_spin.value(), self.n_spin.value())
            plan = ("sweep", values)
            self._target = None

        self._reset_results()
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status.setText("Starting…")
        self.controller.start(
            plan, self._make_builder(),
            self.main._run_root / "sweep", self.main._cross_sections,
        )

    def _reset_results(self) -> None:
        self._points = []
        self._critical_value = None
        self.apply_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.table.setRowCount(0)
        self._curve.setData([], [])
        for item in list(self.plot.items()):
            if isinstance(item, pg.InfiniteLine):
                self.plot.removeItem(item)
        if self._target is not None:
            self.plot.addLine(y=self._target, pen=pg.mkPen("#888", style=Qt.DashLine))

    def _on_point(self, x: float, k: float, std: float) -> None:
        self._points.append((x, k, std))
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(f"{x:g}"))
        self.table.setItem(row, 1, QTableWidgetItem(f"{k:.5f}"))
        self.table.setItem(row, 2, QTableWidgetItem(f"{std * 1e5:.0f}"))
        ordered = sorted(self._points, key=lambda t: t[0])
        self._curve.setData([t[0] for t in ordered], [t[1] for t in ordered])

    def _on_finished(self, summary) -> None:
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.export_btn.setEnabled(bool(self._points))
        if summary.get("mode") == "search":
            x = summary.get("x")
            x_std = summary.get("x_std")
            self._critical_value = x
            p = self._current_param()
            # A Monte Carlo answer is an interval, not a number: quote x ± σₓ (the
            # bracket endpoints' k-noise propagated through the false-position slope).
            interval = f"{x:.4f} ± {x_std:.4f}" if (x is not None and x_std) else (
                f"{x:.4f}" if x is not None else None)
            if x is not None and summary.get("converged"):
                self.apply_btn.setEnabled(True)
                self.status.setText(
                    f"Critical {p.label} = {interval} {p.unit} for k = "
                    f"{summary.get('target'):.4f} ({summary.get('n_evals')} evaluations)"
                    + ("" if summary.get("bracketed") else " — root not bracketed")
                )
            elif x is not None:
                self.apply_btn.setEnabled(True)
                self.status.setText(
                    f"Did not fully converge — best estimate {p.label} ≈ {interval} {p.unit} "
                    f"after {summary.get('n_evals')} evaluations."
                )
            else:
                self.status.setText("Search did not produce an estimate.")
        else:
            n = len(summary.get("points", []))
            self.status.setText(
                f"Sweep {'stopped' if summary.get('stopped') else 'complete'} — {n} points."
            )
        if summary.get("failed"):
            self.status.setText(
                self.status.text()
                + "  (stopped early — a configuration in the bracket couldn't be evaluated; "
                "narrow the bracket or check the material.)"
            )
        self._emit_study_result(summary)

    def _emit_study_result(self, summary) -> None:
        from datetime import datetime, timezone

        from nbeast.core.studies import StudyResult

        p = self._current_param()
        points = [(x, k, std) for x, k, std in self._points]
        if summary.get("mode") == "search":
            x, x_std = summary.get("x"), summary.get("x_std")
            text = (f"critical {p.label} = {x:.4f}"
                    + (f" ± {x_std:.4f}" if x_std else "") + f" {p.unit}") if x is not None \
                else "no estimate"
            scalars = {"x": x, "x_std": x_std}
        else:
            text = f"{len(points)} points swept over {p.label}"
            scalars = {}
        self.studyResult.emit(StudyResult(
            ok=bool(points), summary=text, scalars=scalars, points=points,
            created_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))

    def _on_failed(self, message: str) -> None:
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status.setText(f"Error: {message}")

    def _apply_critical(self) -> None:
        if self._critical_value is None:
            return
        p = self._current_param()
        value = int(round(self._critical_value)) if p.kind == "int" else self._critical_value
        self.main.set_param(p.key, value)
        self.status.setText(f"Set {p.label} = {value:g} {p.unit} in the model.")

    def _export_csv(self) -> None:
        if not self._points:
            return
        path, _filter = QFileDialog.getSaveFileName(self, "Export sweep data", "sweep.csv",
                                                    "CSV (*.csv)")
        if not path:
            return
        import csv

        p = self._current_param()
        with open(path, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([p.key, "keff", "keff_std"])
            for x, k, std in self._points:
                writer.writerow([x, k, std])
        self.status.setText(f"Sweep data exported to {path}")

    def closeEvent(self, event) -> None:
        self.controller.stop_and_wait()
        super().closeEvent(event)
