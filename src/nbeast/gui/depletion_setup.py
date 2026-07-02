"""Depletion setup guide — shown when the burnup data isn't configured.

Depletion needs data NBEAST does not bundle (its offline library is a criticality
library): a depletion *chain* file and a *depletion-capable* cross-section library.
This dialog explains how to obtain them and lets the user point NBEAST at a chain
file they have downloaded, which enables the feature.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from .uikit import make_selectable

from nbeast.core import depletion

_GUIDE = (
    "<b>Depletion / burnup is an optional add-on.</b><br><br>"
    "It tracks how the fuel composition and reactivity evolve as fuel burns. Because "
    "it produces hundreds of fission products and actinides, it needs data beyond "
    "NBEAST's curated criticality bundle:<br><br>"
    "<b>1. A depletion chain file</b> (decay + transmutation data). Reduced chains are "
    "published by the OpenMC project at "
    "<a href='https://github.com/openmc-dev/data/tree/master/depletion'>"
    "github.com/openmc-dev/data</a> "
    "(e.g. <tt>chain_casl_thermal.xml</tt> for LWRs, <tt>chain_casl_fast.xml</tt> for "
    "fast systems). Download one and select it below.<br><br>"
    "<b>2. A depletion-capable cross-section library</b> — one with cross sections for "
    "the fission products and actinides the chain produces (e.g. the full ENDF/B-VIII.0 "
    "library). Activate it from <i>File ▸ Data library…</i>.<br><br>"
    "Once a chain is selected and an adequate library is active, "
    "<i>Analysis ▸ Depletion / burnup…</i> runs a real burnup calculation.<br><br>"
    "⚠ <b>The workflow is validated; the burnup numbers are not benchmarked.</b> NBEAST "
    "has not validated k-vs-burnup or inventories against a depletion benchmark — treat "
    "results as exploratory."
)


class DepletionSetupDialog(QDialog):
    configured = Signal()  # emitted when a chain is selected

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set up depletion / burnup")
        self.resize(620, 460)

        layout = QVBoxLayout(self)
        guide = QLabel(_GUIDE)
        guide.setWordWrap(True)
        guide.setOpenExternalLinks(True)
        layout.addWidget(guide)

        self.status = QLabel(self._status_text())
        make_selectable(self.status)
        self.status.setStyleSheet("color: #555; padding: 4px;")
        layout.addWidget(self.status)

        select_btn = QPushButton("Select depletion chain file…")
        select_btn.clicked.connect(self._select_chain)
        layout.addWidget(select_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _status_text(self) -> str:
        cp = depletion.chain_path()
        if cp:
            ok = "✓ ready" if depletion.is_available() else "(file not found)"
            return f"Current chain: {cp}  {ok}"
        return "No depletion chain configured yet."

    def _select_chain(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select depletion chain XML", "", "Chain files (*.xml);;All files (*)"
        )
        if not path:
            return
        os.environ["OPENMC_DEPLETION_CHAIN"] = path
        try:
            import openmc

            openmc.config["chain_file"] = path
        except Exception:  # noqa: BLE001
            pass
        self.status.setText(self._status_text())
        if depletion.is_available():
            self.configured.emit()