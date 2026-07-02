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
    QDoubleSpinBox,
    QFileDialog,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QTreeWidgetItem,
)

from nbeast.core import cad, materials, specs, tallies
from nbeast.core.project import Project

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

# The mesh fields the Results panel offers (a 2D-slice entry, and a 3D entry where 3D
# is meaningful). Order sets the list order; each field's 3D entry follows its 2D one.
_FIELD_ENTRIES = (
    ("Scalar flux", "flux"),
    ("Fission rate", "fission"),
    ("Absorption rate", "absorption"),
    ("Neutron production (ν-fission)", "nu-fission"),
    ("Heating (energy deposition)", "heating"),
    ("Neutron dose rate", "dose"),
    ("Flux relative error", "flux_rel_err"),
)
_3D_SUFFIX = "__3d"


def _inactive_for(batches: int) -> int:
    """A safe inactive-cycle count that leaves active batches even for small runs."""
    return min(20, max(5, batches // 5))


class MainWindow(QMainWindow):
    def __init__(self, run_root: str | Path | None = None,
                 project_dir: str | Path | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NBEAST — neutron-flux Monte Carlo")
        self.resize(1440, 900)
        self._restore_window_state()

        if run_root is not None:
            self._run_root = Path(run_root)
            default_project = self._run_root / "project"
        else:
            self._run_root = Path(tempfile.gettempdir()) / "nbeast"
            default_project = Path.home() / ".nbeast" / "default-project"
        # The document: single source of truth for template/params/materials, with
        # the undo stack. MainWindow's _template/_param_values/_material_values are
        # delegating properties so existing code and tests keep working.
        from .document import Document

        self.doc = Document(self)
        self.doc.param_changed.connect(self._on_doc_param_changed)
        self.doc.material_changed.connect(self._on_doc_material_changed)
        # Custom-CAD template state (populated by the CAD import dialog).
        self._cad = {"step": None, "materials": []}
        self._cad_dialog = None   # the non-modal CAD import panel, when open
        self._cad_result = False  # current results are from a CAD run (render volumetric)
        self._cad_overlay = None  # (stls, colors, labels) geometry to overlay on CAD fields
        self._unit_system = "SI"  # display units (SI / US-Imperial)
        self._power_w = 0.0       # reactor power (eigenvalue) for absolute units; 0 = relative
        self._source_strength = 0.0  # source rate n/s (fixed source) for absolute units
        self._total_batches = 0
        self._active_study: str | None = None
        self._statepoint: str | None = None
        self._cross_sections = os.environ.get("OPENMC_CROSS_SECTIONS")
        self._starter_xml = self._cross_sections  # the bundled library ('reset' target)
        materials.refresh_auto_materials(self._cross_sections, self._starter_xml)
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
        self._build_shell()
        self._restore_from_project()
        self._sanitize_material_values()
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
        open_project_action.setShortcut("Ctrl+O")
        open_project_action.triggered.connect(self._open_project)
        file_menu.addAction(open_project_action)
        save_action = QAction("Save project state", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self._persist_state)
        file_menu.addAction(save_action)
        file_menu.addSeparator()

        export_action = QAction("Export report…", self)
        export_action.triggered.connect(self._on_export)
        file_menu.addAction(export_action)

        raw_action = QAction("Export raw data…", self)
        raw_action.setToolTip("Export mesh-tally arrays with uncertainties (NumPy / CSV / HDF5).")
        raw_action.triggered.connect(self._on_export_raw)
        file_menu.addAction(raw_action)

        data_action = QAction("Data library…", self)
        data_action.triggered.connect(lambda: self._open_data_library())
        file_menu.addAction(data_action)

        # CAD geometry (DAGMC) is picked from the Template dropdown ("Custom CAD");
        # when the native envs aren't present, offer setup here.
        if not cad.is_available():
            setup_action = QAction("Set up CAD geometry support…", self)
            setup_action.triggered.connect(self._open_cad_setup)
            file_menu.addAction(setup_action)

        edit_menu = self.menuBar().addMenu("&Edit")
        undo_action = self.doc.undo_stack.createUndoAction(self, "Undo")
        undo_action.setShortcut("Ctrl+Z")                 # ⌘Z on macOS
        redo_action = self.doc.undo_stack.createRedoAction(self, "Redo")
        redo_action.setShortcut("Ctrl+Shift+Z")           # ⇧⌘Z on macOS
        edit_menu.addAction(undo_action)
        edit_menu.addAction(redo_action)
        self.doc.undo_stack.indexChanged.connect(self._on_undo_redo)

        view_menu = self.menuBar().addMenu("&View")
        for i, label in enumerate(("Geometry", "Convergence", "Flux map", "Spectrum"), start=1):
            action = QAction(label, self)
            action.setShortcut(f"Ctrl+{i}")
            action.triggered.connect(lambda _c=False, idx=i - 1: self.tabs.setCurrentIndex(idx))
            view_menu.addAction(action)
        view_menu.addSeparator()
        messages_action = QAction("Messages", self)
        messages_action.setShortcut("Ctrl+L")
        messages_action.triggered.connect(
            lambda: self.messages.toggle.setChecked(not self.messages.toggle.isChecked()))
        view_menu.addAction(messages_action)

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

    def _sanitize_material_values(self) -> None:
        """Drop stale material selections — a persisted key not in the current LIBRARY
        (e.g. an auto element material like 'element_Pu' whose data is no longer active)
        would otherwise crash the tree/build. Revert such a role to its template default."""
        from nbeast.core import specs

        for template, roles in self._material_values.items():
            defaults = specs.SPECS[template].material_defaults() if template in specs.SPECS else {}
            for role_key, mat_key in list(roles.items()):
                if mat_key not in materials.LIBRARY:
                    roles[role_key] = defaults.get(role_key, mat_key)

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
        tb.setObjectName("main_toolbar")   # required for saveState()
        tb.setMovable(False)
        self.addToolBar(tb)

        tb.addWidget(QLabel(" Template: "))
        self.template_combo = QComboBox()
        self.template_combo.addItems([*specs.SPECS.keys(), CAD_TEMPLATE])
        self.template_combo.setToolTip("Choose the model to simulate (or import custom CAD).")
        self.template_combo.currentTextChanged.connect(self.set_template)
        tb.addWidget(self.template_combo)

        tb.addSeparator()
        self.run_action = QAction("▶ Run", self)
        self.run_action.setShortcut("Ctrl+R")             # ⌘R on macOS
        self.run_action.setToolTip("Run the simulation (⌘R).")
        self.run_action.triggered.connect(self.start_run)
        tb.addAction(self.run_action)
        self.stop_action = QAction("■ Stop", self)
        self.stop_action.setEnabled(False)
        self.stop_action.setShortcut("Ctrl+.")            # ⌘. — the macOS cancel idiom
        self.stop_action.setToolTip("Stop the running simulation, keeping results so far (⌘.).")
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

    def _build_shell(self) -> None:
        """The COMSOL-style three-pane shell: Model Builder tree | settings pane |
        viewport tabs over a messages strip. Replaces the five-dock layout."""
        from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

        from .messages import MessagesStrip
        from .model_builder import ModelBuilderTree

        # -- left: the tree ------------------------------------------------------
        self.model_tree = ModelBuilderTree()
        self.model_tree.setToolTip(
            "The Model Builder. Model: click a group to edit it. Studies: click an "
            "analysis to open it. Results: click a field to view it; saved runs live "
            "under Results ▸ Saved runs."
        )
        self.model_tree.itemClicked.connect(self._on_tree_click)
        self.model_tree.itemDoubleClicked.connect(self._on_tree_double_click)
        self.model_tree.historyLoadRequested.connect(self._load_history_run)
        self.model_tree.historyCompareRequested.connect(self._compare_history_runs)
        self.model_tree.historyDeleteRequested.connect(self._delete_history_runs)
        self.model_tree.studyAddRequested.connect(self._add_study)
        self.model_tree.studyRenameRequested.connect(self._rename_study)
        self.model_tree.studyDuplicateRequested.connect(self._duplicate_study)
        self.model_tree.studyDeleteRequested.connect(self._delete_study)

        # -- middle: settings pane (header + a stack: property editors | study pane) --
        from PySide6.QtWidgets import QStackedWidget

        from .studies import StudyPane, StudyStore

        self.studies = StudyStore(self.project)
        self.settings_header = QLabel("Settings")
        header_font = self.settings_header.font()
        header_font.setBold(True)
        self.settings_header.setFont(header_font)
        self.settings_hint = QLabel("Select a node in the Model Builder to edit it.")
        self.settings_hint.setWordWrap(True)
        self.properties = QTableWidget(0, 2)
        self.properties.setHorizontalHeaderLabels(["Property", "Value"])
        self.properties.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.properties.verticalHeader().setVisible(False)
        self.study_pane = StudyPane(self.studies)
        self.study_pane.runRequested.connect(self._run_study)
        self.study_pane.loadRequested.connect(self._load_study_run)
        self._settings_stack = QStackedWidget()
        self._settings_stack.addWidget(self.properties)      # page 0: model editors
        self._settings_stack.addWidget(self.study_pane)      # page 1: study config
        settings_pane = QWidget()
        pane_layout = QVBoxLayout(settings_pane)
        pane_layout.setContentsMargins(8, 8, 8, 8)
        pane_layout.setSpacing(6)
        pane_layout.addWidget(self.settings_header)
        pane_layout.addWidget(self.settings_hint)
        pane_layout.addWidget(self._settings_stack, 1)

        # -- right: viewport tabs over the messages strip --------------------------
        from .geometry_view import GeometryView

        self.tabs = QTabWidget()
        self.geometry_view = GeometryView()
        self.monitor = ConvergenceMonitor()
        self.flux_view = FluxViewport()
        self.spectrum_view = SpectrumView()
        self.tabs.addTab(self.geometry_view, "Geometry")
        self.tabs.addTab(self.monitor, "Convergence")
        self.tabs.addTab(self.flux_view, "Flux map")
        self.tabs.addTab(self.spectrum_view, "Spectrum")
        self.messages = MessagesStrip()
        right = QSplitter(Qt.Vertical)
        right.addWidget(self.tabs)
        right.addWidget(self.messages)
        right.setStretchFactor(0, 1)
        right.setCollapsible(0, False)

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.addWidget(self.model_tree)
        self._splitter.addWidget(settings_pane)
        self._splitter.addWidget(right)
        self._splitter.setStretchFactor(2, 1)
        self._splitter.setSizes([250, 300, 890])
        self.setCentralWidget(self._splitter)

        self._current_score: str | None = None
        self._rebuild_results_list()
        self.model_tree.set_results_enabled(False)
        self._update_analysis_availability()

        # Live geometry preview: any document change refreshes it (debounced so
        # spin-drags repaint once, not per tick). The Geometry tab is the default view.
        from PySide6.QtCore import QTimer

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(150)
        self._preview_timer.timeout.connect(self._refresh_geometry_preview)
        self.doc.changed.connect(self._preview_timer.start)
        self._refresh_geometry_preview()
        self._ensure_default_study()
        self._refresh_studies()
        self.tabs.setCurrentWidget(self.geometry_view)

    # ---- document delegation ------------------------------------------------
    # State lives on self.doc; these properties keep the historical attribute names
    # working across the codebase and test suite.
    @property
    def _template(self) -> str:
        return self.doc.template

    @_template.setter
    def _template(self, name: str) -> None:
        self.doc.set_template(name)

    @property
    def _param_values(self) -> dict:
        return self.doc.param_values

    @property
    def _material_values(self) -> dict:
        return self.doc.material_values

    def _on_doc_param_changed(self, _template: str, _key: str) -> None:
        self._refresh_tree()

    def _on_doc_material_changed(self, _template: str, _key: str) -> None:
        self._refresh_tree()

    def _on_undo_redo(self, _idx: int) -> None:
        """After undo/redo, re-render the open editor so its widgets show the
        restored values (the tree refreshes via the doc signals)."""
        item = self.model_tree.currentItem()
        if item is None:
            return
        kind = self.model_tree.node_kind(item)
        if kind and kind[0] == "group":   # only editors re-render; never re-open tools
            self._show_group_editors(str(kind[1]))

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
        """Programmatic + UI entry point for editing a parameter (undoable). The tree
        refreshes via the document signal (not Properties — keep editor focus)."""
        self.doc.edit_param(key, value)

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
        self._refresh_geometry_preview()
        item = self.model_tree.currentItem()
        kind = self.model_tree.node_kind(item) if item is not None else None
        if kind and kind[0] == "group":   # re-render an open editor in the new unit
            self._show_group_editors(str(kind[1]))
        # re-render the field on screen so its colorbar unit updates
        if self.tabs.currentWidget() is self.flux_view:
            self._rerender_current_result()

    def _field_bar_title(self, score: str) -> str:
        from nbeast.core import units

        return units.colorbar_title(score, self._unit_system, self._absolute_units())

    def _on_power_changed(self, value: float) -> None:
        if self._is_fixed_source:
            self._source_strength = float(value)
        else:
            self._power_w = float(value)
        self._refresh_tree()
        if self.tabs.currentWidget() is self.flux_view:
            self._rerender_current_result()
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

    def _refresh_geometry_preview(self) -> None:
        """Rebuild the pre-run geometry preview from the current document state."""
        if not hasattr(self, "geometry_view"):
            return
        if self._is_cad:
            step = self._cad.get("step")
            self.geometry_view.set_hint(
                f"CAD geometry: {os.path.basename(step)} — the import dialog shows the "
                "colour-coded 3D preview." if step else
                "Custom CAD — click Run (or Model ▸ Geometry) to import a STEP file.")
            return
        from nbeast.core import render_geometry

        preview = render_geometry.preview(
            self._template, self._param_values.get(self._template, {}),
            self._material_values.get(self._template, {}))
        if preview is None:
            self.geometry_view.set_hint("No preview for this template.")
            return
        self.geometry_view.set_preview(
            preview, self._unit_system, materials.available_names(self._cross_sections))

    def _refresh_tree(self) -> None:
        self._update_analysis_availability()
        if self._is_cad:
            self.model_tree.set_model_groups(self._cad_tree_groups())
            return
        spec = self.spec

        materials_item = QTreeWidgetItem(["Materials"])
        for role in spec.material_roles:
            mat_key = self._material_values[self._template][role.key]
            spec_obj = materials.LIBRARY.get(mat_key)
            mat_label = spec_obj.label if spec_obj else f"{mat_key} (unavailable)"
            materials_item.addChild(QTreeWidgetItem([f"{role.label}: {mat_label}"]))
        for p in spec.params_in("Materials"):
            materials_item.addChild(QTreeWidgetItem([self._value_text(p)]))

        geometry = QTreeWidgetItem(["Geometry"])
        geometry.addChild(QTreeWidgetItem([spec.geometry]))
        for p in spec.params_in("Geometry"):
            geometry.addChild(QTreeWidgetItem([self._value_text(p)]))

        self.model_tree.set_model_groups(
            [materials_item, geometry, self._settings_tree_item()])

    def _cad_tree_groups(self) -> list[QTreeWidgetItem]:
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
        return [materials_item, geometry, self._settings_tree_item()]

    # ---- tree routing (Model groups / Studies / Results / history) ------------
    def _on_tree_click(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        kind = self.model_tree.node_kind(item)
        if kind is None:
            return
        what, payload = kind
        if what == "group":
            self._settings_stack.setCurrentWidget(self.properties)
            self._show_group_editors(str(payload))
        elif what == "study":
            self._show_study(str(payload))
        elif what == "add_study":
            from PySide6.QtGui import QCursor

            self.model_tree._add_study_menu(QCursor.pos())
        elif what == "result":
            self._on_result_selected(str(payload))
        # history nodes act on double-click / context menu (selection stays cheap)

    def _on_tree_double_click(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        kind = self.model_tree.node_kind(item)
        if kind and kind[0] == "history":
            self._load_history_run(str(kind[1]))

    # ---- studies (persistent analyses) --------------------------------------
    def _ensure_default_study(self) -> None:
        """Every project has at least the default k-eff study, so Run has a home."""
        if not any(c.kind == "keff" for c in self.studies.configs()):
            self.studies.add("keff", self._current_settings())

    def _refresh_studies(self) -> None:
        instances = []
        for config in self.studies.configs():
            result = self.studies.get_result(config.study_id)
            summary = result.summary if result else "not run yet"
            instances.append((config.study_id, config.name, summary))
        self.model_tree.set_studies(instances)
        self._update_analysis_availability()

    def _show_study(self, study_id: str) -> None:
        config = self.studies.get(study_id)
        if config is None:
            return
        self.settings_header.setText(f"Study ▸ {config.name}")
        self.settings_hint.hide()
        self.study_pane.set_param_choices(
            [(p.key, f"{p.label} ({p.unit})" if p.unit else p.label)
             for p in (self.spec.parameters if self.spec else [])])
        self.study_pane.show_study(config)
        self._settings_stack.setCurrentWidget(self.study_pane)

    def _add_study(self, kind: str) -> None:
        config = self.studies.add(kind, self._current_settings())
        self._refresh_studies()
        self.model_tree.select_study(config.study_id)
        self._show_study(config.study_id)

    def _rename_study(self, study_id: str) -> None:
        config = self.studies.get(study_id)
        if config is None:
            return
        name, ok = QInputDialog.getText(self, "Rename study", "Name:", text=config.name)
        if ok and name.strip():
            self.studies.rename(study_id, name.strip())
            self._refresh_studies()

    def _duplicate_study(self, study_id: str) -> None:
        new = self.studies.duplicate(study_id)
        self._refresh_studies()
        if new is not None:
            self.model_tree.select_study(new.study_id)
            self._show_study(new.study_id)

    def _delete_study(self, study_id: str) -> None:
        self.studies.delete(study_id)
        self._refresh_studies()

    def _run_study(self, study_id: str) -> None:
        config = self.studies.get(study_id)
        if config is None:
            return
        self._active_study = study_id
        if config.kind == "keff":
            self.start_run()                       # the run archives + we snapshot on finish
            return
        # The richer analyses keep their (working) tool UIs, now launched from the
        # persistent study and seeded from its saved config; result persistence for
        # these lands in G4. Config already persisted by the pane.
        opener = {
            "sweep": self._open_sweep, "search": self._open_sweep,
            "moderation": self._open_moderation, "poisoning": self._open_poisoning,
            "mgxs": self._open_mgxs, "depletion": self._open_depletion,
        }.get(config.kind)
        if opener is not None:
            opener()

    def _load_study_run(self, study_id: str) -> None:
        """Reload a keff study's most recent archived run into the viewports."""
        runs = [r for r in self.project.runs]
        if runs:
            self._load_history_run(runs[-1].id)
        else:
            self._log("No saved run for this study yet — run it first.")

    def _show_group_editors(self, group: str) -> None:
        self.settings_header.setText(f"Model ▸ {group}")
        self.settings_hint.hide()
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
        """A type-to-filter dropdown of **every installed material** — any of them can
        go in any slot. Role-typical materials (this slot's category) are listed first,
        then all other installed materials. Materials that still need data aren't shown
        (install them in the Data Library); the only exception is the current selection
        if its data was removed, so it stays visible."""
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setToolTip(
            "Any installed material can be assigned to any slot. Install more materials "
            "in the Data Library (File ▸ Data library…)."
        )
        current = self._material_values[self._template][role.key]
        typical = [m for m in materials.by_category(role.category) if m.is_available(available)]
        typical_keys = {m.key for m in typical}
        others = sorted((m for m in materials.LIBRARY.values()
                         if m.is_available(available) and m.key not in typical_keys),
                        key=lambda m: m.label)
        ordered = typical + others
        keys = [m.key for m in ordered]
        if current not in keys and current in materials.LIBRARY:
            ordered.insert(0, materials.LIBRARY[current])   # keep a data-removed selection visible
            keys.insert(0, current)

        for mspec in ordered:
            ok = mspec.is_available(available)
            combo.addItem(mspec.label if ok else f"{mspec.label} — needs data", mspec.key)
            if not ok:
                combo.setItemData(combo.count() - 1, QColor("#999"), Qt.ForegroundRole)
        combo.setCurrentIndex(keys.index(current) if current in keys else 0)

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
        self.doc.edit_material(role_key, mat_key)   # undoable; tree refreshes via signal
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
            "Open the Data Library to download it?",
        )
        if resp == QMessageBox.Yes:
            self._open_data_library(focus_category=self._data_category_for(mspec))

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
            mspec = materials.LIBRARY.get(self._material_values[self._template][role.key])
            if mspec is None or not mspec.is_available(avail):
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
            names = ", ".join((m.label if m else r.label) for r, m in missing)
            self.statusBar().showMessage(
                f"Can't run — {names} need cross-section data. "
                "Download it via File ▸ Data library…"
            )
            return
        model = self._build_model()
        self._persist_state()  # remember the current model so reopening restores it
        self.monitor.reset()
        self.monitor.mark_inactive(0 if self._is_fixed_source else _inactive_for(self.batches_spin.value()))
        self.spectrum_view.clear()
        self.model_tree.set_results_enabled(False)
        self.run_action.setEnabled(False)
        self.stop_action.setEnabled(True)
        self._log(f"Run started — {self._template}, {self.batches_spin.value()} batches × "
                  f"{self.particles_spin.value()} particles (seed {self.seed_spin.value()})")
        self.statusBar().showMessage("Running…")
        self._current_run_dir = self._run_root / "current"
        self.controller.start(model, self._current_run_dir)

    def _log(self, text: str, level: str = "info") -> None:
        """Mirror a message to the messages strip (persistent) + status bar (transient)."""
        if hasattr(self, "messages"):
            self.messages.log(text, level)
        self.statusBar().showMessage(text)

    def stop_run(self) -> None:
        self.controller.cancel()
        self.statusBar().showMessage("Stopping…")

    def _on_started(self, n_batches: int) -> None:
        self._total_batches = n_batches
        self.messages.start_progress(n_batches, "batch 0")
        self.statusBar().showMessage(f"Running… 0/{n_batches} batches")

    def _on_batch(self, update) -> None:
        self.monitor.add_point(
            update.batch, update.keff, update.keff_std, getattr(update, "entropy", None)
        )
        k_note = "" if update.keff is None else f"  k = {update.keff:.5f}"
        self.messages.set_progress(update.batch, f"batch {update.batch}/{self._total_batches}")
        self.statusBar().showMessage(
            f"Running… batch {update.batch}/{self._total_batches}{k_note}"
        )

    def _on_finished(self, result) -> None:
        self.last_result = result
        self.run_action.setEnabled(True)
        self.stop_action.setEnabled(False)
        self.messages.clear_progress()
        k_txt = f"{result.keff:.5f}" if result.keff is not None else "n/a"
        if result.cancelled:
            self._log(f"Stopped at batch {len(result.batches)} (k ≈ {k_txt})", "warning")
        elif result.keff is not None:
            self._log(f"Done — k = {k_txt} ± {result.keff_std:.5f}")
        else:
            self._log(f"Done — fixed-source run ({len(result.batches)} batches)")
        # Surface how the requested temperature was treated (nearest-snapping + the
        # 294 K-pinned thermal kernel) so the approximation isn't silent.
        temperature = self._param_values.get(self._template, {}).get("temperature")
        if temperature is not None:
            from nbeast.core import templates

            note = templates.temperature_note(temperature)
            if note:
                self.statusBar().showMessage(f"{self.statusBar().currentMessage()}  ({note})")
        if not result.cancelled and result.statepoint:
            self._load_results(result.statepoint)
            self._archive_run(result)
            self._snapshot_keff_study(result)

    def _snapshot_keff_study(self, result) -> None:
        """Persist a k-eff run's headline result onto the active (or default) study."""
        from datetime import datetime, timezone

        from nbeast.core.studies import StudyResult

        study_id = self._active_study
        if study_id is None or self.studies.get(study_id) is None \
                or self.studies.get(study_id).kind != "keff":
            study_id = next((c.study_id for c in self.studies.configs() if c.kind == "keff"),
                            None)
        if study_id is None:
            return
        diag = self.last_diagnostics
        if result.keff is not None:
            summary = f"k = {result.keff:.5f} ± {result.keff_std:.5f}"
            scalars = {"keff": result.keff, "keff_std": result.keff_std}
        else:
            summary = f"fixed-source run ({len(result.batches)} batches)"
            scalars = {}
        self.studies.set_result(study_id, StudyResult(
            ok=True, summary=summary, scalars=scalars,
            warnings=list(diag.warnings) if diag else [],
            created_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
        self._refresh_studies()
        self.study_pane.refresh_result()

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
        self._rebuild_results_list(enabled=True)
        # Default view: 2D flux slice for templates, 3D flux volume for CAD (its headline).
        if self._cad_result:
            self._select_result("flux" + _3D_SUFFIX)
            self._current_score = "flux" + _3D_SUFFIX
            self._show_cad_field("flux", switch_tab=False)
        else:
            self._select_result("flux")
            self._current_score = "flux"
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
        for caution in diag.warnings:      # persistent record of every caution
            if hasattr(self, "messages"):
                self.messages.log(caution, "warning")
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
        """Render the chosen mesh field as a 2D slice map in the Flux-map tab.

        A ``*_rel_err`` score shows the relative-error map: the VTK written for the
        base score also carries its ``<label>_rel_err`` array, so we reuse it.
        """
        if not self._statepoint:
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

    # ---- results section ----------------------------------------------------
    def _result_entries(self) -> list[tuple[str, str]]:
        """(label, score) pairs: a 2D-slice + a 3D entry per field, per the current
        results' geometry: z-uniform templates and CAD get 3D for every field; a
        true-3D template (Godiva) gets 3D only for the scalar flux (its real 3D tally)."""
        is_cad = self._cad_result
        z_inv = (not is_cad) and self.spec is not None and self.spec.z_invariant
        entries: list[tuple[str, str]] = []
        for label, score in _FIELD_ENTRIES:
            entries.append((label, score))                       # 2D slice
            if is_cad or z_inv or score == "flux":               # 3D where meaningful
                entries.append((f"{label} (3D)", score + _3D_SUFFIX))
        if not is_cad:
            entries.append(("Neutron tracks", "tracks"))
        return entries

    def _rebuild_results_list(self, enabled: bool | None = None) -> None:
        if enabled is None:
            enabled = bool(self._statepoint)
        self.model_tree.set_result_entries(self._result_entries(), enabled)

    def _select_result(self, score: str) -> None:
        self.model_tree.select_result(score)

    def _on_result_selected(self, score: str) -> None:
        self._current_score = score
        if score == "tracks":
            self.show_tracks()
            return
        is_3d = score.endswith(_3D_SUFFIX)
        base = score[: -len(_3D_SUFFIX)] if is_3d else score
        if not is_3d:
            self._show_field(base, switch_tab=True)         # 2D slice
        elif self._cad_result:
            self._show_cad_field(base, switch_tab=True)     # 3D volume on geometry
        elif self.spec is not None and self.spec.z_invariant:
            self._show_extruded_field(base, switch_tab=True)  # extruded 3D block
        else:
            self._show_volume()                              # real 3D flux (Godiva)

    def _rerender_current_result(self) -> None:
        """Re-render the field on screen (units / normalization changed)."""
        if self._statepoint and self._current_score and self._current_score != "tracks":
            self._on_result_selected(self._current_score)

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
        self.messages.clear_progress()
        self._log(f"Error: {message}", "error")

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
        self.model_tree.set_history(self.project.runs)

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
        self.studies = self.studies.__class__(project)
        self.study_pane._store = self.studies
        self._restore_from_project()
        self._ensure_default_study()
        self._refresh_tree()
        self._refresh_history()
        self._refresh_studies()
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
        """Offer only the study kinds that apply to the current template in Add-study."""
        if not hasattr(self, "model_tree"):
            return
        from nbeast.core import studies as core_studies

        spec = self.spec
        eigen = spec is not None and not self._is_fixed_source
        moderated = eigen and any(r.key == "moderator" for r in spec.material_roles)
        kinds = core_studies.available_kinds(eigenvalue=eigen, moderated=moderated)
        self.model_tree.set_addable_kinds(
            [(k, core_studies.STUDY_KINDS[k].label) for k in kinds])

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
            self.statusBar().showMessage("Depletion data isn't set up — opening the Data Library.")
            self._open_data_library(focus_category="Depletion")

    def _open_data_library(self, focus_category=None) -> None:
        from .data_library import DataLibraryDialog

        dialog = DataLibraryDialog(
            active_xml=self._cross_sections, starter_xml=self._starter_xml,
            parent=self, focus_category=focus_category,
        )
        dialog.activated.connect(self.set_active_library)
        dialog.exec()

    @staticmethod
    def _data_category_for(mspec) -> str | None:
        """Display category in the Data Library for a material (for scroll-to focus)."""
        from .data_library import _MATERIAL_CATEGORIES

        for label, keys in _MATERIAL_CATEGORIES:
            if set(keys) & set(mspec.categories):
                return label
        return None

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
        # Downloaded elements become selectable materials; refresh the dropdowns now.
        materials.refresh_auto_materials(path, self._starter_xml)
        self._sanitize_material_values()   # drop any now-unavailable auto-material selection
        if getattr(self, "_template", None):
            self._render_materials_editors()
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

    # ---- window state (geometry/layout persist across launches) -------------
    @staticmethod
    def _qsettings():
        from PySide6.QtCore import QSettings

        return QSettings("NBEAST", "NBEAST")

    def _restore_window_state(self) -> None:
        try:
            s = self._qsettings()
            geometry = s.value("window/geometry")
            if geometry is not None:
                self.restoreGeometry(geometry)
        except Exception:  # noqa: BLE001 — never block startup on prefs
            pass

    def _save_window_state(self) -> None:
        try:
            s = self._qsettings()
            s.setValue("window/geometry", self.saveGeometry())
            s.setValue("window/state", self.saveState())
        except Exception:  # noqa: BLE001
            pass

    def closeEvent(self, event) -> None:
        # Remember the current model + window layout, and don't leave a worker
        # subprocess running.
        self._persist_state()
        self._save_window_state()
        self.controller.stop_and_wait()
        if getattr(self, "_cad_dialog", None) is not None:
            self._cad_dialog.close()
        super().closeEvent(event)
