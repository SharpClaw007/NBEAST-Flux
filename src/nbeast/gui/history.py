"""The Run history panel — every saved run, ready to reload, compare, or remove.

Persisted runs live in the active :class:`~nbeast.core.project.Project`; this widget
just lists them and turns user gestures into signals the main window acts on. Select
one and **Load** to bring its results back into the viewports; select two and
**Compare** to diff them.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class HistoryPanel(QWidget):
    loadRequested = Signal(str)            # run id
    compareRequested = Signal(str, str)    # run id A, run id B
    deleteRequested = Signal(list)         # list[str] of run ids

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setToolTip(
            "Saved runs in this project. Double-click (or select one + Load) to view a "
            "run's results; select two + Compare to diff them."
        )
        self.list.itemDoubleClicked.connect(self._on_double_click)
        self.list.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.list)

        buttons = QHBoxLayout()
        self.load_btn = QPushButton("Load")
        self.load_btn.clicked.connect(self._on_load)
        self.compare_btn = QPushButton("Compare")
        self.compare_btn.setToolTip("Select exactly two runs to compare them.")
        self.compare_btn.clicked.connect(self._on_compare)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._on_delete)
        for b in (self.load_btn, self.compare_btn, self.delete_btn):
            buttons.addWidget(b)
        layout.addLayout(buttons)

        self._update_buttons()

    # ---- population -------------------------------------------------------
    def set_runs(self, records) -> None:
        """Replace the list contents with the given run records (newest at top)."""
        self.list.clear()
        for rec in reversed(list(records)):
            item = QListWidgetItem(rec.title())
            item.setData(Qt.UserRole, rec.id)
            if rec.warnings:
                item.setToolTip("⚠ " + "; ".join(rec.warnings))
            self.list.addItem(item)
        self._update_buttons()

    def _selected_ids(self) -> list[str]:
        return [it.data(Qt.UserRole) for it in self.list.selectedItems()]

    # ---- interaction ------------------------------------------------------
    def _update_buttons(self) -> None:
        n = len(self.list.selectedItems())
        self.load_btn.setEnabled(n == 1)
        self.compare_btn.setEnabled(n == 2)
        self.delete_btn.setEnabled(n >= 1)

    def _on_double_click(self, item: QListWidgetItem) -> None:
        self.loadRequested.emit(item.data(Qt.UserRole))

    def _on_load(self) -> None:
        ids = self._selected_ids()
        if len(ids) == 1:
            self.loadRequested.emit(ids[0])

    def _on_compare(self) -> None:
        ids = self._selected_ids()
        if len(ids) == 2:
            self.compareRequested.emit(ids[0], ids[1])

    def _on_delete(self) -> None:
        ids = self._selected_ids()
        if ids:
            self.deleteRequested.emit(ids)
