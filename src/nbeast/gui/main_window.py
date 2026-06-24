"""NBEAST main window — the Caedium-style shell with an editable model tree.

Toolbar = template pick + run settings + Run/Stop. The dockable **Model tree**
shows the current parameter values; selecting a group ("Materials"/"Geometry")
renders **editable fields** in the **Properties** panel. Edits drive the model
that Run builds — so what the tree shows is exactly what runs. Transport runs
off-thread via RunController.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
)

from nbeast.core import cad, specs, tallies

from .monitor import ConvergenceMonitor
from .run_controller import RunController
from .spectrum import SpectrumView
from .viewport3d import FluxViewport

_GROUPS = ("Materials", "Geometry")
FIELD_TITLES = {"flux": "Scalar flux", "fission": "Fission rate"}


def _inactive_for(batches: int) -> int:
    """A safe inactive-cycle count that leaves active batches even for small runs."""
    return min(20, max(5, batches // 5))


class MainWindow(QMainWindow):
    def __init__(self, run_root: str | Path | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NBEAST — neutron-flux Monte Carlo")
        self.resize(1100, 720)

        self._run_root = Path(run_root) if run_root else Path(tempfile.gettempdir()) / "nbeast"
        self._template = next(iter(specs.SPECS))  # "Pin cell"
        # Per-template current parameter values, initialised from defaults.
        self._param_values = {label: spec.defaults() for label, spec in specs.SPECS.items()}
        self._total_batches = 0
        self._statepoint: str | None = None
        self._cross_sections = os.environ.get("OPENMC_CROSS_SECTIONS")
        self.last_result = None

        self.controller = RunController()
        self.controller.started.connect(self._on_started)
        self.controller.batch.connect(self._on_batch)
        self.controller.finished.connect(self._on_finished)
        self.controller.failed.connect(self._on_failed)

        self._build_menu()
        self._build_toolbar()
        self._build_docks()
        self._build_central()
        self.statusBar().showMessage("Ready")
        self._refresh_tree()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        export_action = QAction("Export report…", self)
        export_action.triggered.connect(self._on_export)
        file_menu.addAction(export_action)

        data_action = QAction("Cross-section data…", self)
        data_action.triggered.connect(self._open_data_manager)
        file_menu.addAction(data_action)

        # CAD geometry import (DAGMC) — only when the native arm64 DAGMC envs exist.
        if cad.is_available():
            cad_action = QAction("Import CAD geometry…", self)
            cad_action.triggered.connect(self._open_cad_import)
            file_menu.addAction(cad_action)

        examples_menu = self.menuBar().addMenu("&Examples")
        for label, key in (
            ("Godiva — bare HEU sphere (k ≈ 1.0)", "godiva"),
            ("PWR pin cell (k∞ ≈ 1.41)", "pincell"),
            ("7×7 PWR fuel assembly", "assembly"),
        ):
            action = QAction(label, self)
            action.triggered.connect(lambda _checked=False, k=key: self.load_example(k))
            examples_menu.addAction(action)

    # Curated starting points: (template, param overrides, quality, status hint).
    _EXAMPLES = {
        "godiva": ("Godiva", {}, "High", "Godiva benchmark — expect k ≈ 1.0 (critical)."),
        "pincell": ("Pin cell", {}, "Standard", "PWR pin cell — expect k∞ ≈ 1.41."),
        "assembly": ("Fuel assembly", {"n_side": 7}, "Standard",
                     "7×7 PWR fuel assembly — expect k∞ ≈ 1.41."),
    }

    def load_example(self, key: str) -> None:
        template, overrides, quality, hint = self._EXAMPLES[key]
        self.set_template(template)
        values = self.spec.defaults()
        values.update(overrides)
        self._param_values[template] = values
        self.quality_combo.setCurrentText(quality)
        self._apply_quality(quality)
        self._refresh_tree()
        self.statusBar().showMessage(hint)

    # ---- construction -----------------------------------------------------
    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        tb.addWidget(QLabel(" Template: "))
        self.template_combo = QComboBox()
        self.template_combo.addItems(specs.SPECS.keys())
        self.template_combo.setToolTip("Choose the reactor model to simulate.")
        self.template_combo.currentTextChanged.connect(self.set_template)
        tb.addWidget(self.template_combo)

        tb.addSeparator()

        # Simple mode: one quality preset (sets batches + particles).
        self._quality_label_act = tb.addWidget(QLabel(" Quality: "))
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["Quick", "Standard", "High"])
        self.quality_combo.setCurrentText("Standard")
        self.quality_combo.setToolTip(
            "Run-quality preset (sets batches & particles). Switch on Advanced for full control."
        )
        self.quality_combo.currentTextChanged.connect(self._apply_quality)
        self._quality_combo_act = tb.addWidget(self.quality_combo)

        # Advanced mode: raw run settings.
        self._batches_label_act = tb.addWidget(QLabel(" Batches: "))
        self.batches_spin = QSpinBox()
        self.batches_spin.setRange(10, 100_000)
        self.batches_spin.setValue(100)
        self.batches_spin.setToolTip(
            "Monte Carlo batches (statistical samples). More batches → lower "
            "uncertainty but longer runtime. Early 'inactive' batches are discarded."
        )
        self.batches_spin.valueChanged.connect(lambda _: self._refresh_tree())
        self._batches_act = tb.addWidget(self.batches_spin)

        self._particles_label_act = tb.addWidget(QLabel(" Particles/batch: "))
        self.particles_spin = QSpinBox()
        self.particles_spin.setRange(100, 10_000_000)
        self.particles_spin.setSingleStep(1000)
        self.particles_spin.setValue(2000)
        self.particles_spin.setToolTip(
            "Neutrons simulated per batch. More → smoother flux/spectrum maps, "
            "longer runtime."
        )
        self.particles_spin.valueChanged.connect(lambda _: self._refresh_tree())
        self._particles_act = tb.addWidget(self.particles_spin)

        tb.addSeparator()
        self.run_action = QAction("Run", self)
        self.run_action.setToolTip("Run the k-effective (criticality) simulation.")
        self.run_action.triggered.connect(self.start_run)
        tb.addAction(self.run_action)
        self.stop_action = QAction("Stop", self)
        self.stop_action.setEnabled(False)
        self.stop_action.setToolTip("Stop the running simulation (keeps results so far).")
        self.stop_action.triggered.connect(self.stop_run)
        tb.addAction(self.stop_action)

        tb.addSeparator()
        self.advanced_check = QCheckBox("Advanced")
        self.advanced_check.setToolTip("Show expert run settings (batches, particles per batch).")
        self.advanced_check.toggled.connect(self._set_advanced)
        tb.addWidget(self.advanced_check)

        self._apply_quality("Standard")
        self._set_advanced(False)

    def _apply_quality(self, name: str) -> None:
        presets = {"Quick": (50, 1000), "Standard": (100, 2000), "High": (200, 5000)}
        batches, particles = presets.get(name, (100, 2000))
        self.batches_spin.setValue(batches)
        self.particles_spin.setValue(particles)

    def _set_advanced(self, advanced: bool) -> None:
        self._advanced = advanced
        for act in (self._batches_label_act, self._batches_act,
                    self._particles_label_act, self._particles_act):
            act.setVisible(advanced)
        for act in (self._quality_label_act, self._quality_combo_act):
            act.setVisible(not advanced)

    def _build_docks(self) -> None:
        self.model_tree = QTreeWidget()
        self.model_tree.setHeaderLabel("Model")
        self.model_tree.setToolTip(
            "The model being simulated. Click a group (Materials / Geometry) to edit "
            "its parameters in the Properties panel below."
        )
        self.model_tree.itemClicked.connect(self._on_tree_click)
        model_dock = QDockWidget("Model", self)
        model_dock.setWidget(self.model_tree)
        self.addDockWidget(Qt.LeftDockWidgetArea, model_dock)

        self.properties = QTableWidget(0, 2)
        self.properties.setHorizontalHeaderLabels(["Property", "Value"])
        self.properties.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.properties.verticalHeader().setVisible(False)
        props_dock = QDockWidget("Properties (select a group to edit)", self)
        props_dock.setWidget(self.properties)
        self.addDockWidget(Qt.LeftDockWidgetArea, props_dock)

        # Right dock: results field picker (enabled once a run finishes).
        self.results_list = QListWidget()
        for label, score in (
            ("Scalar flux", "flux"),
            ("Fission rate", "fission"),
            ("Neutron tracks", "tracks"),
        ):
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, score)
            self.results_list.addItem(item)
        self.results_list.setEnabled(False)
        self.results_list.setToolTip(
            "Pick a result to view: scalar flux, fission rate, or neutron tracks "
            "(available after a run)."
        )
        self.results_list.itemClicked.connect(self._on_results_clicked)
        results_dock = QDockWidget("Results", self)
        results_dock.setWidget(self.results_list)
        self.addDockWidget(Qt.RightDockWidgetArea, results_dock)

    def _build_central(self) -> None:
        self.tabs = QTabWidget()
        self.monitor = ConvergenceMonitor()
        self.flux_view = FluxViewport()
        self.spectrum_view = SpectrumView()
        self.tabs.addTab(self.monitor, "Convergence")
        self.tabs.addTab(self.flux_view, "Flux map")
        self.tabs.addTab(self.spectrum_view, "Spectrum")
        self.setCentralWidget(self.tabs)

    # ---- model tree -------------------------------------------------------
    @property
    def spec(self) -> specs.TemplateSpec:
        return specs.SPECS[self._template]

    def set_template(self, name: str) -> None:
        if name not in specs.SPECS:
            return
        self._template = name
        if self.template_combo.currentText() != name:
            self.template_combo.setCurrentText(name)
        self.properties.setRowCount(0)
        self._refresh_tree()

    def set_param(self, key: str, value: float) -> None:
        """Programmatic + UI entry point for editing a parameter."""
        self._param_values[self._template][key] = value
        self._refresh_tree()  # reflect new value in the tree (not Properties — keep editor focus)

    def _value_text(self, param: specs.Parameter) -> str:
        value = self._param_values[self._template][param.key]
        unit = f" {param.unit}" if param.unit else ""
        if param.kind == "int":
            return f"{param.label} = {int(value)}{unit}"
        return f"{param.label} = {value:.{param.decimals}f}{unit}"

    def _refresh_tree(self) -> None:
        self.model_tree.clear()
        spec = self.spec

        materials = QTreeWidgetItem(["Materials"])
        for label in spec.materials:
            materials.addChild(QTreeWidgetItem([label]))
        for p in spec.params_in("Materials"):
            materials.addChild(QTreeWidgetItem([self._value_text(p)]))

        geometry = QTreeWidgetItem(["Geometry"])
        geometry.addChild(QTreeWidgetItem([spec.geometry]))
        for p in spec.params_in("Geometry"):
            geometry.addChild(QTreeWidgetItem([self._value_text(p)]))

        settings = QTreeWidgetItem(["Settings"])
        settings.addChild(QTreeWidgetItem([f"batches = {self.batches_spin.value()}"]))
        settings.addChild(QTreeWidgetItem([f"particles/batch = {self.particles_spin.value()}"]))
        settings.addChild(QTreeWidgetItem([f"inactive = {_inactive_for(self.batches_spin.value())}"]))

        for item in (materials, geometry, settings):
            self.model_tree.addTopLevelItem(item)
            item.setExpanded(True)

    # ---- properties (editing) --------------------------------------------
    def _group_of(self, item: QTreeWidgetItem) -> str:
        return item.text(0) if item.parent() is None else item.parent().text(0)

    def _on_tree_click(self, item: QTreeWidgetItem, _column: int) -> None:
        group = self._group_of(item)
        params = self.spec.params_in(group) if group in _GROUPS else []
        if params:
            self._render_param_editors(group, params)
        else:
            self._render_readonly(group)

    def _render_param_editors(self, group: str, params: list[specs.Parameter]) -> None:
        self.properties.setRowCount(len(params))
        for row, p in enumerate(params):
            label = f"{p.label} ({p.unit})" if p.unit else p.label
            self.properties.setItem(row, 0, QTableWidgetItem(label))
            value = self._param_values[self._template][p.key]
            if p.kind == "int":
                editor = QSpinBox()
                editor.setRange(int(p.minimum), int(p.maximum))
                editor.setSingleStep(int(p.step))
                editor.setValue(int(value))
            else:
                editor = QDoubleSpinBox()
                editor.setRange(p.minimum, p.maximum)
                editor.setSingleStep(p.step)
                editor.setDecimals(p.decimals)
                editor.setValue(value)
            editor.valueChanged.connect(lambda v, key=p.key: self.set_param(key, v))
            self.properties.setCellWidget(row, 1, editor)

    def _render_readonly(self, group: str) -> None:
        if group == "Settings":
            rows = [
                ("batches", self.batches_spin.value()),
                ("particles/batch", self.particles_spin.value()),
                ("inactive", _inactive_for(self.batches_spin.value())),
                ("(edit batches/particles in the toolbar)", ""),
            ]
        else:
            rows = [("info", "fixed — not editable in v1")]
        self.properties.setRowCount(len(rows))
        for row, (key, value) in enumerate(rows):
            self.properties.setItem(row, 0, QTableWidgetItem(str(key)))
            self.properties.setItem(row, 1, QTableWidgetItem(str(value)))

    # ---- run lifecycle ----------------------------------------------------
    def _build_base_model(self, batches: int, particles: int, inactive: int):
        return self.spec.build(
            batches=batches,
            particles=particles,
            inactive=inactive,
            **self._param_values[self._template],
        )

    def _build_model(self):
        batches = self.batches_spin.value()
        model = self._build_base_model(
            batches, self.particles_spin.value(), _inactive_for(batches)
        )
        tallies.add_flux_spectrum(model, n_groups=100)
        tallies.add_flux_slice_mesh(model, n=40)
        return model

    def start_run(self) -> None:
        if self.controller.running:
            return
        model = self._build_model()
        self.monitor.reset()
        self.spectrum_view.clear()
        self.results_list.setEnabled(False)
        self.run_action.setEnabled(False)
        self.stop_action.setEnabled(True)
        self.statusBar().showMessage("Running…")
        self.controller.start(model, self._run_root / "current")

    def stop_run(self) -> None:
        self.controller.cancel()
        self.statusBar().showMessage("Stopping…")

    def _on_started(self, n_batches: int) -> None:
        self._total_batches = n_batches
        self.statusBar().showMessage(f"Running… 0/{n_batches} batches")

    def _on_batch(self, update) -> None:
        self.monitor.add_point(update.batch, update.keff, update.keff_std)
        self.statusBar().showMessage(
            f"Running… batch {update.batch}/{self._total_batches}  k = {update.keff:.5f}"
        )

    def _on_finished(self, result) -> None:
        self.last_result = result
        self.run_action.setEnabled(True)
        self.stop_action.setEnabled(False)
        k_txt = f"{result.keff:.5f}" if result.keff is not None else "n/a"
        if result.cancelled:
            self.statusBar().showMessage(f"Stopped at batch {len(result.batches)} (k ≈ {k_txt})")
        elif result.keff is not None:
            self.statusBar().showMessage(f"Done — k = {k_txt} ± {result.keff_std:.5f}")
        else:
            self.statusBar().showMessage("Done")
        if not result.cancelled and result.statepoint:
            self._load_results(result.statepoint)

    def _load_results(self, statepoint: str) -> None:
        """Populate spectrum + flux/fission views from a finished run (defensive)."""
        from nbeast.core.results import Results

        self._statepoint = statepoint
        try:
            with Results(statepoint) as results:
                spectrum = results.flux_spectrum()
                self.spectrum_view.set_spectrum(spectrum.energy_edges, spectrum.flux)
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(
                f"{self.statusBar().currentMessage()}  (spectrum unavailable: {exc})"
            )
        self.results_list.setEnabled(True)
        self.results_list.setCurrentRow(0)
        self._show_field("flux", switch_tab=False)

    def _show_field(self, score: str, switch_tab: bool = True) -> None:
        """Render the chosen mesh field (flux/fission) in the Flux-map tab."""
        if not self._statepoint:
            return
        from nbeast.core.results import Results

        try:
            vtk = Path(self._statepoint).parent / f"{score}.vtk"
            with Results(self._statepoint) as results:
                results.field_to_vtk(vtk, score)
            self.flux_view.show_field(vtk, score, FIELD_TITLES.get(score, score))
            if switch_tab:
                self.tabs.setCurrentWidget(self.flux_view)
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"Field '{score}' unavailable: {exc}")

    def _on_results_clicked(self, item) -> None:
        score = item.data(Qt.UserRole)
        if score == "tracks":
            self.show_tracks()
        else:
            self._show_field(score, switch_tab=True)

    def show_tracks(self) -> None:
        """Generate a few neutron tracks and render them in the Flux-map tab."""
        from nbeast.core import tracks

        self.statusBar().showMessage("Generating neutron tracks…")
        QApplication.processEvents()
        try:
            model = self._build_base_model(batches=1, particles=15, inactive=0)
            path = tracks.generate(model, n_particles=15, run_dir=self._run_root / "tracks")
            polylines = tracks.read_polylines(path, max_polylines=60)
            if not polylines:
                self.statusBar().showMessage("No neutron tracks were generated.")
                return
            self.flux_view.show_tracks(polylines, title=f"{self._template} — neutron tracks")
            self.tabs.setCurrentWidget(self.flux_view)
            self.statusBar().showMessage(f"Showing {len(polylines)} neutron tracks")
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"Track generation failed: {exc}")

    def _on_failed(self, message: str) -> None:
        self.last_result = None
        self.run_action.setEnabled(True)
        self.stop_action.setEnabled(False)
        self.statusBar().showMessage(f"Error: {message}")

    def _open_data_manager(self) -> None:
        from .data_manager import DataManagerDialog

        dialog = DataManagerDialog(active_xml=self._cross_sections, parent=self)
        dialog.activated.connect(self.set_active_library)
        dialog.exec()

    def _open_cad_import(self) -> None:
        from .cad_import import CadImportDialog

        dialog = CadImportDialog(cross_sections=self._cross_sections, parent=self)
        dialog.completed.connect(
            lambda res: self.statusBar().showMessage(
                f"CAD run: k-eff = {res['keff']:.4f} ± {res['keff_std']:.4f}"
            )
        )
        dialog.preview.connect(self._show_cad_preview)
        dialog.exec()

    def _show_cad_preview(self, stls, colors) -> None:
        """Render imported CAD solids (coloured by material) in the 3D viewport."""
        self.flux_view.show_cad(stls, colors, title="CAD geometry")
        self.tabs.setCurrentWidget(self.flux_view)

    def set_active_library(self, path: str) -> None:
        """Make a downloaded library the active one for model building + runs."""
        import openmc

        os.environ["OPENMC_CROSS_SECTIONS"] = path
        openmc.config["cross_sections"] = path
        self._cross_sections = path
        self.statusBar().showMessage(f"Active cross-section library: {path}")

    def _on_export(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Export report to folder…")
        if directory:
            self.export_report(directory)

    def export_report(self, out_dir):
        """Write the OpenMC deck + a PDF/PNG report + spectrum CSV to out_dir."""
        from nbeast.core import export
        from nbeast.gui import report

        out_dir = Path(out_dir)
        if not (self.last_result and self._statepoint):
            self.statusBar().showMessage("Run a simulation before exporting a report.")
            return None

        export.export_deck(self._build_model(), out_dir / "openmc_deck")

        values = self._param_values[self._template]
        lines = [
            f"k-effective = {self.last_result.keff:.5f} +/- {self.last_result.keff_std:.5f}",
            "",
            "Parameters:",
        ]
        for param in self.spec.parameters:
            value = values[param.key]
            text = f"{int(value)}" if param.kind == "int" else f"{value:.{param.decimals}f}"
            lines.append(f"  {param.label} = {text} {param.unit}".rstrip())
        lines.append(f"  batches = {self.batches_spin.value()}")
        lines.append(f"  particles/batch = {self.particles_spin.value()}")

        report.write_report(
            out_dir,
            title=f"Template: {self._template}",
            summary_lines=lines,
            result=self.last_result,
            statepoint=self._statepoint,
        )
        self.statusBar().showMessage(f"Report exported to {out_dir}")
        return out_dir

    def closeEvent(self, event) -> None:
        # Don't leave an OpenMC worker subprocess running after the window closes.
        self.controller.stop_and_wait()
        super().closeEvent(event)
