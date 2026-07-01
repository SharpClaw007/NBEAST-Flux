"""Analysis tools panel — a button per tool (sweep, moderation, poisoning, multigroup,
depletion), enabled for the templates each one applies to. Lives as a tab beside
Results + Run history so the tools sit with the rest of the output, not in a menu.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

# (key, button label, one-line description used as the tooltip)
ANALYSES = (
    ("sweep", "Parameter sweep / criticality search",
     "Vary one parameter over a range, or search for the value that makes k = target."),
    ("moderation", "Moderation / reactivity curve",
     "k-eff, reactivity, and source-driven power from voided to flooded moderator."),
    ("poisoning", "Reactor poisoning (Xe-135 / Sm-149)",
     "Equilibrium xenon + samarium reactivity worth (needs Xe/Sm data)."),
    ("mgxs", "Multigroup constants",
     "Collapse the run into few-group cross sections for a diffusion code."),
    ("depletion", "Depletion / burnup",
     "Track k-effective and nuclide inventory as the fuel burns (needs data)."),
)


class AnalysisPanel(QWidget):
    def __init__(self, callbacks: dict, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        intro = QLabel("Analysis tools — each runs on the current model.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #555;")
        layout.addWidget(intro)

        self._buttons: dict[str, QPushButton] = {}
        self._tips: dict[str, str] = {}
        for key, label, desc in ANALYSES:
            button = QPushButton(label)
            button.setToolTip(desc)
            button.setStyleSheet("text-align: left; padding: 6px;")
            button.clicked.connect(callbacks[key])
            layout.addWidget(button)
            self._buttons[key] = button
            self._tips[key] = desc
        layout.addStretch(1)

    def set_enabled(self, key: str, ok: bool, reason: str = "") -> None:
        """Enable/disable a tool; a disabled tool's tooltip explains why."""
        button = self._buttons.get(key)
        if button is None:
            return
        button.setEnabled(ok)
        button.setToolTip(self._tips[key] if ok or not reason else reason)
