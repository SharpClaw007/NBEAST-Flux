"""Small shared UI helpers.

``make_selectable`` makes a status/result label's text selectable + copyable (⌘C,
right-click) — errors and results should never be un-copyable. ``CopyableListWidget``
is a list whose rows copy to the clipboard (used by the Messages strip and anywhere a
scrollable log is shown).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QMenu

_SELECTABLE = Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard | Qt.LinksAccessibleByMouse


def make_selectable(label: QLabel) -> QLabel:
    """Let the user select + copy a label's text (e.g. an error message)."""
    label.setTextInteractionFlags(_SELECTABLE)
    label.setCursor(Qt.IBeamCursor)
    return label


class CopyableListWidget(QListWidget):
    """A list whose selected rows (or all rows) copy to the clipboard via ⌘C or a
    right-click menu — so a run log / error trace is never trapped on screen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)

    def keyPressEvent(self, event):  # noqa: N802
        if event.matches(QKeySequence.Copy):
            self.copy_selected()
            return
        super().keyPressEvent(event)

    def _text_of(self, items) -> str:
        return "\n".join(i.text() for i in items)

    def copy_selected(self) -> None:
        items = self.selectedItems() or [self.item(i) for i in range(self.count())]
        text = self._text_of(items)
        if text:
            QApplication.clipboard().setText(text)

    def copy_all(self) -> None:
        text = self._text_of([self.item(i) for i in range(self.count())])
        if text:
            QApplication.clipboard().setText(text)

    def _context_menu(self, pos) -> None:
        menu = QMenu(self)
        copy = menu.addAction("Copy")
        copy.setEnabled(bool(self.selectedItems()))
        copy_all = menu.addAction("Copy all")
        copy_all.setEnabled(self.count() > 0)
        chosen = menu.exec(self.viewport().mapToGlobal(pos))
        if chosen is copy:
            self.copy_selected()
        elif chosen is copy_all:
            self.copy_all()
