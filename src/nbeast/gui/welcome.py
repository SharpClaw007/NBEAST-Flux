"""The welcome / start screen — shown on launch.

Recent projects, a template gallery with live geometry thumbnails, and example cases,
so the app opens with a choice instead of a cold empty pin cell. Emits an action the
main window applies; a "Show on startup" toggle persists to QSettings.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from nbeast.core import render_geometry, specs

# Template gallery cards: (template, expected-result hint).
_GALLERY = (
    ("Pin cell", "PWR pin cell — k∞ ≈ 1.41"),
    ("Fuel assembly", "N×N fuel assembly"),
    ("Godiva", "Bare HEU sphere — k ≈ 1.0"),
    ("Shield slab", "Fixed-source shielding"),
)
_EXAMPLES = (
    ("Godiva — bare HEU sphere", "godiva"),
    ("PWR pin cell", "pincell"),
    ("7×7 fuel assembly", "assembly"),
    ("Water shield slab", "shield"),
)


def _thumbnail(template: str):
    """A geometry thumbnail QPixmap for a template (default parameters)."""
    from .geometry_view import GeometryView

    spec = specs.SPECS.get(template)
    if spec is None:
        return None
    preview = render_geometry.preview(template, spec.defaults(), spec.material_defaults())
    if preview is None:
        return None
    view = GeometryView()
    view.set_preview(preview, "SI")
    pix = view.render_pixmap(220, 150)
    view.deleteLater()
    return pix


class _Card(QFrame):
    clicked = Signal()

    def __init__(self, title: str, subtitle: str, pixmap):
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(subtitle)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        if pixmap is not None:
            thumb = QLabel()
            thumb.setPixmap(pixmap)
            thumb.setAlignment(Qt.AlignCenter)
            layout.addWidget(thumb)
        name = QLabel(f"<b>{title}</b>")
        sub = QLabel(subtitle)
        sub.setStyleSheet("color:#666;")
        sub.setWordWrap(True)
        layout.addWidget(name)
        layout.addWidget(sub)

    def mousePressEvent(self, _event):  # noqa: N802
        self.clicked.emit()


class WelcomeDialog(QDialog):
    templateChosen = Signal(str)
    exampleChosen = Signal(str)
    projectChosen = Signal(str)     # path
    newProjectRequested = Signal()
    openProjectRequested = Signal()

    def __init__(self, recent_projects: list[str], parent=None, show_startup: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Welcome to NBEAST")
        self.resize(760, 560)
        layout = QVBoxLayout(self)

        heading = QLabel("<h2>NBEAST</h2><span style='color:#666'>neutron-flux Monte Carlo</span>")
        layout.addWidget(heading)

        body = QHBoxLayout()
        layout.addLayout(body, 1)

        # -- left: recent projects + actions --
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Recent projects</b>"))
        self.recent_list = QListWidget()
        for path in recent_projects:
            item = QListWidgetItem(path)
            item.setData(Qt.UserRole, path)
            self.recent_list.addItem(item)
        if not recent_projects:
            self.recent_list.addItem("(none yet)")
            self.recent_list.setEnabled(False)
        self.recent_list.itemDoubleClicked.connect(self._on_recent)
        left.addWidget(self.recent_list, 1)
        open_btn = QPushButton("Open project…")
        open_btn.clicked.connect(self._emit_open)
        new_btn = QPushButton("New project…")
        new_btn.clicked.connect(self._emit_new)
        left.addWidget(open_btn)
        left.addWidget(new_btn)
        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setMaximumWidth(260)
        body.addWidget(left_w)

        # -- right: template gallery --
        right = QVBoxLayout()
        right.addWidget(QLabel("<b>Start from a template</b>"))
        gallery = QGridLayout()
        for i, (template, hint) in enumerate(_GALLERY):
            card = _Card(template, hint, _thumbnail(template))
            card.clicked.connect(lambda t=template: self._choose_template(t))
            gallery.addWidget(card, i // 2, i % 2)
        right.addLayout(gallery)
        right.addWidget(QLabel("<b>Or open an example</b>"))
        ex_row = QHBoxLayout()
        for label, key in _EXAMPLES:
            btn = QPushButton(label)
            btn.setIconSize(QSize(16, 16))
            btn.clicked.connect(lambda _c=False, k=key: self._choose_example(k))
            ex_row.addWidget(btn)
        right.addLayout(ex_row)
        right.addStretch(1)
        body.addLayout(right, 1)

        footer = QHBoxLayout()
        self.show_startup_check = QCheckBox("Show this screen on startup")
        self.show_startup_check.setChecked(show_startup)
        footer.addWidget(self.show_startup_check)
        footer.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        footer.addWidget(close_btn)
        layout.addLayout(footer)

    @property
    def show_on_startup(self) -> bool:
        return self.show_startup_check.isChecked()

    def _choose_template(self, template: str) -> None:
        self.templateChosen.emit(template)
        self.accept()

    def _choose_example(self, key: str) -> None:
        self.exampleChosen.emit(key)
        self.accept()

    def _on_recent(self, item) -> None:
        path = item.data(Qt.UserRole)
        if path:
            self.projectChosen.emit(path)
            self.accept()

    def _emit_open(self) -> None:
        self.openProjectRequested.emit()
        self.accept()

    def _emit_new(self) -> None:
        self.newProjectRequested.emit()
        self.accept()
