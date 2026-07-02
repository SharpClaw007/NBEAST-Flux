"""GUI layer for persistent studies: a project-backed store + a config/results pane.

* :class:`StudyStore` — CRUD over the project's ``studies`` list (v2 schema), so study
  instances + their last results survive close/reopen.
* :class:`StudyPane` — the settings-pane view for a selected study: a generic config
  form built from :data:`nbeast.core.studies.STUDY_KINDS`, a Run button, and the last
  result summary (with a re-load button for k-eff studies). The main window supplies
  the run + reload callbacks so this stays UI-only.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from nbeast.core import studies as core_studies
from nbeast.core.studies import StudyConfig, StudyResult


class StudyStore:
    """Persistent study instances, backed by ``project.studies`` (list of dicts)."""

    def __init__(self, project):
        self.project = project

    def _entries(self) -> list[dict]:
        return self.project.studies

    def configs(self) -> list[StudyConfig]:
        return [StudyConfig.from_dict(e.get("config", {})) for e in self._entries()]

    def names(self) -> list[str]:
        return [c.name for c in self.configs()]

    def _next_id(self) -> str:
        used = {e.get("config", {}).get("study_id", "") for e in self._entries()}
        n = 1
        while f"study-{n:03d}" in used:
            n += 1
        return f"study-{n:03d}"

    def add(self, kind: str, quality: dict, params: dict | None = None) -> StudyConfig:
        config = StudyConfig(
            kind=kind, name=core_studies.default_name(kind, self.names()),
            params=dict(params or {}), quality=dict(quality), study_id=self._next_id())
        self._entries().append({"config": config.to_dict(), "result": None})
        self.project.save()
        return config

    def _find(self, study_id: str) -> dict | None:
        return next((e for e in self._entries()
                     if e.get("config", {}).get("study_id") == study_id), None)

    def get(self, study_id: str) -> StudyConfig | None:
        entry = self._find(study_id)
        return StudyConfig.from_dict(entry["config"]) if entry else None

    def update(self, config: StudyConfig) -> None:
        entry = self._find(config.study_id)
        if entry is not None:
            entry["config"] = config.to_dict()
            self.project.save()

    def rename(self, study_id: str, name: str) -> None:
        entry = self._find(study_id)
        if entry is not None:
            entry["config"]["name"] = name
            self.project.save()

    def duplicate(self, study_id: str) -> StudyConfig | None:
        src = self.get(study_id)
        if src is None:
            return None
        return self.add(src.kind, src.quality, src.params)

    def delete(self, study_id: str) -> None:
        entry = self._find(study_id)
        if entry is not None:
            self._entries().remove(entry)
            self.project.save()

    def set_result(self, study_id: str, result: StudyResult) -> None:
        entry = self._find(study_id)
        if entry is not None:
            entry["result"] = result.to_dict()
            self.project.save()

    def get_result(self, study_id: str) -> StudyResult | None:
        entry = self._find(study_id)
        data = entry.get("result") if entry else None
        return StudyResult.from_dict(data) if data else None


class StudyPane(QWidget):
    """Config form + Run + last-result summary for one study (lives in the settings pane)."""

    runRequested = Signal(str)      # study_id
    loadRequested = Signal(str)     # study_id (reload a k-eff study's saved run)

    def __init__(self, store: StudyStore, parent=None):
        super().__init__(parent)
        self._store = store
        self._config: StudyConfig | None = None
        self._param_choices: list[tuple[str, str]] = []   # (key, label) for "param" fields
        self._editors: dict = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._summary = QLabel(core_studies.STUDY_KINDS["keff"].summary)
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet("color:#666;")
        layout.addWidget(self._summary)

        self._form = QFormLayout()
        layout.addLayout(self._form)

        buttons = QHBoxLayout()
        self._run_btn = QPushButton("▶ Run study")
        self._run_btn.clicked.connect(self._on_run)
        self._load_btn = QPushButton("Load saved run")
        self._load_btn.clicked.connect(self._on_load)
        self._load_btn.hide()
        buttons.addWidget(self._run_btn)
        buttons.addWidget(self._load_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._result = QLabel("")
        self._result.setWordWrap(True)
        self._result.setTextFormat(Qt.RichText)
        layout.addWidget(self._result)
        layout.addStretch(1)

    def set_param_choices(self, choices: list[tuple[str, str]]) -> None:
        self._param_choices = choices

    def show_study(self, config: StudyConfig) -> None:
        self._config = config
        spec = config.spec
        self._summary.setText(spec.summary if spec else "")
        self._clear_form()
        self._editors = {}
        for field in (spec.fields if spec else ()):
            editor = self._make_editor(field, config.params.get(field.key, field.default))
            if editor is not None:
                self._editors[field.key] = editor
                self._form.addRow(field.label + ":", editor)
                editor.setToolTip(field.help)
        self._load_btn.setVisible(config.kind == "keff")
        self._show_result(self._store.get_result(config.study_id))

    # ---- form -----------------------------------------------------------------
    def _clear_form(self) -> None:
        while self._form.rowCount():
            self._form.removeRow(0)

    def _make_editor(self, field, value):
        if field.kind == "int":
            w = QSpinBox()
            w.setRange(int(field.minimum), int(field.maximum))
            w.setValue(int(value if value is not None else field.default or 0))
            return w
        if field.kind == "float":
            w = QDoubleSpinBox()
            w.setDecimals(4)
            w.setRange(field.minimum, field.maximum)
            w.setValue(float(value if value is not None else field.default or 0.0))
            return w
        if field.kind == "choice":
            w = QComboBox()
            w.addItems([str(c) for c in field.choices])
            if value is not None and str(value) in [str(c) for c in field.choices]:
                w.setCurrentText(str(value))
            return w
        if field.kind == "param":
            w = QComboBox()
            for key, label in self._param_choices:
                w.addItem(label, key)
            if value is not None:
                idx = w.findData(value)
                if idx >= 0:
                    w.setCurrentIndex(idx)
            return w
        return None

    def current_params(self) -> dict:
        """Read the form back into a params dict."""
        out = {}
        spec = self._config.spec if self._config else None
        for field in (spec.fields if spec else ()):
            editor = self._editors.get(field.key)
            if editor is None:
                continue
            if field.kind in ("int", "float"):
                out[field.key] = editor.value()
            elif field.kind == "param":
                out[field.key] = editor.currentData()
            else:
                out[field.key] = editor.currentText()
        return out

    # ---- result ----------------------------------------------------------------
    def _show_result(self, result: StudyResult | None) -> None:
        if result is None:
            self._result.setText("<i>Not run yet.</i>")
            return
        badge = "✅" if result.ok else "⚠"
        warn = ("<br><span style='color:#a60'>"
                + "<br>".join(result.warnings) + "</span>") if result.warnings else ""
        stamp = f"<br><span style='color:#999'>{result.created_utc}</span>" if result.created_utc else ""
        self._result.setText(f"{badge} {result.summary}{warn}{stamp}")

    def refresh_result(self) -> None:
        if self._config is not None:
            self._show_result(self._store.get_result(self._config.study_id))

    def _persist_params(self) -> None:
        if self._config is not None:
            self._config.params = self.current_params()
            self._store.update(self._config)

    def _on_run(self) -> None:
        if self._config is not None:
            self._persist_params()
            self.runRequested.emit(self._config.study_id)

    def _on_load(self) -> None:
        if self._config is not None:
            self.loadRequested.emit(self._config.study_id)
