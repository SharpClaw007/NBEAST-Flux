"""Reactor poisoning — equilibrium Xe-135 & Sm-149 reactivity worth.

Two-pass, spectrum-consistent: it first runs the clean model, folds that run's flux
spectrum with the Xe/Sm/U-235 pointwise data to get spectrum-averaged one-group cross
sections, then computes the equilibrium poison concentrations from those (rather than
2200 m/s constants) and re-runs with equilibrium Sm-149, then Xe-135 + Sm-149. Reports
each poison's reactivity worth (Δρ in pcm). Needs Xe-135/Sm-149 cross sections (not in
the bundled H/O/U/Zr library), so it offers a download when they're missing.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
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

# The 3 evaluations, in run order.
_CASES = ("clean", "+ Sm-149", "+ Xe-135 & Sm-149")


class _PoisonWorker(QObject):
    """Runs clean → (spectrum-averaged σ) → +Sm → +Xe+Sm off the UI thread."""

    case = Signal(int, float)     # case index, k-effective
    progress = Signal(str)
    finished = Signal(object)     # {"sigma": {...}, "xe": r, "sm": r} or None
    failed = Signal(str)

    def __init__(self, spec, base, mats, batches, particles, inactive, seed,
                 flux, run_root, cross_sections):
        super().__init__()
        self._spec = spec
        self._base, self._mats = base, mats
        self._batches, self._particles = batches, particles
        self._inactive, self._seed = inactive, seed
        self._flux = flux
        self._run_root = Path(run_root)
        self._xs = cross_sections
        self._runner = None
        self._stop = False

    def _build(self, poison):
        return self._spec.build(batches=self._batches, particles=self._particles,
                                inactive=self._inactive, seed=self._seed,
                                poison=poison, **self._mats, **self._base)

    def _run_case(self, index, poison, subdir, add_spectrum=False):
        from nbeast.core import tallies
        from nbeast.core.runner import Runner

        model = self._build(poison)
        if add_spectrum:
            tallies.add_flux_spectrum(model)
        self._runner = Runner(cross_sections=self._xs)
        result = self._runner.run(model, self._run_root / subdir)
        if result.cancelled or self._stop:
            return None
        if result.error or result.keff is None:
            raise RuntimeError(result.error or f"{_CASES[index]} run produced no k")
        self.case.emit(index, float(result.keff))
        return result

    @Slot()
    def run(self):
        try:
            # Pass 1 — clean run, carrying a flux-spectrum tally.
            self.progress.emit("Clean run (for the flux spectrum)…")
            clean = self._run_case(0, None, "clean", add_spectrum=True)
            if clean is None:
                return self.finished.emit(None)

            # Spectrum-averaged one-group cross sections from the clean spectrum.
            sigma = {}
            try:
                from nbeast.core import results

                with results.Results(clean.statepoint) as res:
                    spec = res.flux_spectrum()
                sigma = poisons.spectrum_averaged_xs(spec.energy_edges, spec.flux, self._xs)
            except Exception:  # noqa: BLE001 — fall back to 2200 m/s constants
                sigma = {}
            xe, sm = poisons.equilibrium_ratios(self._flux, **sigma)

            self.progress.emit("Equilibrium Sm-149…")
            if self._run_case(1, (0.0, sm), "sm") is None:
                return self.finished.emit(None)
            self.progress.emit("Equilibrium Xe-135 + Sm-149…")
            if self._run_case(2, (xe, sm), "both") is None:
                return self.finished.emit(None)

            self.finished.emit({"sigma": sigma, "xe": xe, "sm": sm})
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))

    def cancel(self):
        self._stop = True
        if self._runner is not None:
            self._runner.cancel()


class PoisoningDialog(QDialog):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main = main_window
        self.setWindowTitle("Reactor poisoning — Xe-135 / Sm-149 worth")
        self.resize(560, 480)
        self._k: dict[int, float] = {}
        self._thread = None
        self._worker = None

        self._build_ui()
        self._refresh_availability()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        intro = QLabel(
            "Xe-135 and Sm-149 are the reactor 'poisons' — fission products with huge "
            "thermal absorption that build to an equilibrium and cost reactivity. This "
            "runs the model clean vs. poisoned and reports each one's worth (Δρ), using "
            "cross sections spectrum-averaged over the clean run's own flux."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #555;")
        layout.addWidget(intro)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.level_combo = QComboBox()
        # Default to a realistic operating flux; saturation is the conservative bound.
        self.level_combo.addItem("Equilibrium at φ = 3×10¹³ n/cm²·s (typical)", 3e13)
        self.level_combo.addItem("Equilibrium at φ = 1×10¹³ n/cm²·s", 1e13)
        self.level_combo.addItem("Equilibrium at φ = 1×10¹⁴ n/cm²·s", 1e14)
        self.level_combo.addItem("Saturation (max Xe — conservative upper bound)", None)
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
        self.stop_btn.clicked.connect(self._cancel)
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
    def _start(self) -> None:
        if self._thread is not None:
            return
        from .main_window import _inactive_for

        main = self.main
        batches = self.batches_spin.value()
        worker = _PoisonWorker(
            spec=main.spec,
            base=dict(main._param_values[main._template]),
            mats=dict(main._material_values[main._template]),
            batches=batches,
            particles=self.particles_spin.value(),
            inactive=_inactive_for(batches),
            seed=main.seed_spin.value(),
            flux=self.level_combo.currentData(),
            run_root=main._run_root / "poison",
            cross_sections=main._cross_sections,
        )
        self._k = {}
        self.result.setText("")
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status.setText("Starting…")

        self._thread = QThread()
        self._worker = worker
        worker.moveToThread(self._thread)
        self._thread.started.connect(worker.run)
        worker.case.connect(self._on_case)
        worker.progress.connect(lambda m: self.status.setText(m))
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        self._thread.start()

    def _cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def _teardown(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(10_000)
        self._thread = self._worker = None

    @Slot(int, float)
    def _on_case(self, index: int, k: float) -> None:
        self._k[index] = k
        self.status.setText(f"{_CASES[index]}: k = {k:.5f}")

    @Slot(object)
    def _on_finished(self, info) -> None:
        self._teardown()
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if not ({0, 1, 2} <= self._k.keys()):
            self.status.setText("Stopped before all cases completed.")
            return
        rho = {i: reactivity.reactivity_pcm(self._k[i]) for i in (0, 1, 2)}
        sm_worth = rho[1] - rho[0]
        xe_worth = rho[2] - rho[1]
        total = rho[2] - rho[0]
        sigma = (info or {}).get("sigma", {})
        if sigma:
            note = (f"Spectrum-averaged σ: σ_f(U235) = {sigma.get('sigma_f_u235', 0):.1f} b, "
                    f"σ_a(Xe135) = {sigma.get('sigma_a_xe', 0):.3g} b, "
                    f"σ_a(Sm149) = {sigma.get('sigma_a_sm', 0):.3g} b.")
        else:
            note = "Used 2200 m/s cross sections (spectrum averaging unavailable)."
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
            f"<p style='color:#777'>{note} Typical reference: Xe-135 ≈ −2600 to −3000 pcm, "
            "Sm-149 ≈ −900 to −1300 pcm.</p>"
        )
        self.status.setText("Done.")

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._teardown()
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status.setText(f"Error: {message}")

    def closeEvent(self, event) -> None:
        self._cancel()
        self._teardown()
        super().closeEvent(event)
