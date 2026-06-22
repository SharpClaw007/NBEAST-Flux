"""NBEAST main window — the Caedium-style shell.

Toolbar (template + eigenvalue settings + Run/Stop), dockable Model tree and
Properties grid, and tabbed viewports (live convergence monitor + a 3D-view
placeholder for Phase 3). Transport runs off-thread via RunController.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QHeaderView,
    QLabel,
    QMainWindow,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
)

from nbeast import core

from .monitor import ConvergenceMonitor
from .run_controller import RunController

# Template metadata drives the UI without building an OpenMC model (so the
# window constructs even with no cross-section data). build() is only called on Run.
TEMPLATES = {
    "Pin cell": {
        "build": lambda batches, particles, inactive: core.templates.pin_cell(
            batches=batches, particles=particles, inactive=inactive
        ),
        "materials": ["UO₂ fuel", "Zircaloy", "Water"],
        "geometry": "PWR pin cell (reflective BCs)",
    },
    "Godiva": {
        "build": lambda batches, particles, inactive: core.benchmarks.godiva(
            batches=batches, particles=particles, inactive=inactive
        ),
        "materials": ["HEU metal (Godiva)"],
        "geometry": "Bare HEU sphere (vacuum BC)",
    },
}


def _inactive_for(batches: int) -> int:
    """A safe inactive-cycle count that leaves active batches even for small runs."""
    return min(20, max(5, batches // 5))


class MainWindow(QMainWindow):
    def __init__(self, run_root: str | Path | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NBEAST — neutron-flux Monte Carlo")
        self.resize(1100, 720)

        self._run_root = Path(run_root) if run_root else Path(tempfile.gettempdir()) / "nbeast"
        self._template = "Pin cell"
        self._total_batches = 0
        self.last_result = None

        self.controller = RunController()
        self.controller.started.connect(self._on_started)
        self.controller.batch.connect(self._on_batch)
        self.controller.finished.connect(self._on_finished)
        self.controller.failed.connect(self._on_failed)

        self._build_toolbar()
        self._build_docks()
        self._build_central()
        self.statusBar().showMessage("Ready")
        self._refresh_tree()

    # ---- construction -----------------------------------------------------
    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        tb.addWidget(QLabel(" Template: "))
        self.template_combo = QComboBox()
        self.template_combo.addItems(TEMPLATES.keys())
        self.template_combo.currentTextChanged.connect(self.set_template)
        tb.addWidget(self.template_combo)

        tb.addSeparator()
        tb.addWidget(QLabel(" Batches: "))
        self.batches_spin = QSpinBox()
        self.batches_spin.setRange(10, 100_000)
        self.batches_spin.setValue(100)
        self.batches_spin.valueChanged.connect(lambda _: self._refresh_tree())
        tb.addWidget(self.batches_spin)

        tb.addWidget(QLabel(" Particles/batch: "))
        self.particles_spin = QSpinBox()
        self.particles_spin.setRange(100, 10_000_000)
        self.particles_spin.setSingleStep(1000)
        self.particles_spin.setValue(2000)
        self.particles_spin.valueChanged.connect(lambda _: self._refresh_tree())
        tb.addWidget(self.particles_spin)

        tb.addSeparator()
        self.run_action = QAction("Run", self)
        self.run_action.triggered.connect(self.start_run)
        tb.addAction(self.run_action)
        self.stop_action = QAction("Stop", self)
        self.stop_action.setEnabled(False)
        self.stop_action.triggered.connect(self.stop_run)
        tb.addAction(self.stop_action)

    def _build_docks(self) -> None:
        self.model_tree = QTreeWidget()
        self.model_tree.setHeaderLabel("Model")
        self.model_tree.itemClicked.connect(self._on_tree_click)
        model_dock = QDockWidget("Model", self)
        model_dock.setWidget(self.model_tree)
        self.addDockWidget(Qt.LeftDockWidgetArea, model_dock)

        self.properties = QTableWidget(0, 2)
        self.properties.setHorizontalHeaderLabels(["Property", "Value"])
        self.properties.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.properties.verticalHeader().setVisible(False)
        props_dock = QDockWidget("Properties", self)
        props_dock.setWidget(self.properties)
        self.addDockWidget(Qt.LeftDockWidgetArea, props_dock)

    def _build_central(self) -> None:
        self.tabs = QTabWidget()
        self.monitor = ConvergenceMonitor()
        self.tabs.addTab(self.monitor, "Convergence")
        placeholder = QLabel("3D flux view — coming in Phase 3")
        placeholder.setAlignment(Qt.AlignCenter)
        self.tabs.addTab(placeholder, "3D View")
        self.setCentralWidget(self.tabs)

    # ---- model tree / properties -----------------------------------------
    def set_template(self, name: str) -> None:
        if name not in TEMPLATES:
            return
        self._template = name
        if self.template_combo.currentText() != name:
            self.template_combo.setCurrentText(name)
        self._refresh_tree()

    def _refresh_tree(self) -> None:
        self.model_tree.clear()
        meta = TEMPLATES[self._template]

        materials = QTreeWidgetItem(["Materials"])
        for label in meta["materials"]:
            materials.addChild(QTreeWidgetItem([label]))

        geometry = QTreeWidgetItem(["Geometry"])
        geometry.addChild(QTreeWidgetItem([meta["geometry"]]))

        settings = QTreeWidgetItem(["Settings"])
        settings.addChild(QTreeWidgetItem([f"batches = {self.batches_spin.value()}"]))
        settings.addChild(QTreeWidgetItem([f"particles/batch = {self.particles_spin.value()}"]))
        settings.addChild(QTreeWidgetItem([f"inactive = {_inactive_for(self.batches_spin.value())}"]))

        for item in (materials, geometry, settings):
            self.model_tree.addTopLevelItem(item)
            item.setExpanded(True)

    def _on_tree_click(self, item: QTreeWidgetItem, _column: int) -> None:
        rows = [("name", item.text(0))]
        if item.parent() is None:
            rows.append(("children", str(item.childCount())))
        else:
            rows.append(("group", item.parent().text(0)))
        self._set_properties(rows)

    def _set_properties(self, rows) -> None:
        self.properties.setRowCount(len(rows))
        for r, (key, value) in enumerate(rows):
            self.properties.setItem(r, 0, QTableWidgetItem(str(key)))
            self.properties.setItem(r, 1, QTableWidgetItem(str(value)))

    # ---- run lifecycle ----------------------------------------------------
    def _build_model(self):
        meta = TEMPLATES[self._template]
        batches = self.batches_spin.value()
        return meta["build"](batches, self.particles_spin.value(), _inactive_for(batches))

    def start_run(self) -> None:
        if self.controller.running:
            return
        model = self._build_model()
        self.monitor.reset()
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

    def _on_failed(self, message: str) -> None:
        self.last_result = None
        self.run_action.setEnabled(True)
        self.stop_action.setEnabled(False)
        self.statusBar().showMessage(f"Error: {message}")
