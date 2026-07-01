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
    completed = Signal(dict)              # {keff, keff_std, h5m}

    def __init__(self, cross_sections: str | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import CAD geometry (DAGMC)")
        self.resize(980, 640)
        self._cross_sections = cross_sections
        self._thread = None
        self._worker = None
        self._on_done_cb = None
        self._stls = None            # per-solid tessellated STLs, for the live preview
        self._inspected_path = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Import a STEP file and assign a material to each solid. The 3-D preview "
            "colours each solid by its material, so you can see exactly what you're "
            "assigning to which part."
        ))

        # STEP file picker — inspection + preview are automatic once a file is chosen.
        picker = QHBoxLayout()
        self.step_edit = QLineEdit()
        self.step_edit.setPlaceholderText("path to a .step / .stp file")
        self.step_edit.editingFinished.connect(self._inspect)
        picker.addWidget(self.step_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        picker.addWidget(browse)
        self.inspect_btn = QPushButton("Inspect")  # kept for _set_busy; auto-triggered
        self.inspect_btn.clicked.connect(self._inspect)
        self.inspect_btn.hide()
        picker.addWidget(self.inspect_btn)
        layout.addLayout(picker)

        # Split: material assignments (left) | live colour-coded 3-D preview (right).
        split = QHBoxLayout()
        left = QVBoxLayout()
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Solid", "Material"])
        self.table.horizontalHeader().setStretchLastSection(True)
        left.addWidget(self.table, 1)

        form = QFormLayout()
        self.max_mesh = QDoubleSpinBox(); self.max_mesh.setRange(0.1, 1000); self.max_mesh.setValue(10.0)
        self.min_mesh = QDoubleSpinBox(); self.min_mesh.setRange(0.01, 1000); self.min_mesh.setValue(1.0)
        self.batches = QSpinBox(); self.batches.setRange(2, 100000); self.batches.setValue(50)
        self.particles = QSpinBox(); self.particles.setRange(100, 100000000); self.particles.setValue(2000)
        form.addRow("Max mesh size:", self.max_mesh)
        form.addRow("Min mesh size:", self.min_mesh)
        form.addRow("Batches:", self.batches)
        form.addRow("Particles/batch:", self.particles)
        left.addLayout(form)

        self.status = QLabel("Pick a STEP file to preview it.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #555;")
        left.addWidget(self.status)

        split.addLayout(left, 2)

        from .viewport3d import FluxViewport
        self.preview3d = FluxViewport()
        self.preview3d.setMinimumWidth(430)
        split.addWidget(self.preview3d, 3)
        layout.addLayout(split, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
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
            self._inspect()   # auto-inspect: go straight to material selection

    def _material_combo(self) -> QComboBox:
        combo = QComboBox()
        for tag, preset in cad.MATERIAL_PRESETS.items():
            combo.addItem(preset["label"], tag)
        return combo

    def _set_busy(self, busy: bool, message: str) -> None:
        has_solids = self.table.rowCount() > 0
        self.inspect_btn.setEnabled(not busy)
        self.run_btn.setEnabled(not busy and has_solids)
        self.status.setText(message)

    def _start(self, fn, on_done) -> None:
        # The worker's `done`/`failed` signals MUST land on a bound method of this
        # dialog (a main-thread QObject) so PySide delivers them QUEUED to the GUI
        # thread. Connecting a bare lambda/free function instead makes a DIRECT
        # connection that runs the callback — and its _teardown() — *on the worker
        # thread*, which then destroys the still-running QThread and aborts the app.
        self._on_done_cb = on_done
        self._thread = QThread()
        self._worker = _Worker(fn)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._dispatch_done)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    @Slot(object)
    def _dispatch_done(self, result) -> None:
        cb, self._on_done_cb = self._on_done_cb, None
        if cb is not None:
            cb(result)

    def _teardown(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._thread = self._worker = None
        self._on_done_cb = None

    # ---- inspect ---------------------------------------------------------
    def _inspect(self) -> None:
        if self._thread is not None:   # already busy (inspecting or running)
            return
        path = self.step_edit.text().strip()
        if not path:
            return
        if not os.path.exists(path):
            self.status.setText("That STEP file does not exist.")
            return
        if path == self._inspected_path and self.table.rowCount() > 0:
            return   # already inspected this file
        self._set_busy(True, "Inspecting STEP file…")
        self._start(lambda: cad.inspect_step(path), self._on_inspected)

    @Slot(object)
    def _on_inspected(self, info) -> None:
        self._teardown()
        self._inspected_path = self.step_edit.text().strip()
        self._stls = None
        # inspect_step returns a dict; the UI unit test passes a bare count.
        n_solids = info["n_solids"] if isinstance(info, dict) else int(info)
        extent = info.get("extent") if isinstance(info, dict) else None
        presets = list(cad.MATERIAL_PRESETS.keys())
        self.table.setRowCount(n_solids)
        for i in range(n_solids):
            self.table.setItem(i, 0, QTableWidgetItem(f"Solid {i}"))
            combo = self._material_combo()
            combo.setCurrentIndex(i % len(presets))   # distinct default colours per solid
            combo.currentIndexChanged.connect(lambda _idx, r=i: self._on_material_changed(r))
            self.table.setCellWidget(i, 1, combo)
            self._recolor_row(i)

        note = f"{n_solids} solid(s) found — assign materials, then Generate & run."
        if extent:
            # Scale mesh sizes to the geometry so faceting is fine enough to stay
            # watertight (coarse meshing on small parts loses particles at run time).
            mx = min(max(extent / 10.0, self.max_mesh.minimum()), self.max_mesh.maximum())
            mn = min(max(extent / 40.0, self.min_mesh.minimum()), self.min_mesh.maximum())
            self.max_mesh.setValue(mx)
            self.min_mesh.setValue(mn)
            note = f"{n_solids} solid(s), size ≈ {extent:g} — mesh sized to fit."
        self._set_busy(False, note)   # solids present → enable Generate & run
        self._start_tessellate()      # then auto-build the colour-coded 3-D preview

    # ---- live colour-coded 3D preview ------------------------------------
    def _start_tessellate(self) -> None:
        if self._thread is not None:
            return
        path = self.step_edit.text().strip()
        if not path or not os.path.exists(path):
            return
        out_dir = tempfile.mkdtemp(prefix="nbeast_cad_prev_")
        self._set_busy(True, "Building the 3-D preview…")
        self._start(lambda: cad.tessellate(path, out_dir), self._on_tessellated)

    @Slot(object)
    def _on_tessellated(self, stls) -> None:
        self._teardown()
        self._stls = list(stls)
        self._render_preview()
        self._set_busy(
            False,
            f"{len(stls)} solid(s), colour-coded by material — assign, then Generate & run."
        )

    def _colors_labels(self) -> tuple[list, list]:
        tags = [self.table.cellWidget(i, 1).currentData() for i in range(self.table.rowCount())]
        colors = [cad.MATERIAL_PRESETS[t]["color"] for t in tags]
        labels = [cad.MATERIAL_PRESETS[t]["label"] for t in tags]
        return colors, labels

    def _render_preview(self) -> None:
        if not self._stls:
            return
        colors, labels = self._colors_labels()
        self.preview3d.show_cad(self._stls, colors, title="CAD geometry", labels=labels)

    def _recolor_row(self, row: int) -> None:
        """Tint the Solid cell with its material colour so the table maps to the 3-D view."""
        from PySide6.QtGui import QColor

        combo = self.table.cellWidget(row, 1)
        item = self.table.item(row, 0)
        if combo is None or item is None:
            return
        color = cad.MATERIAL_PRESETS.get(combo.currentData(), {}).get("color")
        if color:
            item.setBackground(QColor(color))

    def _on_material_changed(self, row: int) -> None:
        self._recolor_row(row)
        self._render_preview()

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
            return {**res, "h5m": h5m, "step": path, "material_tags": tags}

        self._set_busy(True, "Meshing geometry and running… (this can take a while)")
        self._start(job, self._on_done)

    @Slot(object)
    def _on_done(self, res: dict) -> None:
        self._teardown()
        if self._stls:  # overlay the coloured geometry in the result volume render
            colors, labels = self._colors_labels()
            res["stls"], res["colors"], res["labels"] = self._stls, colors, labels
        self._set_busy(False, f"Done.  k-eff = {res['keff']:.4f} ± {res['keff_std']:.4f}")
        self.completed.emit(res)

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._teardown()
        # Show the last meaningful line (the actual error), not the whole traceback dump.
        lines = [ln for ln in message.strip().splitlines() if ln.strip()]
        concise = lines[-1] if lines else "unknown error"
        self._set_busy(False, f"Failed: {concise[:400]}")

    def closeEvent(self, event) -> None:
        self._teardown()             # stop any worker thread before we're destroyed
        self.preview3d.finalize()    # release the embedded VTK interactor (else segfault)
        super().closeEvent(event)
