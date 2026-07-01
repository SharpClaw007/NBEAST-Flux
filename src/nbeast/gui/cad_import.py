"""CAD geometry import dialog (Phase 6, Stage E).

Import a STEP file, assign a material to each solid, mesh it to a DAGMC `.h5m`
(cad env) and run it to k-eff (dagmc-OpenMC env) — all off the UI thread via
nbeast.core.cad, which orchestrates the two native-arm64 envs. Gated on
cad.is_available(); only shown when the DAGMC envs are present.
"""

from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from nbeast.core import cad


class _Worker(QObject):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    @Slot()
    def run(self):
        try:
            self.done.emit(self._fn())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class CadImportDialog(QDialog):
    completed = Signal(dict)        # {keff, keff_std, h5m}
    preview = Signal(list, list)    # (stl_paths, colors) -> render in the 3D viewport

    def __init__(self, cross_sections: str | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import CAD geometry (DAGMC)")
        self.resize(560, 460)
        self._cross_sections = cross_sections
        self._thread = None
        self._worker = None
        self._preview_stls = None
        self._preview_colors = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Import a STEP file, assign a material to each solid, then mesh and run it "
            "as DAGMC geometry — natively on Apple Silicon."
        ))

        # STEP file picker
        picker = QHBoxLayout()
        self.step_edit = QLineEdit()
        self.step_edit.setPlaceholderText("path to a .step / .stp file")
        picker.addWidget(self.step_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        picker.addWidget(browse)
        self.inspect_btn = QPushButton("Inspect")
        self.inspect_btn.clicked.connect(self._inspect)
        picker.addWidget(self.inspect_btn)
        layout.addLayout(picker)

        # per-solid material assignment
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Solid", "Material"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        # mesh + run settings
        form = QFormLayout()
        self.max_mesh = QDoubleSpinBox(); self.max_mesh.setRange(0.1, 1000); self.max_mesh.setValue(10.0)
        self.min_mesh = QDoubleSpinBox(); self.min_mesh.setRange(0.01, 1000); self.min_mesh.setValue(1.0)
        self.batches = QSpinBox(); self.batches.setRange(2, 100000); self.batches.setValue(50)
        self.particles = QSpinBox(); self.particles.setRange(100, 100000000); self.particles.setValue(2000)
        form.addRow("Max mesh size:", self.max_mesh)
        form.addRow("Min mesh size:", self.min_mesh)
        form.addRow("Batches:", self.batches)
        form.addRow("Particles/batch:", self.particles)
        layout.addLayout(form)

        self.status = QLabel("Pick a STEP file and click Inspect.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #555;")
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.preview_btn = QPushButton("Preview 3D")
        self.preview_btn.setEnabled(False)
        self.preview_btn.clicked.connect(self._preview)
        buttons.addWidget(self.preview_btn)
        self.run_btn = QPushButton("Generate && run")
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self._run)
        buttons.addWidget(self.run_btn)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    # ---- helpers ---------------------------------------------------------
    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select STEP file", "", "STEP (*.step *.stp)")
        if path:
            self.step_edit.setText(path)

    def _material_combo(self) -> QComboBox:
        combo = QComboBox()
        for tag, preset in cad.MATERIAL_PRESETS.items():
            combo.addItem(preset["label"], tag)
        return combo

    def _set_busy(self, busy: bool, message: str) -> None:
        has_solids = self.table.rowCount() > 0
        self.inspect_btn.setEnabled(not busy)
        self.preview_btn.setEnabled(not busy and has_solids)
        self.run_btn.setEnabled(not busy and has_solids)
        self.status.setText(message)

    def _start(self, fn, on_done) -> None:
        self._thread = QThread()
        self._worker = _Worker(fn)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(on_done)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    def _teardown(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._thread = self._worker = None

    # ---- inspect ---------------------------------------------------------
    def _inspect(self) -> None:
        path = self.step_edit.text().strip()
        if not path or not os.path.exists(path):
            self.status.setText("That STEP file does not exist.")
            return
        self._set_busy(True, "Inspecting STEP file…")
        self._start(lambda: cad.inspect_step(path), self._on_inspected)

    @Slot(object)
    def _on_inspected(self, info) -> None:
        self._teardown()
        # inspect_step returns a dict; the UI unit test passes a bare count.
        n_solids = info["n_solids"] if isinstance(info, dict) else int(info)
        extent = info.get("extent") if isinstance(info, dict) else None
        self.table.setRowCount(n_solids)
        for i in range(n_solids):
            self.table.setItem(i, 0, QTableWidgetItem(f"Solid {i}"))
            self.table.setCellWidget(i, 1, self._material_combo())

        note = f"{n_solids} solid(s) found — assign materials, then Generate & run."
        if extent:
            # Scale mesh sizes to the geometry so faceting is fine enough to stay
            # watertight (coarse meshing on small parts loses particles at run time).
            mx = min(max(extent / 10.0, self.max_mesh.minimum()), self.max_mesh.maximum())
            mn = min(max(extent / 40.0, self.min_mesh.minimum()), self.min_mesh.maximum())
            self.max_mesh.setValue(mx)
            self.min_mesh.setValue(mn)
            note = (f"{n_solids} solid(s), size ≈ {extent:g} — mesh sized to fit. "
                    "Assign materials, then Generate & run.")
        self._set_busy(False, note)

    # ---- 3D preview ------------------------------------------------------
    def _preview(self) -> None:
        path = self.step_edit.text().strip()
        tags = [self.table.cellWidget(i, 1).currentData() for i in range(self.table.rowCount())]
        out_dir = tempfile.mkdtemp(prefix="nbeast_cad_prev_")
        self._set_busy(True, "Tessellating geometry for the 3D preview…")
        self._start(lambda: cad.tessellate(path, out_dir), lambda stls: self._on_preview(stls, tags))

    @Slot(object)
    def _on_preview(self, stls, tags) -> None:
        self._teardown()
        colors = [cad.MATERIAL_PRESETS[t]["color"] for t in tags]
        self._preview_stls = list(stls)          # reused for the volume-render overlay
        self._preview_colors = colors
        self._set_busy(False, f"Previewing {len(stls)} solid(s) — coloured by material.")
        self.preview.emit(list(stls), colors)

    # ---- generate + run --------------------------------------------------
    def _run(self) -> None:
        path = self.step_edit.text().strip()
        tags = [self.table.cellWidget(i, 1).currentData() for i in range(self.table.rowCount())]
        out = os.path.join(tempfile.mkdtemp(prefix="nbeast_cad_"), "model.h5m")
        max_m, min_m = self.max_mesh.value(), self.min_mesh.value()
        batches, particles = self.batches.value(), self.particles.value()
        xs = self._cross_sections

        def job():
            h5m = cad.generate_h5m(path, tags, out, max_mesh_size=max_m, min_mesh_size=min_m)
            res = cad.run_model(h5m, cad.material_specs(tags), batches=batches,
                                particles=particles, cross_sections=xs)
            return {**res, "h5m": h5m}

        self._set_busy(True, "Meshing geometry and running… (this can take a while)")
        self._start(job, self._on_done)

    @Slot(object)
    def _on_done(self, res: dict) -> None:
        self._teardown()
        if self._preview_stls:  # overlay the geometry in the volume render
            res["stls"] = self._preview_stls
            res["colors"] = self._preview_colors
        self._set_busy(False, f"Done.  k-eff = {res['keff']:.4f} ± {res['keff_std']:.4f}")
        self.completed.emit(res)

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._teardown()
        self._set_busy(False, f"Failed: {message}")
