"""The messages strip — run log + progress under the viewport.

Commercial CAE tools keep a persistent, scrollable message area instead of a
one-line status bar: progress you can watch, warnings that don't vanish after five
seconds, and a run log you can copy. The strip is collapsible (header always
visible); the main window mirrors its status-bar traffic here via ``log()``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

_MAX_LINES = 500


class MessagesStrip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(6, 2, 6, 2)
        self.toggle = QToolButton()
        self.toggle.setText("Messages")
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.DownArrow)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.setAutoRaise(True)
        self.toggle.toggled.connect(self._on_toggled)
        header.addWidget(self.toggle)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(260)
        self.progress.setTextVisible(True)
        self.progress.hide()
        header.addWidget(self.progress)
        self.progress_label = QLabel("")
        header.addWidget(self.progress_label)
        header.addStretch(1)
        layout.addLayout(header)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.setMaximumHeight(130)
        layout.addWidget(self.list)

    # ---- log ------------------------------------------------------------------
    def log(self, text: str, level: str = "info") -> None:
        if not text:
            return
        item = QListWidgetItem(("⚠ " if level == "warning" else
                                "✖ " if level == "error" else "") + text)
        if level == "error":
            item.setForeground(Qt.red)
        self.list.addItem(item)
        while self.list.count() > _MAX_LINES:
            self.list.takeItem(0)
        self.list.scrollToBottom()

    # ---- progress ---------------------------------------------------------------
    def start_progress(self, total: int, label: str = "") -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(0)
        self.progress.show()
        self.progress_label.setText(label)

    def set_progress(self, value: int, label: str = "") -> None:
        self.progress.setValue(value)
        if label:
            self.progress_label.setText(label)

    def clear_progress(self) -> None:
        self.progress.hide()
        self.progress_label.setText("")

    # ---- collapse ------------------------------------------------------------------
    def _on_toggled(self, expanded: bool) -> None:
        self.list.setVisible(expanded)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
