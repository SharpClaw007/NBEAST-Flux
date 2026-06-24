"""CAD support setup dialog (Phase 6, Stage F).

Shown from File ▸ Set up CAD geometry support… when the DAGMC envs are absent.
Downloads the published channel and creates the two native-arm64 conda envs the
CAD feature needs, streaming progress off the UI thread.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from nbeast.core import cad


class _SetupWorker(QObject):
    line = Signal(str)
    done = Signal()
    failed = Signal(str)

    @Slot()
    def run(self):
        try:
            cad.setup_support(on_line=self.line.emit)
            self.done.emit()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class CadSetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set up CAD geometry support")
        self.resize(640, 440)
        self._thread = None
        self._worker = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "This downloads the native Apple-Silicon CAD channel and creates two conda "
            "environments (cad_to_dagmc + dagmc-OpenMC). It needs internet and a few "
            "minutes. NBEAST enables CAD import once they exist."
        ))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, 1)

        self.buttons = QDialogButtonBox()
        self.install_btn = QPushButton("Install CAD support")
        self.install_btn.clicked.connect(self._start)
        self.buttons.addButton(self.install_btn, QDialogButtonBox.AcceptRole)
        self.buttons.addButton(QDialogButtonBox.Close)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _append(self, text: str) -> None:
        self.log.appendPlainText(text)

    def _start(self) -> None:
        self.install_btn.setEnabled(False)
        self._append("Starting CAD support setup…")
        self._thread = QThread()
        self._worker = _SetupWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.line.connect(self._append)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    def _teardown(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._thread = self._worker = None

    @Slot()
    def _on_done(self) -> None:
        self._teardown()
        self._append("\n✓ CAD support installed. Reopen NBEAST to use File ▸ Import CAD geometry.")

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._teardown()
        self.install_btn.setEnabled(True)
        self._append(f"\n✗ Setup failed: {message}")
