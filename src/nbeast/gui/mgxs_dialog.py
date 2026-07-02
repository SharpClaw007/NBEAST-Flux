"""Generate few-group cross sections from a Monte Carlo run.

Pick a group structure (e.g. CASMO-2 for fast/thermal) and a domain (per material
or per cell); NBEAST runs the current eigenvalue model with the collapsing tallies
attached, then reads back the group constants — total, absorption, fission,
ν-fission, χ — into a table that can be exported to CSV/HDF5 for a diffusion code.

The transport runs on a worker thread via :class:`RunController`; the
:class:`openmc.mgxs.Library` object is held across the run so its results can be
loaded from the statepoint when the run finishes.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
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

from nbeast.core import mgxs_gen

from .run_controller import RunController


class MgxsDialog(QDialog):
    studyResult = Signal(object)   # a core.studies.StudyResult when generation completes

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main = main_window
        self.setWindowTitle("Generate multigroup cross sections")
        self.resize(720, 560)
        self._library = None
        self._table = None

        self.controller = RunController(cross_sections=main_window._cross_sections)
        self.controller.finished.connect(self._on_finished)
        self.controller.failed.connect(self._on_failed)

        self._build_ui()
        if self.main._is_fixed_source:
            self.run_btn.setEnabled(False)
            self.status.setText(
                "Multigroup generation needs an eigenvalue model — pick a reactor "
                "template (not the shield slab)."
            )

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.structure_combo = QComboBox()
        self.structure_combo.addItems(mgxs_gen.GROUP_STRUCTURES)
        form.addRow("Group structure:", self.structure_combo)

        self.domain_combo = QComboBox()
        self.domain_combo.addItems(["material", "cell"])
        form.addRow("Domain:", self.domain_combo)

        self.batches_spin = QSpinBox()
        self.batches_spin.setRange(20, 100_000)
        self.batches_spin.setValue(100)
        form.addRow("Batches:", self.batches_spin)

        self.particles_spin = QSpinBox()
        self.particles_spin.setRange(100, 10_000_000)
        self.particles_spin.setSingleStep(500)
        self.particles_spin.setValue(2000)
        form.addRow("Particles/batch:", self.particles_spin)
        layout.addLayout(form)

        controls = QHBoxLayout()
        self.run_btn = QPushButton("Generate")
        self.run_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.controller.cancel)
        self.export_csv_btn = QPushButton("Export CSV")
        self.export_csv_btn.setEnabled(False)
        self.export_csv_btn.clicked.connect(lambda: self._export("csv"))
        self.export_h5_btn = QPushButton("Export HDF5")
        self.export_h5_btn.setEnabled(False)
        self.export_h5_btn.clicked.connect(lambda: self._export("h5"))
        for b in (self.run_btn, self.stop_btn, self.export_csv_btn, self.export_h5_btn):
            controls.addWidget(b)
        layout.addLayout(controls)

        self.status = QLabel("Ready")
        layout.addWidget(self.status)

        self.table = QTableWidget(0, 0)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, stretch=1)

    # ---- run --------------------------------------------------------------
    def _start(self) -> None:
        if self.controller.running:
            return
        from .main_window import _inactive_for

        batches = self.batches_spin.value()
        model = self.main._build_base_model(
            batches, self.particles_spin.value(), _inactive_for(batches),
            seed=self.main.seed_spin.value(),
        )
        try:
            self._library = mgxs_gen.build_library(
                model,
                structure=self.structure_combo.currentText(),
                domain_type=self.domain_combo.currentText(),
            )
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"Could not build library: {exc}")
            return
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.export_csv_btn.setEnabled(False)
        self.export_h5_btn.setEnabled(False)
        self.status.setText("Running transport…")
        self.controller.start(model, self.main._run_root / "mgxs")

    def _on_finished(self, result) -> None:
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if result.cancelled or not result.statepoint or self._library is None:
            self.status.setText("Generation cancelled.")
            return
        try:
            self._table = mgxs_gen.load_constants(self._library, result.statepoint)
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"Could not read constants: {exc}")
            return
        self._populate(self._table)
        self.export_csv_btn.setEnabled(True)
        self.export_h5_btn.setEnabled(True)
        n = self._table["n_groups"]
        summary = f"{n}-group constants for {len(self._table['domains'])} domains"
        self.status.setText(summary + "." + getattr(self, "_matrix_note", ""))
        from datetime import datetime, timezone

        from nbeast.core.studies import StudyResult

        self.studyResult.emit(StudyResult(
            ok=True, summary=summary,
            scalars={"n_groups": n, "domains": len(self._table["domains"])},
            created_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))

    def _on_failed(self, message: str) -> None:
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status.setText(f"Error: {message}")

    def _populate(self, table: dict) -> None:
        # The grid shows scalar (per-group) constants + the derived diffusion
        # coefficient; group-to-group matrices (e.g. the ν-scatter matrix) are
        # square, so they don't fit a per-group row — they go to the export.
        first = next(iter(table["domains"].values()), {})
        scalar_types = [mt for mt in table["mgxs_types"] if not first.get(mt, {}).get("matrix")]
        if "diffusion" in first:
            scalar_types = scalar_types + ["diffusion"]
        matrix_types = [mt for mt in table["mgxs_types"] if first.get(mt, {}).get("matrix")]
        bounds = table["group_bounds_eV"]
        columns = ["domain", "group", "E_low (eV)", "E_high (eV)"] + list(scalar_types)
        rows = []
        for domain, per_type in table["domains"].items():
            for g in range(table["n_groups"]):
                lo, hi = bounds[g]
                row = [domain, str(g + 1), f"{lo:.3g}", f"{hi:.3g}"]
                row += [f"{per_type[mt]['mean'][g]:.5g}" for mt in scalar_types]
                rows.append(row)
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(value))
        self._matrix_note = (
            f"  + {', '.join(matrix_types)} (group-to-group) in the export"
            if matrix_types else ""
        )

    def _export(self, fmt: str) -> None:
        if not self._table:
            return
        default = f"mgxs.{fmt}"
        flt = "CSV (*.csv)" if fmt == "csv" else "HDF5 (*.h5)"
        path, _ = QFileDialog.getSaveFileName(self, "Export multigroup constants", default, flt)
        if not path:
            return
        try:
            out = mgxs_gen.export_constants(self._table, path, fmt=fmt)
            self.status.setText(f"Exported to {out}")
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"Export failed: {exc}")

    def closeEvent(self, event) -> None:
        self.controller.stop_and_wait()
        super().closeEvent(event)
