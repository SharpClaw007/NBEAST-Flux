"""The Model Builder tree — the COMSOL-style backbone of the shell.

One authoritative tree with three fixed roots:

* **Model** — the template's Materials / Geometry / Settings groups (clicking a group
  renders its editors in the settings pane, exactly like the old Model dock);
* **Studies** — the analyses (sweep, moderation, poisoning, MGXS, depletion), enabled
  per template; clicking one launches it (G1 parity: opens the existing tool — they
  become persistent studies in G3/G4);
* **Results** — the current run's viewable fields (2D + 3D per field, tracks) and the
  project's saved-run history, with a context menu (Load / Compare / Delete).

Nodes carry a ``(kind, payload)`` tuple in ``Qt.UserRole``; the main window routes
clicks by kind. The roots persist across refreshes — sections rebuild independently.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QMenu, QTreeWidget, QTreeWidgetItem

# node kinds (payload meaning): "group" (model group name) · "study" (study key) ·
# "result" (score) · "history" (run id) · "root" (section name)
KIND_ROLE = Qt.UserRole


def _kind(item: QTreeWidgetItem) -> tuple[str, object] | None:
    data = item.data(0, KIND_ROLE)
    return data if isinstance(data, tuple) else None


class ModelBuilderTree(QTreeWidget):
    historyLoadRequested = Signal(str)          # run id
    historyCompareRequested = Signal(str, str)  # run ids a, b
    historyDeleteRequested = Signal(list)       # run ids
    studyAddRequested = Signal(str)             # study kind to create
    studyRenameRequested = Signal(str)          # study id
    studyDuplicateRequested = Signal(str)       # study id
    studyDeleteRequested = Signal(str)          # study id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.setUniformRowHeights(True)

        self._addable_kinds: list[tuple[str, str]] = []   # (kind, label) for the add menu
        self.model_root = self._root("Model")
        self.studies_root = self._root("Studies")
        self.add_study_item = QTreeWidgetItem(["＋ Add study…"])
        self.add_study_item.setData(0, KIND_ROLE, ("add_study", None))
        self.add_study_item.setForeground(0, self.palette().brush(self.foregroundRole()))
        self.studies_root.addChild(self.add_study_item)
        self.results_root = self._root("Results")
        self.history_item = QTreeWidgetItem(["Saved runs"])
        self.history_item.setData(0, KIND_ROLE, ("root", "history"))
        self.results_root.addChild(self.history_item)
        for root in (self.model_root, self.studies_root, self.results_root):
            root.setExpanded(True)

    def _root(self, label: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label])
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        item.setData(0, KIND_ROLE, ("root", label))
        item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
        self.addTopLevelItem(item)
        return item

    # ---- section rebuilds ---------------------------------------------------
    @staticmethod
    def _clear_children(item: QTreeWidgetItem, keep=()) -> None:
        for child in [item.child(i) for i in range(item.childCount())]:
            if child not in keep:
                item.removeChild(child)

    def set_model_groups(self, groups: list[QTreeWidgetItem]) -> None:
        """Replace the Model section with the given group items (Materials/…)."""
        self._clear_children(self.model_root)
        for group in groups:
            group.setData(0, KIND_ROLE, ("group", group.text(0)))
            for j in range(group.childCount()):        # value rows select their group
                group.child(j).setData(0, KIND_ROLE, ("group", group.text(0)))
            self.model_root.addChild(group)
            group.setExpanded(True)

    def set_studies(self, instances: list[tuple[str, str, str]]) -> None:
        """instances = (study_id, name, last_summary). Persistent study nodes, followed
        by the always-present '＋ Add study…' node."""
        self._clear_children(self.studies_root, keep=(self.add_study_item,))
        for study_id, name, summary in instances:
            item = QTreeWidgetItem([name])
            item.setData(0, KIND_ROLE, ("study", study_id))
            if summary:
                item.setToolTip(0, summary)
            self.studies_root.insertChild(self.studies_root.childCount() - 1, item)
        self.studies_root.setExpanded(True)

    def set_addable_kinds(self, kinds: list[tuple[str, str]]) -> None:
        """(kind, label) pairs offered by the Add-study menu, per the current template."""
        self._addable_kinds = list(kinds)
        self.add_study_item.setDisabled(not kinds)

    def set_result_entries(self, entries: list[tuple[str, str]], enabled: bool) -> None:
        """entries = (label, score). The Saved-runs child is preserved."""
        self._clear_children(self.results_root, keep=(self.history_item,))
        for label, score in entries:
            item = QTreeWidgetItem([label])
            item.setData(0, KIND_ROLE, ("result", score))
            item.setDisabled(not enabled)
            # insert before the history item so saved runs stay last
            self.results_root.insertChild(self.results_root.childCount() - 1, item)
        self.results_root.setExpanded(True)

    def set_results_enabled(self, enabled: bool) -> None:
        for item in self.result_items():
            item.setDisabled(not enabled)

    def set_history(self, runs) -> None:
        """runs: iterable of objects with .id and .title() (project RunRecords)."""
        self._clear_children(self.history_item)
        for record in runs:
            item = QTreeWidgetItem([record.title()])
            item.setData(0, KIND_ROLE, ("history", record.id))
            item.setToolTip(0, f"{record.id} · {record.created_utc}\n"
                               "Double-click to load. Right-click to compare or delete.")
            self.history_item.addChild(item)
        self.history_item.setText(0, f"Saved runs ({self.history_item.childCount()})")

    # ---- queries (also used by tests) ----------------------------------------
    def model_group(self, name: str) -> QTreeWidgetItem | None:
        """The Model section's group item (Materials / Geometry / Settings)."""
        for i in range(self.model_root.childCount()):
            if self.model_root.child(i).text(0) == name:
                return self.model_root.child(i)
        return None

    def model_group_names(self) -> list[str]:
        return [self.model_root.child(i).text(0) for i in range(self.model_root.childCount())]

    def result_items(self) -> list[QTreeWidgetItem]:
        return [self.results_root.child(i) for i in range(self.results_root.childCount())
                if self.results_root.child(i) is not self.history_item]

    def result_scores(self) -> list[str]:
        return [_kind(i)[1] for i in self.result_items()]

    def history_ids(self) -> list[str]:
        return [_kind(self.history_item.child(i))[1]
                for i in range(self.history_item.childCount())]

    def select_result(self, score: str) -> None:
        for item in self.result_items():
            if _kind(item)[1] == score:
                self.setCurrentItem(item)
                return

    def study_ids(self) -> list[str]:
        out = []
        for i in range(self.studies_root.childCount()):
            k = _kind(self.studies_root.child(i))
            if k and k[0] == "study":
                out.append(k[1])
        return out

    def select_study(self, study_id: str) -> None:
        for i in range(self.studies_root.childCount()):
            item = self.studies_root.child(i)
            k = _kind(item)
            if k and k[0] == "study" and k[1] == study_id:
                self.setCurrentItem(item)
                return

    def node_kind(self, item: QTreeWidgetItem) -> tuple[str, object] | None:
        return _kind(item)

    # ---- history context menu -------------------------------------------------
    def _selected_history_ids(self) -> list[str]:
        out = []
        for item in self.selectedItems():
            k = _kind(item)
            if k and k[0] == "history":
                out.append(k[1])
        return out

    def _add_study_menu(self, global_pos) -> None:
        menu = QMenu(self)
        for kind, label in self._addable_kinds:
            menu.addAction(label).setData(kind)
        chosen = menu.exec(global_pos)
        if chosen is not None:
            self.studyAddRequested.emit(chosen.data())

    def _context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        global_pos = self.viewport().mapToGlobal(pos)
        k = _kind(item) if item is not None else None

        if k and k[0] == "add_study":
            self._add_study_menu(global_pos)
            return
        if k and k[0] == "study":                       # a study instance
            menu = QMenu(self)
            rename = menu.addAction("Rename…")
            duplicate = menu.addAction("Duplicate")
            delete = menu.addAction("Delete")
            chosen = menu.exec(global_pos)
            if chosen is rename:
                self.studyRenameRequested.emit(k[1])
            elif chosen is duplicate:
                self.studyDuplicateRequested.emit(k[1])
            elif chosen is delete:
                self.studyDeleteRequested.emit(k[1])
            return

        ids = self._selected_history_ids()
        if not ids:
            return
        menu = QMenu(self)
        load = menu.addAction("Load run")
        load.setEnabled(len(ids) == 1)
        compare = menu.addAction("Compare runs…")
        compare.setEnabled(len(ids) == 2)
        menu.addSeparator()
        delete = menu.addAction(f"Delete {len(ids)} run{'s' if len(ids) != 1 else ''}…")
        chosen = menu.exec(global_pos)
        if chosen is load:
            self.historyLoadRequested.emit(ids[0])
        elif chosen is compare:
            self.historyCompareRequested.emit(ids[0], ids[1])
        elif chosen is delete:
            self.historyDeleteRequested.emit(ids)
