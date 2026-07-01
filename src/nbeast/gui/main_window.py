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
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
)

from nbeast.core import cad, materials, specs, tallies
from nbeast.core.project import Project

from .history import HistoryPanel
from .monitor import ConvergenceMonitor
from .run_controller import RunController
from .spectrum import SpectrumView
from .viewport3d import FluxViewport

_GROUPS = ("Materials", "Geometry")
CAD_TEMPLATE = "Custom CAD (DAGMC)"   # a template entry that drives the CAD import flow
FIELD_TITLES = {
    "flux": "Scalar flux",
    "fission": "Fission rate",
    "absorption": "Absorption rate",
    "nu-fission": "Neutron production (ν-fission)",
    "heating": "Heating (energy deposition)",
    "dose": "Neutron dose rate",
    "flux_rel_err": "Flux relative error (1σ/mean)",
}


def _inactive_for(batches: int) -> int:
    """A safe inactive-cycle count that leaves active batches even for small runs."""
    return min(20, max(5, batches // 5))


class MainWindow(QMainWindow):
    def __init__(self, run_root: str | Path | None = None,
                 project_dir: str | Path | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NBEAST — neutron-flux Monte Carlo")
        self.resize(1100, 720)

        if run_root is not None:
            self._run_root = Path(run_root)
            default_project = self._run_root / "project"
        else:
            self._run_root = Path(tempfile.gettempdir()) / "nbeast"
            default_project = Path.home() / ".nbeast" / "default-project"
        self._template = next(iter(specs.SPECS))  # "Pin cell"
        # Per-template current parameter values, initialised from defaults.
        self._param_values = {label: spec.defaults() for label, spec in specs.SPECS.items()}
        # Per-template material selections (role key -> material catalog key).
        self._material_values = {
            label: spec.material_defaults() for label, spec in specs.SPECS.items()
        }
        # Custom-CAD template state (populated by the CAD import dialog).
        self._cad = {"step": None, "materials": []}
        self._cad_dialog = None   # the non-modal CAD import panel, when open
        self._cad_result = False  # current results are from a CAD run (render volumetric)
        self._cad_overlay = None  # (stls, colors, labels) geometry to overlay on CAD fields
        self._current_field_score = "flux"  # last field shown (for the 2D/3D toggle)
        self._unit_system = "SI"  # display units (SI / US-Imperial)
        self._power_w = 0.0       # reactor power (eigenvalue) for absolute units; 0 = relative
        self._source_strength = 0.0  # source rate n/s (fixed source) for absolute units
        self._total_batches = 0
        self._statepoint: str | None = None
        self._cross_sections = os.environ.get("OPENMC_CROSS_SECTIONS")
        self.last_result = None
        self.last_diagnostics = None

        # Persistent project: run history + last-used model state survive restarts.
        self.project = Project.open_or_create(project_dir or default_project,
                                              name="NBEAST project")

        self.controller = RunController()
        self.controller.started.connect(self._on_started)
        self.controller.batch.connect(self._on_batch)
        self.controller.finished.connect(self._on_finished)
        self.controller.failed.connect(self._on_failed)

        self._build_menu()
        self._build_toolbar()
        self._build_docks()
        self._build_central()
        self._restore_from_project()
        self.statusBar().showMessage("Ready")
        self._refresh_tree()
        self._refresh_history()
        self._update_title()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        new_project_action = QAction("New project…", self)
        new_project_action.triggered.connect(self._new_project)
        file_menu.addAction(new_project_action)
        open_project_action = QAction("Open project…", self)
        open_project_action.triggered.connect(self._open_project)
        file_menu.addAction(open_project_action)
        file_menu.addSeparator()

        export_action = QAction("Export report…", self)
        export_action.triggered.connect(self._on_export)
        file_menu.addAction(export_action)

        raw_action = QAction("Export raw data…", self)
        raw_action.setToolTip("Export mesh-tally arrays with uncertainties (NumPy / CSV / HDF5).")
        raw_action.triggered.connect(self._on_export_raw)
        file_menu.addAction(raw_action)

        data_action = QAction("Cross-section data…", self)
        data_action.triggered.connect(lambda: self._open_data_manager())
        file_menu.addAction(data_action)

        # CAD geometry (DAGMC) is picked from the Template dropdown ("Custom CAD");
        # when the native envs aren't present, offer setup here.
        if not cad.is_available():
            setup_action = QAction("Set up CAD geometry support…", self)
            setup_action.triggered.connect(self._open_cad_setup)
            file_menu.addAction(setup_action)

        examples_menu = self.menuBar().addMenu("&Examples")
        for label, key in (
            ("Godiva — bare HEU sphere (k ≈ 1.0)", "godiva"),
            ("PWR pin cell (k∞ ≈ 1.41)", "pincell"),
            ("7×7 PWR fuel assembly", "assembly"),
            ("Water shield slab (fixed source)", "shield"),
        ):
            action = QAction(label, self)
            action.triggered.connect(lambda _checked=False, k=key: self.load_example(k))
            examples_menu.addAction(action)

        # Analysis tools live in the "Analysis" tab (beside Results / Run history),
        # built in _build_docks — not a menu.

    # Curated starting points: (template, param overrides, quality, status hint).
    _EXAMPLES = {
        "godiva": ("Godiva", {}, "High", "Godiva benchmark — expect k ≈ 1.0 (critical)."),
        "pincell": ("Pin cell", {}, "Standard", "PWR pin cell — expect k∞ ≈ 1.41."),
        "assembly": ("Fuel assembly", {"n_side": 7}, "Standard",
                     "7×7 PWR fuel assembly — expect k∞ ≈ 1.41."),
        "shield": ("Shield slab", {}, "Standard",
                   "Water shield — watch flux & dose attenuate through the slab."),
    }

    def load_example(self, key: str) -> None:
        template, overrides, quality, hint = self._EXAMPLES[key]
        self.set_template(template)
        values = self.spec.defaults()
        values.update(overrides)
        self._param_values[template] = values
        self._material_values[template] = self.spec.material_defaults()
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
        self.template_combo.addItems([*specs.SPECS.keys(), CAD_TEMPLATE])
        self.template_combo.setToolTip("Choose the model to simulate (or import custom CAD).")
        self.template_combo.currentTextChanged.connect(self.set_template)
        tb.addWidget(self.template_combo)

        tb.addSeparator()
        self.run_action = QAction("Run", self)
        self.run_action.setToolTip("Run the simulation.")
        self.run_action.triggered.connect(self.start_run)
        tb.addAction(self.run_action)
        self.stop_action = QAction("Stop", self)
        self.stop_action.setEnabled(False)
        self.stop_action.setToolTip("Stop the running simulation (keeps results so far).")
        self.stop_action.triggered.connect(self.stop_run)
        tb.addAction(self.stop_action)

        tb.addSeparator()
        tb.addWidget(QLabel(" Units: "))
        self.units_combo = QComboBox()
        self.units_combo.addItems(["Metric (SI)", "US (Imperial)"])
        self.units_combo.setToolTip(
            "Display unit system. Geometry shows cm ↔ in; result maps are relative "
            "(per source neutron) until you set a reactor power in Settings, then they "
            "read absolute units (n/cm²·s ↔ n/in²·s, Sv/h ↔ rem/h)."
        )
        self.units_combo.currentIndexChanged.connect(self._on_units_changed)
        tb.addWidget(self.units_combo)

        # Run-settings widgets are the canonical state but live in the Model tree's
        # Settings group (edited in Properties), not on the toolbar. Parented to the
        # window, never shown directly.
        self.quality_combo = QComboBox(self)
        self.quality_combo.addItems(["Quick", "Standard", "High"])
        self.quality_combo.setCurrentText("Standard")
        self.quality_combo.currentTextChanged.connect(self._apply_quality)
        self.batches_spin = QSpinBox(self)
        self.batches_spin.setRange(10, 100_000)
        self.batches_spin.setValue(100)
        self.batches_spin.valueChanged.connect(lambda _: self._refresh_tree())
        self.particles_spin = QSpinBox(self)
        self.particles_spin.setRange(100, 10_000_000)
        self.particles_spin.setSingleStep(1000)
        self.particles_spin.setValue(2000)
        self.particles_spin.valueChanged.connect(lambda _: self._refresh_tree())
        self.seed_spin = QSpinBox(self)
        self.seed_spin.setRange(1, 2_147_483_647)
        self.seed_spin.setValue(1)
        self.seed_spin.valueChanged.connect(lambda _: self._refresh_tree())
        # These are state only (edited via the Settings group), never shown directly —
        # hide them so they don't render at the window origin.
        for w in (self.quality_combo, self.batches_spin, self.particles_spin, self.seed_spin):
            w.hide()
        self._advanced = True  # everything editable now; kept for compatibility
        self._apply_quality("Standard")

    def _apply_quality(self, name: str) -> None:
        presets = {"Quick": (50, 1000), "Standard": (100, 2000), "High": (200, 5000)}
        batches, particles = presets.get(name, (100, 2000))
        self.batches_spin.setValue(batches)
        self.particles_spin.setValue(particles)

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
            ("Absorption rate", "absorption"),
            ("Neutron production (ν-fission)", "nu-fission"),
            ("Heating (energy deposition)", "heating"),
            ("Neutron dose rate", "dose"),
            ("Flux relative error", "flux_rel_err"),
            ("Scalar flux (3D volume)", "volume"),
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

        # Run history: persisted runs, reloadable + comparable.
        self.history_panel = HistoryPanel()
        self.history_panel.loadRequested.connect(self._load_history_run)
        self.history_panel.compareRequested.connect(self._compare_history_runs)
        self.history_panel.deleteRequested.connect(self._delete_history_runs)
        history_dock = QDockWidget("Run history", self)
        history_dock.setWidget(self.history_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, history_dock)

        # Analysis tools: a tab beside Results + Run history (was the Analysis menu).
        from .analysis_panel import AnalysisPanel

        self.analysis_panel = AnalysisPanel({
            "sweep": self._open_sweep,
            "moderation": self._open_moderation,
            "poisoning": self._open_poisoning,
            "mgxs": self._open_mgxs,
            "depletion": self._open_depletion,
        })
        analysis_dock = QDockWidget("Analysis", self)
        analysis_dock.setWidget(self.analysis_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, analysis_dock)

        self.tabifyDockWidget(results_dock, history_dock)
        self.tabifyDockWidget(history_dock, analysis_dock)
        results_dock.raise_()
        self._update_analysis_availability()

    def _build_central(self) -> None:
        self.tabs = QTabWidget()
        self.monitor = ConvergenceMonitor()
        self.flux_view = FluxViewport()
        self.flux_view.view3d_check.toggled.connect(self._on_view3d_toggled)
        self.spectrum_view = SpectrumView()
        self.tabs.addTab(self.monitor, "Convergence")
        self.tabs.addTab(self.flux_view, "Flux map")
        self.tabs.addTab(self.spectrum_view, "Spectrum")
        self.setCentralWidget(self.tabs)

    # ---- model tree -------------------------------------------------------
    @property
    def spec(self):
        return specs.SPECS.get(self._template)

    @property
    def _is_cad(self) -> bool:
        return self._template == CAD_TEMPLATE

    def set_template(self, name: str) -> None:
        if name == CAD_TEMPLATE:
            self._select_cad_template()
            return
        if name not in specs.SPECS:
            return
        self._template = name
        if self.template_combo.currentText() != name:
            self.template_combo.setCurrentText(name)
        self.properties.setRowCount(0)
        self._refresh_tree()

    def _select_cad_template(self) -> None:
        from nbeast.core import cad

        if not cad.is_available():
            self.statusBar().showMessage("CAD support isn't installed — opening setup.")
            self.template_combo.setCurrentText(self._template)  # revert
            self._open_cad_setup()
            return
        self._template = CAD_TEMPLATE
        if self.template_combo.currentText() != CAD_TEMPLATE:
            self.template_combo.setCurrentText(CAD_TEMPLATE)
        self.properties.setRowCount(0)
        self._refresh_tree()
        self.statusBar().showMessage(
            "Custom CAD — click Geometry (or Run) to import a STEP file and assign materials."
        )

    def set_param(self, key: str, value: float) -> None:
        """Programmatic + UI entry point for editing a parameter."""
        self._param_values[self._template][key] = value
        self._refresh_tree()  # reflect new value in the tree (not Properties — keep editor focus)

    # ---- display units ----------------------------------------------------
    def _absolute_units(self) -> bool:
        """Field maps are absolute only when a power (eigenvalue) or source strength
        (fixed source) is set."""
        return (self._source_strength > 0) if self._is_fixed_source else (self._power_w > 0)

    def _source_rate(self, results) -> float | None:
        """Absolute source rate [n/s]: a fixed source gives it directly; an eigenvalue
        run derives it from the reactor power via the whole-geometry fission energy."""
        if self._is_fixed_source:
            return self._source_strength if self._source_strength > 0 else None
        if self._power_w > 0:
            return results.source_rate(self._power_w)
        return None

    def _on_units_changed(self, index: int) -> None:
        self._unit_system = "US" if index == 1 else "SI"
        self._refresh_tree()
        item = self.model_tree.currentItem()
        if item is not None:           # re-render an open Properties editor in the new unit
            self._on_tree_click(item, 0)
        # re-render the field on screen so its colorbar unit updates
        if self.tabs.currentWidget() is self.flux_view and self._statepoint \
                and self.results_list.isEnabled():
            current = self.results_list.currentItem()
            if current is not None:
                self._on_results_clicked(current)

    def _field_bar_title(self, score: str) -> str:
        from nbeast.core import units

        return units.colorbar_title(score, self._unit_system, self._absolute_units())

    def _on_power_changed(self, value: float) -> None:
        if self._is_fixed_source:
            self._source_strength = float(value)
        else:
            self._power_w = float(value)
        self._refresh_tree()
        if self.tabs.currentWidget() is self.flux_view and self._statepoint \
                and self.results_list.isEnabled():
            current = self.results_list.currentItem()
            if current is not None:
                self._on_results_clicked(current)
        self._surface_diagnostics()   # refresh fission-power readout

    def _display_scale(self, results, score: str, tally_name: str) -> float:
        """Combined power/source normalization × unit-system factor for a field."""
        from nbeast.core import units

        scale = units.field_factor(score, self._unit_system, self._absolute_units())
        if self._absolute_units():
            scale *= results.absolute_factor(score, self._source_rate(results), name=tally_name)
        return scale

    def _value_text(self, param: specs.Parameter) -> str:
        from nbeast.core import units

        value = self._param_values[self._template][param.key]
        if units.is_length(param.unit):
            disp = units.cm_to_display(value, self._unit_system)
            u = units.length_unit(self._unit_system)
            dec = param.decimals + (1 if self._unit_system == units.US else 0)
            return f"{param.label} = {disp:.{dec}f} {u}"
        unit = f" {param.unit}" if param.unit else ""
        if param.kind == "int":
            return f"{param.label} = {int(value)}{unit}"
        return f"{param.label} = {value:.{param.decimals}f}{unit}"

    def _param_row_label(self, param: specs.Parameter) -> str:
        """Property-row label with the unit in the current system (cm ↔ in)."""
        from nbeast.core import units

        unit = units.length_unit(self._unit_system) if units.is_length(param.unit) else param.unit
        return f"{param.label} ({unit})" if unit else param.label

    def _settings_tree_item(self) -> QTreeWidgetItem:
        settings = QTreeWidgetItem(["Settings"])
        settings.addChild(QTreeWidgetItem([f"quality = {self.quality_combo.currentText()}"]))
        settings.addChild(QTreeWidgetItem([f"batches = {self.batches_spin.value()}"]))
        settings.addChild(QTreeWidgetItem([f"particles/batch = {self.particles_spin.value()}"]))
        # Fixed-source runs have no inactive (source-convergence) batches.
        inactive = 0 if self._is_fixed_source else _inactive_for(self.batches_spin.value())
        settings.addChild(QTreeWidgetItem([f"inactive = {inactive}"]))
        settings.addChild(QTreeWidgetItem([f"seed = {self.seed_spin.value()}"]))
        if self._is_fixed_source:
            val = f"{self._source_strength:g} n/s" if self._source_strength > 0 else "relative (per source n)"
            settings.addChild(QTreeWidgetItem([f"source strength = {val}"]))
        else:
            val = f"{self._power_w:g} W" if self._power_w > 0 else "relative (per source n)"
            settings.addChild(QTreeWidgetItem([f"reactor power = {val}"]))
        return settings

    def _refresh_tree(self) -> None:
        self._update_analysis_availability()
        self.model_tree.clear()
        if self._is_cad:
            self._refresh_cad_tree()
            return
        spec = self.spec

        materials_item = QTreeWidgetItem(["Materials"])
        for role in spec.material_roles:
            mat_key = self._material_values[self._template][role.key]
            mat_label = materials.LIBRARY[mat_key].label
            materials_item.addChild(QTreeWidgetItem([f"{role.label}: {mat_label}"]))
        for p in spec.params_in("Materials"):
            materials_item.addChild(QTreeWidgetItem([self._value_text(p)]))

        geometry = QTreeWidgetItem(["Geometry"])
        geometry.addChild(QTreeWidgetItem([spec.geometry]))
        for p in spec.params_in("Geometry"):
            geometry.addChild(QTreeWidgetItem([self._value_text(p)]))

        for item in (materials_item, geometry, self._settings_tree_item()):
            self.model_tree.addTopLevelItem(item)
            item.setExpanded(True)

    def _refresh_cad_tree(self) -> None:
        from nbeast.core import cad

        step = self._cad.get("step")
        geometry = QTreeWidgetItem(["Geometry"])
        geometry.addChild(QTreeWidgetItem(
            [f"CAD file: {os.path.basename(step)}" if step else "CAD file: (click to import…)"]))

        materials_item = QTreeWidgetItem(["Materials"])
        mats = self._cad.get("materials") or []
        if mats:
            for i, tag in enumerate(mats):
                label = cad.MATERIAL_PRESETS.get(tag, {}).get("label", tag)
                materials_item.addChild(QTreeWidgetItem([f"Solid {i}: {label}"]))
        else:
            materials_item.addChild(QTreeWidgetItem(["(import a CAD file to assign materials)"]))

        for item in (materials_item, geometry, self._settings_tree_item()):
            self.model_tree.addTopLevelItem(item)
            item.setExpanded(True)

    # ---- properties (editing) --------------------------------------------
    def _group_of(self, item: QTreeWidgetItem) -> str:
        return item.text(0) if item.parent() is None else item.parent().text(0)

    def _on_tree_click(self, item: QTreeWidgetItem, _column: int) -> None:
        group = self._group_of(item)
        if group == "Settings":
            self._render_settings_editors()
            return
        if self._is_cad:
            if group in ("Geometry", "Materials"):
                self._open_cad_import()   # configure the CAD file + materials in the dialog
            else:
                self._render_readonly(group)
            return
        if group == "Materials":
            self._render_materials_editors()
        elif group == "Geometry":
            params = self.spec.params_in("Geometry")
            self._render_param_editors("Geometry", params) if params \
                else self._render_readonly("Geometry")
        else:
            self._render_readonly(group)

    def _render_settings_editors(self) -> None:
        """Run settings (quality preset, batches, particles, seed) — editable here now
        that they've moved off the toolbar. Editors write to the canonical spin boxes."""
        self.properties.setRowCount(4)
        self.properties.setItem(0, 0, QTableWidgetItem("Quality preset"))
        qcombo = QComboBox()
        qcombo.addItems(["Quick", "Standard", "High"])
        qcombo.setCurrentText(self.quality_combo.currentText())
        qcombo.currentTextChanged.connect(self._on_quality_selected)
        self.properties.setCellWidget(0, 1, qcombo)

        def spin(row, label, canonical, minimum, maximum, step=1):
            self.properties.setItem(row, 0, QTableWidgetItem(label))
            editor = QSpinBox()
            editor.setRange(minimum, maximum)
            editor.setSingleStep(step)
            editor.setValue(canonical.value())
            editor.valueChanged.connect(canonical.setValue)
            self.properties.setCellWidget(row, 1, editor)
            return editor

        self._batches_editor = spin(1, "Batches", self.batches_spin, 10, 100_000)
        self._particles_editor = spin(2, "Particles/batch", self.particles_spin,
                                      100, 10_000_000, step=1000)
        spin(3, "Seed", self.seed_spin, 1, 2_147_483_647)

        # Normalization: 0 keeps result maps relative (per source neutron); a positive
        # value gives absolute units. Eigenvalue runs take a reactor power; fixed-source
        # runs take a source strength (n/s), which fixes the scale directly.
        self.properties.setRowCount(5)
        fixed = self._is_fixed_source
        label = "Source strength (n/s)" if fixed else "Reactor power (W)"
        self.properties.setItem(4, 0, QTableWidgetItem(label))
        norm = QDoubleSpinBox()
        norm.setRange(0.0, 1e24)
        norm.setDecimals(1)
        norm.setSingleStep(1000.0)
        norm.setValue(self._source_strength if fixed else self._power_w)
        norm.setSpecialValueText("relative (per source n)")
        norm.setToolTip(
            "Neutron source rate (n/s) — sets absolute units and reports induced fission "
            "power. 0 = relative maps." if fixed else
            "Fission power used to normalize result maps to absolute units "
            "(n/cm²·s, W/cm³, Sv/h). 0 = relative maps (per source neutron)."
        )
        norm.valueChanged.connect(self._on_power_changed)
        self.properties.setCellWidget(4, 1, norm)

    def _on_quality_selected(self, name: str) -> None:
        self.quality_combo.setCurrentText(name)   # _apply_quality updates batches/particles
        if hasattr(self, "_batches_editor"):
            self._batches_editor.setValue(self.batches_spin.value())
            self._particles_editor.setValue(self.particles_spin.value())

    def _make_param_editor(self, p: specs.Parameter):
        from nbeast.core import units

        value = self._param_values[self._template][p.key]
        if p.kind == "int":
            editor = QSpinBox()
            editor.setRange(int(p.minimum), int(p.maximum))
            editor.setSingleStep(int(p.step))
            editor.setValue(int(value))
            editor.valueChanged.connect(lambda v, key=p.key: self.set_param(key, v))
            return editor
        # Length params are stored in cm but shown/edited in the display unit; the
        # editor converts back to cm before writing.
        f = units.CM_PER_INCH if (units.is_length(p.unit) and self._unit_system == units.US) else 1.0
        editor = QDoubleSpinBox()
        editor.setRange(p.minimum / f, p.maximum / f)
        editor.setSingleStep(p.step / f)
        editor.setDecimals(p.decimals + (1 if f != 1.0 else 0))
        editor.setValue(value / f)
        editor.valueChanged.connect(lambda v, key=p.key, fac=f: self.set_param(key, v * fac))
        return editor

    def _render_param_editors(self, group: str, params: list[specs.Parameter]) -> None:
        self.properties.setRowCount(len(params))
        for row, p in enumerate(params):
            self.properties.setItem(row, 0, QTableWidgetItem(self._param_row_label(p)))
            self.properties.setCellWidget(row, 1, self._make_param_editor(p))

    def _render_materials_editors(self) -> None:
        """Materials panel: a searchable material dropdown per role, then the numeric
        material parameters (enrichment, temperature)."""
        roles = self.spec.material_roles
        params = self.spec.params_in("Materials")
        available = materials.available_names(self._cross_sections)
        self.properties.setRowCount(len(roles) + len(params))
        row = 0
        for role in roles:
            self.properties.setItem(row, 0, QTableWidgetItem(role.label))
            self.properties.setCellWidget(row, 1, self._make_material_combo(role, available))
            row += 1
        for p in params:
            self.properties.setItem(row, 0, QTableWidgetItem(self._param_row_label(p)))
            self.properties.setCellWidget(row, 1, self._make_param_editor(p))
            row += 1

    def _make_material_combo(self, role, available: set):
        """A type-to-filter material dropdown for one role; materials whose data isn't
        in the active library are listed but greyed and marked 'needs data'."""
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setToolTip(
            "Type to filter. 'needs data' materials require extra cross sections — "
            "selecting one offers the downloader (File ▸ Cross-section data…)."
        )
        current = self._material_values[self._template][role.key]
        chosen = 0
        for i, mspec in enumerate(materials.by_category(role.category)):
            ok = mspec.is_available(available)
            combo.addItem(mspec.label if ok else f"{mspec.label} — needs data", mspec.key)
            if not ok:
                combo.setItemData(i, QColor("#999"), Qt.ForegroundRole)
            if mspec.key == current:
                chosen = i
        combo.setCurrentIndex(chosen)
        completer = combo.completer()
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        combo.activated.connect(
            lambda idx, c=combo, rk=role.key: self._on_material_selected(rk, c.itemData(idx))
        )
        return combo

    def _on_material_selected(self, role_key: str, mat_key) -> None:
        if not mat_key:
            return
        self._material_values[self._template][role_key] = mat_key
        self._refresh_tree()
        mspec = materials.LIBRARY.get(mat_key)
        if mspec and not mspec.is_available(materials.available_names(self._cross_sections)):
            self._offer_data_download(mspec)

    def _offer_data_download(self, mspec) -> None:
        available = materials.available_names(self._cross_sections)
        elements, sab = mspec.missing_data(available)
        need = ", ".join([*elements, *sab]) or "additional data"
        resp = QMessageBox.question(
            self, "Material needs data",
            f"{mspec.label} needs cross-section data not in the active library:\n  {need}\n\n"
            "Download just this material's data now?",
        )
        if resp == QMessageBox.Yes:
            self._open_data_manager(prefill=(elements, sab))

    def _render_readonly(self, group: str) -> None:
        if group == "Settings":
            rows = [
                ("batches", self.batches_spin.value()),
                ("particles/batch", self.particles_spin.value()),
                ("inactive", _inactive_for(self.batches_spin.value())),
                ("seed", self.seed_spin.value()),
                ("(edit batches/particles/seed in the toolbar)", ""),
            ]
        else:
            rows = [("info", "fixed — not editable in v1")]
        self.properties.setRowCount(len(rows))
        for row, (key, value) in enumerate(rows):
            self.properties.setItem(row, 0, QTableWidgetItem(str(key)))
            self.properties.setItem(row, 1, QTableWidgetItem(str(value)))

    # ---- run lifecycle ----------------------------------------------------
    def _build_base_model(self, batches: int, particles: int, inactive: int,
                          seed: int | None = None):
        return self.spec.build(
            batches=batches,
            particles=particles,
            inactive=inactive,
            seed=seed,
            **self._material_values[self._template],
            **self._param_values[self._template],
        )

    @property
    def _is_fixed_source(self) -> bool:
        return self.spec is not None and self.spec.run_mode == "fixed source"

    def _build_model(self):
        batches = self.batches_spin.value()
        inactive = 0 if self._is_fixed_source else _inactive_for(batches)
        model = self._build_base_model(
            batches, self.particles_spin.value(), inactive,
            seed=self.seed_spin.value(),
        )
        tallies.add_flux_spectrum(model, n_groups=100)
        tallies.add_power_norm(model)              # whole-geometry basis for absolute units
        tallies.add_flux_slice_mesh(model, n=40)   # flux + reaction-rate + heating maps
        tallies.add_flux_volume_mesh(model, n=30)
        tallies.add_dose_mesh(model, n=40)         # flux-to-dose-rate (shielding)
        if not self._is_fixed_source:
            tallies.add_entropy_mesh(model)  # fission-source convergence (eigenvalue only)
        return model

    def _unavailable_materials(self) -> list:
        """Selected materials whose data isn't in the active library (role, spec)."""
        if self.spec is None:
            return []
        avail = materials.available_names(self._cross_sections)
        out = []
        for role in self.spec.material_roles:
            mspec = materials.LIBRARY[self._material_values[self._template][role.key]]
            if not mspec.is_available(avail):
                out.append((role, mspec))
        return out

    def start_run(self) -> None:
        if self.controller.running:
            return
        if self._is_cad:
            self._open_cad_import()   # CAD configures + runs inside its own dialog
            return
        missing = self._unavailable_materials()
        if missing:
            names = ", ".join(m.label for _, m in missing)
            self.statusBar().showMessage(
                f"Can't run — {names} need cross-section data. "
                "Download it via File ▸ Cross-section data…"
            )
            return
        model = self._build_model()
        self._persist_state()  # remember the current model so reopening restores it
        self.monitor.reset()
        self.monitor.mark_inactive(0 if self._is_fixed_source else _inactive_for(self.batches_spin.value()))
        self.spectrum_view.clear()
        self.results_list.setEnabled(False)
        self.run_action.setEnabled(False)
        self.stop_action.setEnabled(True)
        self.statusBar().showMessage("Running…")
        self._current_run_dir = self._run_root / "current"
        self.controller.start(model, self._current_run_dir)

    def stop_run(self) -> None:
        self.controller.cancel()
        self.statusBar().showMessage("Stopping…")

    def _on_started(self, n_batches: int) -> None:
        self._total_batches = n_batches
        self.statusBar().showMessage(f"Running… 0/{n_batches} batches")

    def _on_batch(self, update) -> None:
        self.monitor.add_point(
            update.batch, update.keff, update.keff_std, getattr(update, "entropy", None)
        )
        if update.keff is None:  # fixed-source run — no k-effective to report
            self.statusBar().showMessage(
                f"Running… batch {update.batch}/{self._total_batches}"
            )
        else:
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
            self.statusBar().showMessage(f"Done — fixed-source run ({len(result.batches)} batches)")
        if not result.cancelled and result.statepoint:
            self._load_results(result.statepoint)
            self._archive_run(result)

    def _load_results(self, statepoint: str, cad_overlay=None) -> None:
        """Populate spectrum + flux/fission views from a finished run (defensive).

        ``cad_overlay`` = (stls, colors, labels): when given, the results are from a CAD
        run and every field is rendered volumetrically on the semi-transparent geometry
        rather than as a flat 2D slice."""
        from nbeast.core.results import Results

        self._cad_result = cad_overlay is not None
        self._cad_overlay = cad_overlay
        self._statepoint = statepoint
        self.last_diagnostics = None
        try:
            with Results(statepoint) as results:
                spectrum = results.flux_spectrum()
                self.spectrum_view.set_spectrum(
                    spectrum.energy_edges, spectrum.flux, spectrum.flux_std
                )
                self.last_diagnostics = results.diagnostics()
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(
                f"{self.statusBar().currentMessage()}  (spectrum unavailable: {exc})"
            )
        self._surface_diagnostics()
        # Fixed-source runs have no k-effective / fission-source convergence — say so
        # rather than leaving an empty criticality plot with a misleading caption.
        if self.last_diagnostics is not None and self.last_diagnostics.keff is None:
            self.monitor.set_note(
                "Fixed-source run — k-effective and fission-source convergence do not "
                "apply (there is no chain reaction to converge)."
            )
        else:
            self.monitor.clear_note()
        self.results_list.setEnabled(True)
        self.results_list.setCurrentRow(0)
        self._show_field("flux", switch_tab=False)

    def _surface_diagnostics(self) -> None:
        """Fold the trust check into the status bar — concise, non-blocking."""
        diag = self.last_diagnostics
        if diag is None:
            return
        if diag.keff is None:  # fixed-source run
            base = f"Done — fixed-source run ({diag.n_active} batches)"
            ok_text = "✓ flux statistics OK"
        else:
            base = f"Done — k = {diag.keff:.5f} ± {diag.keff_std:.5f} ({diag.keff_pcm:.0f} pcm)"
            ok_text = "✓ converged"
        tail = f"⚠ {diag.warnings[0]}" if diag.warnings else ok_text
        self.statusBar().showMessage(f"{base}  {tail}{self._fission_power_note()}")

    def _fission_power_note(self) -> str:
        """For a fixed source with a strength set, report the induced fission power
        (an output, not an input) — 0 for a non-fissile shield."""
        if not (self._is_fixed_source and self._source_strength > 0 and self._statepoint):
            return ""
        try:
            from nbeast.core.results import Results

            with Results(self._statepoint) as results:
                power = results.fission_power(self._source_strength)
        except Exception:  # noqa: BLE001
            return ""
        if power:
            return f"  ·  induced fission power ≈ {power:.3g} W"
        return "  ·  non-multiplying (shield attenuates the source)"

    @staticmethod
    def _field_source(score: str) -> tuple[str, str, str]:
        """Map a Results-panel score to (tally name, tally score, VTK array label).

        Most maps live on the ``flux_mesh`` tally; the dose rate lives on its own
        ``dose_mesh`` tally (it reads ``flux`` weighted by the dose function).
        """
        base = score[:-8] if score.endswith("_rel_err") else score
        if base == "dose":
            return "dose_mesh", "flux", "dose"
        return "flux_mesh", base, base

    def _show_field(self, score: str, switch_tab: bool = True) -> None:
        """Render the chosen mesh field in the Flux-map tab.

        A ``*_rel_err`` score shows the relative-error map: the VTK written for the
        base score also carries its ``<label>_rel_err`` array, so we reuse it.
        """
        if not self._statepoint:
            return
        if self._cad_result:   # CAD is 3-D — render volumetrically on the geometry
            self.flux_view.view3d_check.setVisible(False)
            self._show_cad_field(score, switch_tab)
            return
        self._current_field_score = score
        # The "View in 3D" toggle is offered only where the slice extrudes exactly (a
        # z-uniform geometry). When on, render the extruded 3D block instead of the slice.
        supports_3d = self.spec is not None and self.spec.z_invariant
        self.flux_view.view3d_check.setVisible(supports_3d)
        if supports_3d and self.flux_view.view3d_check.isChecked():
            self._show_extruded_field(score, switch_tab)
            return
        from nbeast.core.results import Results

        tally_name, tally_score, label = self._field_source(score)
        try:
            vtk = Path(self._statepoint).parent / f"{label}.vtk"
            with Results(self._statepoint) as results:
                scale = self._display_scale(results, score, tally_name)
                results.field_to_vtk(vtk, score=tally_score, name=tally_name, label=label,
                                     scale=scale)
            self.flux_view.show_field(vtk, score, FIELD_TITLES.get(score, score),
                                      bar_title=self._field_bar_title(score))
            if switch_tab:
                self.tabs.setCurrentWidget(self.flux_view)
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"Field '{score}' unavailable: {exc}")

    def _on_results_clicked(self, item) -> None:
        score = item.data(Qt.UserRole)
        if score == "tracks":
            self.show_tracks()
        elif score == "volume":
            self._show_volume()
        else:
            self._show_field(score, switch_tab=True)

    def _on_view3d_toggled(self, _checked: bool) -> None:
        """Re-render the current field in the chosen 2D/3D mode."""
        if self._statepoint and not self._cad_result and self.results_list.isEnabled():
            self._show_field(self._current_field_score, switch_tab=False)

    def _show_extruded_field(self, score: str, switch_tab: bool = True) -> None:
        """Render a z-invariant template field as a 3-D block by extruding its 2D slice
        across z (exact for infinite/reflective-z geometries)."""
        if not self._statepoint:
            return
        import numpy as np

        from nbeast.core.results import Results

        tally_name, tally_score, _label = self._field_source(score)
        try:
            with Results(self._statepoint) as results:
                values, dims, lower, upper, rel = results.field_extruded_volume(
                    tally_score, tally_name)
                scale = self._display_scale(results, score, tally_name)
            if score.endswith("_rel_err"):
                arr, log = rel, False
            else:
                arr, log = np.asarray(values, dtype=float) * scale, True
            self.flux_view.show_field_volume(
                arr, dims, lower, upper, log=log,
                bar_title=self._field_bar_title(score), title=FIELD_TITLES.get(score, score),
            )
            if switch_tab:
                self.tabs.setCurrentWidget(self.flux_view)
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"Field '{score}' unavailable: {exc}")

    def _show_cad_field(self, score: str, switch_tab: bool = True) -> None:
        """Render a CAD result field as a 3-D volume on the semi-transparent geometry."""
        if not self._statepoint:
            return
        import numpy as np

        from nbeast.core.results import Results

        base = score[:-8] if score.endswith("_rel_err") else score
        if base == "dose":
            name, tally_score = "dose_volume", "flux"
        else:
            name, tally_score = "flux_volume", ("flux" if base == "volume" else base)
        try:
            with Results(self._statepoint) as results:
                mean, dims, lower, upper, rel = results.field_volume(tally_score, name)
                scale = self._display_scale(results, score, name)
            if score.endswith("_rel_err"):
                values, log = rel, False
            else:
                values, log = np.asarray(mean, dtype=float) * scale, True
            stls, colors, labels = self._cad_overlay or (None, None, None)
            self.flux_view.show_field_volume(
                values, dims, lower, upper, log=log, stls=stls, colors=colors, labels=labels,
                bar_title=self._field_bar_title(score), title=FIELD_TITLES.get(score, score),
            )
            if switch_tab:
                self.tabs.setCurrentWidget(self.flux_view)
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"Field '{score}' unavailable: {exc}")

    def _show_volume(self) -> None:
        """Publication-style 3D volume render of the flux field."""
        if not self._statepoint:
            return
        if self._cad_result:
            self._show_cad_field("flux")
            return
        from nbeast.core.results import Results

        try:
            with Results(self._statepoint) as results:
                values, dims, lower, upper = results.flux_volume()
                scale = self._display_scale(results, "flux", "flux_volume")
            if scale != 1.0:
                import numpy as np
                values = np.asarray(values, dtype=float) * scale
            self.flux_view.show_field_volume(values, dims, lower, upper, title="Scalar flux",
                                             bar_title=self._field_bar_title("flux"))
            self.tabs.setCurrentWidget(self.flux_view)
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"Volume render unavailable: {exc}")

    def show_tracks(self) -> None:
        """Generate a few neutron tracks and render them in the Flux-map tab."""
        if self.spec is None:
            self.statusBar().showMessage("Neutron tracks aren't available for the CAD template.")
            return
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

    # ---- project + run history -------------------------------------------
    def _current_settings(self) -> dict:
        return {
            "batches": self.batches_spin.value(),
            "particles": self.particles_spin.value(),
            "seed": self.seed_spin.value(),
        }

    def _persist_state(self) -> None:
        """Record the current editor state into the active project (best-effort)."""
        try:
            self.project.update_state(
                template=self._template,
                param_values=self._param_values,
                material_values=self._material_values,
                settings=self._current_settings(),
            )
        except Exception:  # noqa: BLE001 — persistence must never break a run
            pass

    def _restore_from_project(self) -> None:
        """Reload the last-used template, parameters, and run settings from the project."""
        if not self.project.template or self.project.template not in specs.SPECS:
            return
        for label, values in self.project.param_values.items():
            if label in self._param_values:
                self._param_values[label].update(values)
        for label, mats in (self.project.material_values or {}).items():
            if label in self._material_values:
                self._material_values[label].update(mats)
        s = self.project.settings or {}
        if "batches" in s:
            self.batches_spin.setValue(int(s["batches"]))
        if "particles" in s:
            self.particles_spin.setValue(int(s["particles"]))
        if "seed" in s:
            self.seed_spin.setValue(int(s["seed"]))
        self.set_template(self.project.template)
        self._update_title()

    def _update_title(self) -> None:
        self.setWindowTitle(f"NBEAST — {self.project.name}")

    def _refresh_history(self) -> None:
        self.history_panel.set_runs(self.project.runs)

    def _archive_run(self, result) -> None:
        """Save a finished run into the project so it persists and can be revisited."""
        try:
            run_dir = Path(result.statepoint).parent
            warnings = self.last_diagnostics.warnings if self.last_diagnostics else []
            self.project.add_run(
                statepoint_src=result.statepoint,
                model_xml_src=run_dir / "model.xml",
                template=self._template,
                parameters=dict(self._param_values[self._template]),
                batches=self.batches_spin.value(),
                inactive=_inactive_for(self.batches_spin.value()),
                particles=self.particles_spin.value(),
                seed=self.seed_spin.value(),
                keff=result.keff,
                keff_std=result.keff_std,
                warnings=list(warnings),
            )
            self._refresh_history()
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"Run finished (could not archive: {exc})")

    def _load_history_run(self, run_id: str) -> None:
        """Bring a saved run's results back into the viewports."""
        from nbeast.core.runner import RunResult

        record = self.project.get_run(run_id)
        if record is None:
            return
        sp = self.project.statepoint_path(record)
        if sp is None or not sp.exists():
            self.statusBar().showMessage(f"Statepoint for {run_id} is missing.")
            return
        self.last_result = RunResult(
            keff=record.keff, keff_std=record.keff_std, statepoint=str(sp)
        )
        self._load_results(str(sp))
        self._replay_convergence(str(sp), record.inactive or 0)
        self.statusBar().showMessage(f"Loaded {record.title()} ({run_id})")

    def _replay_convergence(self, statepoint: str, n_inactive: int) -> None:
        """Redraw the convergence monitor for a loaded run from its statepoint."""
        from nbeast.core.results import Results

        try:
            with Results(statepoint) as results:
                kg = results.k_generation()
                ent = results.entropy()
            if kg is None:
                return
            self.monitor.reset()
            self.monitor.mark_inactive(n_inactive)
            for i, k in enumerate(kg):
                e = float(ent[i]) if (ent is not None and i < ent.size) else None
                self.monitor.add_point(i + 1, float(k), None, e)
        except Exception:  # noqa: BLE001 — the curve is a nicety, never fatal
            pass

    def _delete_history_runs(self, ids: list) -> None:
        if not ids:
            return
        n = len(ids)
        confirm = QMessageBox.question(
            self, "Delete runs",
            f"Delete {n} saved run{'s' if n != 1 else ''} from this project? "
            "This removes the archived statepoint(s) and cannot be undone.",
        )
        if confirm != QMessageBox.Yes:
            return
        for run_id in ids:
            self.project.delete_run(run_id)
        self._refresh_history()
        self.statusBar().showMessage(f"Deleted {n} run{'s' if n != 1 else ''}.")

    def _compare_history_runs(self, id_a: str, id_b: str) -> None:
        from .compare_dialog import CompareDialog

        a, b = self.project.get_run(id_a), self.project.get_run(id_b)
        if a is None or b is None:
            return
        dialog = CompareDialog(a, b, self.project, parent=self)
        dialog.exec()

    def _new_project(self) -> None:
        parent = QFileDialog.getExistingDirectory(self, "New project — choose a parent folder")
        if not parent:
            return
        name, ok = QInputDialog.getText(self, "New project", "Project name:", text="study")
        if not ok or not name.strip():
            return
        target = Path(parent) / name.strip()
        if (target / "project.json").exists():
            self.statusBar().showMessage(f"A project already exists at {target}.")
            return
        self._switch_project(Project.create(target, name=name.strip()))

    def _open_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Open project — choose the project folder")
        if not directory:
            return
        try:
            self._switch_project(Project.open(directory))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Open project", f"Not an NBEAST project:\n{exc}")

    def _switch_project(self, project: Project) -> None:
        self.project = project
        self._restore_from_project()
        self._refresh_tree()
        self._refresh_history()
        self._update_title()
        self.statusBar().showMessage(f"Project: {project.path}")

    def _on_export_raw(self) -> None:
        if not self._statepoint:
            self.statusBar().showMessage("Run or load a simulation before exporting raw data.")
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export raw mesh data", "flux_mesh.npz",
            "NumPy archive (*.npz);;CSV (*.csv);;HDF5 (*.h5)",
        )
        if not path:
            return
        from nbeast.core.results import Results

        try:
            with Results(self._statepoint) as results:
                out = results.export_mesh_data(path)
            self.statusBar().showMessage(f"Raw data exported to {out}")
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"Raw export failed: {exc}")

    def _update_analysis_availability(self) -> None:
        """Grey out analysis tools that don't apply to the current template."""
        if not hasattr(self, "analysis_panel"):
            return
        spec = self.spec
        eigen = spec is not None and not self._is_fixed_source
        moderated = eigen and any(r.key == "moderator" for r in spec.material_roles)
        eig_reason = "Needs an eigenvalue template (not Custom CAD or the fixed-source shield)."
        mod_reason = "Needs a moderated thermal lattice (pin cell or assembly)."
        for key in ("sweep", "mgxs", "depletion"):
            self.analysis_panel.set_enabled(key, eigen, eig_reason)
        for key in ("moderation", "poisoning"):
            self.analysis_panel.set_enabled(key, moderated, mod_reason)

    def _analysis_needs_template(self) -> bool:
        """The Analysis tools (sweep, multigroup, depletion) are eigenvalue-only —
        they all rely on k-effective / a fissile fuel, so they don't apply to the CAD
        import or the fixed-source shield."""
        if self.spec is None:
            self.statusBar().showMessage(
                "This analysis works on a parametric template — pick one (not Custom CAD)."
            )
            return False
        if self._is_fixed_source:
            self.statusBar().showMessage(
                "This analysis is for eigenvalue (criticality) models — it doesn't apply "
                "to the fixed-source shield (there's no k-effective)."
            )
            return False
        return True

    def _open_sweep(self) -> None:
        if not self._analysis_needs_template():
            return
        from .sweep_dialog import SweepDialog

        dialog = SweepDialog(self, parent=self)
        dialog.exec()

    def _open_moderation(self) -> None:
        if not self._analysis_needs_template():
            return
        if not any(r.key == "moderator" for r in self.spec.material_roles):
            self.statusBar().showMessage(
                "The moderation curve needs a template with a moderator (pin cell or assembly)."
            )
            return
        from .moderation_dialog import ModerationDialog

        ModerationDialog(self, parent=self).exec()

    def _open_poisoning(self) -> None:
        if not self._analysis_needs_template():
            return
        if not any(r.key == "moderator" for r in self.spec.material_roles):
            self.statusBar().showMessage(
                "Poisoning applies to a thermal fuel lattice (pin cell or assembly)."
            )
            return
        from .poisoning_dialog import PoisoningDialog

        PoisoningDialog(self, parent=self).exec()

    def _open_mgxs(self) -> None:
        if not self._analysis_needs_template():
            return
        from .mgxs_dialog import MgxsDialog

        MgxsDialog(self, parent=self).exec()

    def _open_depletion(self) -> None:
        if not self._analysis_needs_template():
            return
        from nbeast.core import depletion

        if depletion.is_available():
            from .depletion_dialog import DepletionDialog

            DepletionDialog(self, parent=self).exec()
        else:
            from .depletion_setup import DepletionSetupDialog

            dialog = DepletionSetupDialog(parent=self)
            dialog.configured.connect(
                lambda: self.statusBar().showMessage("Depletion data configured — "
                                                     "reopen Analysis ▸ Depletion / burnup.")
            )
            dialog.exec()

    def _open_data_manager(self, prefill=None) -> None:
        from .data_manager import DataManagerDialog

        dialog = DataManagerDialog(active_xml=self._cross_sections, parent=self, prefill=prefill)
        dialog.activated.connect(self.set_active_library)
        dialog.exec()

    def _open_cad_import(self) -> None:
        from .cad_import import CadImportDialog

        # Reuse an already-open panel rather than stacking dialogs.
        if getattr(self, "_cad_dialog", None) is not None:
            self._cad_dialog.raise_()
            self._cad_dialog.activateWindow()
            return
        dialog = CadImportDialog(cross_sections=self._cross_sections, parent=self)
        # Seed the dialog's run quality from the model tree's Settings, so those
        # settings aren't decorative for the CAD template.
        dialog.batches.setValue(self.batches_spin.value())
        dialog.particles.setValue(self.particles_spin.value())
        dialog.completed.connect(self._on_cad_completed)
        dialog.finished.connect(lambda _=0: setattr(self, "_cad_dialog", None))
        self._cad_dialog = dialog
        # Non-modal: the main window's 3D viewport must stay live so previews and
        # results can render into it. Rendering to it while a *modal* dialog blocks
        # the event loop crashes the GL context on macOS.
        dialog.setModal(False)
        dialog.show()

    def _on_cad_completed(self, res: dict) -> None:
        from nbeast.core.runner import RunResult

        # Remember the config so the CAD template's tree shows it.
        self._cad["step"] = res.get("step")
        self._cad["materials"] = list(res.get("material_tags", []))
        if self._is_cad:
            self._refresh_tree()

        self.statusBar().showMessage(
            f"CAD run: k-eff = {res['keff']:.4f} ± {res['keff_std']:.4f}"
        )
        sp = res.get("statepoint")
        if sp and Path(sp).exists():
            # Load through the normal results path, tagged as CAD so every field renders
            # volumetrically on the geometry (Convergence, spectrum, diagnostics too).
            self.last_result = RunResult(keff=res["keff"], keff_std=res["keff_std"], statepoint=sp)
            overlay = (res.get("stls"), res.get("colors"), res.get("labels"))
            self._load_results(sp, cad_overlay=overlay)
            self._replay_convergence(sp, 0)
            self.tabs.setCurrentWidget(self.flux_view)
        elif res.get("energy_edges") and res.get("flux"):
            self.spectrum_view.set_spectrum(res["energy_edges"], res["flux"])
            if res.get("flux_map") and res.get("map_bounds"):
                b = res["map_bounds"]
                self.tabs.setCurrentWidget(self.flux_view)
                self.flux_view.show_field_array(
                    res["flux_map"], (b[0], b[1]), (b[2], b[3]), title="CAD flux map"
                )

    def _open_cad_setup(self) -> None:
        from .cad_setup import CadSetupDialog

        CadSetupDialog(parent=self).exec()

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
        """Write the OpenMC deck + provenance + a PDF/PNG report + spectrum CSV."""
        from nbeast.core import export, provenance
        from nbeast.gui import report

        out_dir = Path(out_dir)
        if not (self.last_result and self._statepoint):
            self.statusBar().showMessage("Run a simulation before exporting a report.")
            return None
        if self.spec is None:
            self.statusBar().showMessage(
                "Report export isn't available for the CAD template yet — use Export raw data."
            )
            return None

        values = self._param_values[self._template]
        model = self._build_model()
        meta = provenance.capture(
            template=self._template,
            parameters=values,
            model=model,
            cross_sections=self._cross_sections,
            threads=os.environ.get("OMP_NUM_THREADS"),
        )
        export.export_deck(model, out_dir / "openmc_deck", metadata=meta)

        if self.last_result.keff is not None:
            header = f"k-effective = {self.last_result.keff:.5f} +/- {self.last_result.keff_std:.5f}"
        else:
            header = f"Fixed-source run — {len(self.last_result.batches)} batches"
        lines = [header, "", "Materials:"]
        for role in self.spec.material_roles:
            mat_key = self._material_values[self._template][role.key]
            lines.append(f"  {role.label} = {materials.LIBRARY[mat_key].label}")
        lines += ["", "Parameters:"]
        for param in self.spec.parameters:
            value = values[param.key]
            text = f"{int(value)}" if param.kind == "int" else f"{value:.{param.decimals}f}"
            lines.append(f"  {param.label} = {text} {param.unit}".rstrip())
        lines.append(f"  batches = {self.batches_spin.value()}")
        lines.append(f"  particles/batch = {self.particles_spin.value()}")
        lines.append(f"  seed = {self.seed_spin.value()}")
        if self.last_diagnostics is not None:
            lines += ["", "Diagnostics:"] + [f"  {ln}" for ln in self.last_diagnostics.summary_lines()]
        lines += ["", "Provenance:"] + [f"  {ln}" for ln in meta.summary_lines()]

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
        # Remember the current model, and don't leave a worker subprocess running.
        self._persist_state()
        self.controller.stop_and_wait()
        if getattr(self, "_cad_dialog", None) is not None:
            self._cad_dialog.close()
        super().closeEvent(event)
