"""Reactor poisoning — equilibrium Xe-135 & Sm-149 reactivity worth.

Runs the model clean, then with equilibrium Sm-149, then with Xe-135 + Sm-149, and
reports each poison's reactivity worth (Δρ in pcm). Needs Xe-135/Sm-149 cross sections
(not in the bundled H/O/U/Zr library), so it offers a download when they're missing.
Thermal-lattice, saturation approximation (see :mod:`nbeast.core.poisons`).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from nbeast.core import poisons, reactivity

from .sweep_dialog import SweepController

# The 3 evaluations: (label, poison-config-builder given (xe, sm)).
_CASES = ("clean", "+ Sm-149", "+ Xe-135 & Sm-149")


class PoisoningDialog(QDialog):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main = main_window
        self.setWindowTitle("Reactor poisoning — Xe-135 / Sm-149 worth")
        self.resize(560, 460)
        self._k: dict[int, float] = {}

        self.controller = SweepController(self)
        self.controller.point.connect(self._on_point)
        self.controller.progress.connect(lambda m: self.status.setText(m))
        self.controller.finished.connect(self._on_finished)
        self.controller.failed.connect(self._on_failed)

        self._build_ui()
        self._refresh_availability()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        intro = QLabel(
            "Xe-135 and Sm-149 are the reactor 'poisons' — fission products with huge "
            "thermal absorption that build to an equilibrium and cost reactivity. This "
            "runs the model clean vs. poisoned and reports each one's worth (Δρ)."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #555;")
        layout.addWidget(intro)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.level_combo = QComboBox()
        self.level_combo.addItem("Equilibrium at saturation (max Xe)", None)
        self.level_combo.addItem("Equilibrium at φ = 1×10¹³ n/cm²·s", 1e13)
        self.level_combo.addItem("Equilibrium at φ = 1×10¹⁴ n/cm²·s", 1e14)
        self.batches_spin = QSpinBox()
        self.batches_spin.setRange(20, 100_000)
        self.batches_spin.setValue(80)
        self.particles_spin = QSpinBox()
        self.particles_spin.setRange(100, 10_000_000)
        self.particles_spin.setSingleStep(500)
        self.particles_spin.setValue(2000)
        form.addRow("Xe-135 level:", self.level_combo)
        form.addRow("Batches / run:", self.batches_spin)
        form.addRow("Particles / batch:", self.particles_spin)
        layout.addLayout(form)

        controls = QHBoxLayout()
        self.run_btn = QPushButton("Run")
        self.run_btn.setDefault(True)
        self.run_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.controller.cancel)
        self.download_btn = QPushButton("Download Xe/Sm data…")
        self.download_btn.clicked.connect(self._download)
        controls.addWidget(self.run_btn)
        controls.addWidget(self.stop_btn)
        controls.addStretch(1)
        controls.addWidget(self.download_btn)
        layout.addLayout(controls)

        self.status = QLabel("Ready.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #555;")
        layout.addWidget(self.status)

        self.result = QLabel("")
        self.result.setWordWrap(True)
        self.result.setTextFormat(Qt.RichText)
        layout.addWidget(self.result, stretch=1)

    # ---- availability -----------------------------------------------------
    def _refresh_availability(self) -> None:
        available = poisons.is_available(self.main._cross_sections)
        self.run_btn.setEnabled(available)
        self.download_btn.setVisible(not available)
        if not available:
            self.status.setText(
                "Xe-135 / Sm-149 cross sections aren't in the active library — "
                "download them to enable poisoning."
            )

    def _download(self) -> None:
        self.main._open_data_library(focus_category="Poisons")
        self._refresh_availability()

    # ---- run --------------------------------------------------------------
    def _make_builder(self):
        from .main_window import _inactive_for

        main = self.main
        spec = main.spec
        base = dict(main._param_values[main._template])
        mats = dict(main._material_values[main._template])
        batches = self.batches_spin.value()
        particles = self.particles_spin.value()
        inactive = _inactive_for(batches)
        seed = main.seed_spin.value()
        xe, sm = poisons.equilibrium_ratios(self.level_combo.currentData())
        configs = {0: None, 1: (0.0, sm), 2: (xe, sm)}   # clean, +Sm, +Xe+Sm

        def builder(x: float):
            return spec.build(batches=batches, particles=particles, inactive=inactive,
                              seed=seed, poison=configs[int(round(x))], **mats, **base)

        return builder

    def _start(self) -> None:
        if self.controller.running:
            return
        self._k = {}
        self.result.setText("")
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status.setText("Running clean + poisoned cases…")
        self.controller.start(("sweep", [0.0, 1.0, 2.0]), self._make_builder(),
                              self.main._run_root / "poison", self.main._cross_sections)

    def _on_point(self, x: float, k: float, std: float) -> None:
        idx = int(round(x))
        self._k[idx] = k
        self.status.setText(f"{_CASES[idx]}: k = {k:.5f}")

    def _on_finished(self, summary) -> None:
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if {0, 1, 2} <= self._k.keys():
            rho = {i: reactivity.reactivity_pcm(self._k[i]) for i in (0, 1, 2)}
            sm_worth = rho[1] - rho[0]
            xe_worth = rho[2] - rho[1]
            total = rho[2] - rho[0]
            self.result.setText(
                "<table cellpadding=4>"
                f"<tr><td><b>Clean k</b></td><td>{self._k[0]:.5f}</td><td></td></tr>"
                f"<tr><td>Sm-149 worth</td><td>{sm_worth:+.0f} pcm</td>"
                f"<td>(k → {self._k[1]:.5f})</td></tr>"
                f"<tr><td>Xe-135 worth</td><td>{xe_worth:+.0f} pcm</td>"
                f"<td>(k → {self._k[2]:.5f})</td></tr>"
                f"<tr><td><b>Total poison worth</b></td><td><b>{total:+.0f} pcm</b></td>"
                f"<td></td></tr>"
                "</table>"
                "<p style='color:#777'>Thermal-lattice saturation estimate. Typical "
                "reference: Xe-135 ≈ −2600 to −3000 pcm, Sm-149 ≈ −900 to −1300 pcm.</p>"
            )
            self.status.setText("Done.")
        else:
            self.status.setText("Stopped before all cases completed.")

    def _on_failed(self, message: str) -> None:
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status.setText(f"Error: {message}")

    def closeEvent(self, event) -> None:
        self.controller.stop_and_wait()
        super().closeEvent(event)
