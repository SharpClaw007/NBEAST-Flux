"""Cross-section data manager dialog.

Pick a library + elements/nuclides (or a preset), download them into the user
data directory (seeded from the bundled library so it stays a superset), and make
the result the active library. The download runs off the UI thread.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from nbeast.core import data

CUSTOM = "Custom…"


def _split_tokens(text: str) -> tuple[list[str], list[str]]:
    """Split 'U O Pu239' into (elements, nuclides) by presence of a digit."""
    tokens = text.split()
    elements = [t for t in tokens if not any(c.isdigit() for c in t)]
    nuclides = [t for t in tokens if any(c.isdigit() for c in t)]
    return elements, nuclides


class _DownloadWorker(QObject):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, active_xml, user_dir, library, elements, nuclides, sab):
        super().__init__()
        self._args = (active_xml, user_dir, library, elements, nuclides, sab)

    @Slot()
    def run(self):
        active_xml, user_dir, library, elements, nuclides, sab = self._args
        try:
            if active_xml:
                data.seed_from(active_xml, user_dir)
            xml = data.download(user_dir, library, elements, nuclides, sab)
            self.done.emit(str(xml))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class DataManagerDialog(QDialog):
    activated = Signal(str)  # emitted with the new cross_sections.xml path

    def __init__(self, active_xml: str | None = None, parent=None, prefill=None):
        super().__init__(parent)
        self.setWindowTitle("Cross-section data")
        self.resize(560, 320)
        self._active_xml = active_xml
        self._user_dir = data.default_data_dir()
        self._thread = None
        self._worker = None
        self._prefill = prefill  # optional (elements, sab) for a targeted per-material fetch

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Download more nuclear data on demand. Downloads add to your library and "
            "become active; the bundled set remains as a fallback."
        ))

        form = QFormLayout()
        self.library_combo = QComboBox()
        self.library_combo.addItems(data.LIBRARIES)
        form.addRow("Library:", self.library_combo)

        self.preset_combo = QComboBox()
        self.preset_combo.addItems([*data.PRESETS.keys(), CUSTOM])
        self.preset_combo.currentTextChanged.connect(self._apply_preset)
        form.addRow("Preset:", self.preset_combo)

        self.elements_edit = QLineEdit()
        self.elements_edit.setPlaceholderText("e.g.  U O H Zr  or  Pu239 Gd155")
        form.addRow("Elements / nuclides:", self.elements_edit)

        self.sab_edit = QLineEdit()
        self.sab_edit.setPlaceholderText("e.g.  c_H_in_H2O")
        form.addRow("Thermal scattering S(α,β):", self.sab_edit)
        layout.addLayout(form)

        self.status = QLabel(f"Active library: {active_xml or '(none)'}\nDownloads to: {self._user_dir}")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #555;")
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.download_button = QPushButton("Download && activate")
        self.download_button.clicked.connect(self._start_download)
        buttons.addWidget(self.download_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self._apply_preset(self.preset_combo.currentText())
        if self._prefill:
            self._apply_prefill(self._prefill)

    def _apply_prefill(self, prefill) -> None:
        """Pre-populate the fields with a specific material's missing data."""
        elements, sab = prefill
        self.preset_combo.setCurrentText(CUSTOM)
        self.elements_edit.setText(" ".join(elements))
        self.sab_edit.setText(" ".join(sab))
        need = ", ".join([*elements, *sab]) or "nothing — already available"
        self.status.setText(
            f"Ready to download this material's data: {need}\nDownloads to: {self._user_dir}"
        )

    def _apply_preset(self, name: str) -> None:
        if name == CUSTOM:
            return
        preset = data.PRESETS.get(name, {})
        self.elements_edit.setText(" ".join(preset.get("elements", [])))
        self.sab_edit.setText(" ".join(preset.get("sab", [])))

    def _start_download(self) -> None:
        elements, nuclides = _split_tokens(self.elements_edit.text())
        sab = self.sab_edit.text().split()
        if not (elements or nuclides or sab):
            self.status.setText("Nothing selected to download.")
            return

        self.download_button.setEnabled(False)
        self.status.setText("Downloading… (this can take a while for large selections)")

        self._thread = QThread()
        self._worker = _DownloadWorker(
            self._active_xml, str(self._user_dir),
            self.library_combo.currentText(), elements, nuclides, sab,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    def _teardown(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None

    @Slot(str)
    def _on_done(self, xml: str) -> None:
        self._teardown()
        self._active_xml = xml
        self.download_button.setEnabled(True)
        self.status.setText(f"Done. Active library:\n{xml}")
        self.activated.emit(xml)

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._teardown()
        self.download_button.setEnabled(True)
        self.status.setText(f"Download failed: {message}")
