"""A persistent NBEAST project: the model state plus a history of runs.

Today every session is an ephemeral temp directory — close the app and the runs
are gone. A :class:`Project` makes the work durable and shareable: it is a plain
*directory* containing a ``project.json`` manifest and a ``runs/`` subfolder, one
archived statepoint per run. Reopening a project restores the last-edited template,
its parameters, and run settings, and re-lists every run with its k-effective so a
researcher can revisit, compare, or export any of them later.

The format is deliberately a directory rather than a single bundle: OpenMC
statepoints are large binary HDF5 files, and a directory lets the OS (and the user)
manage them without NBEAST round-tripping megabytes through JSON.

This module is Qt-free and OpenMC-free — it only moves files and (de)serialises a
manifest, so it is fully unit-testable without a display or nuclear data.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

PROJECT_VERSION = 1
_MANIFEST = "project.json"
_RUNS_DIR = "runs"
_STATEPOINT_NAME = "statepoint.h5"
_MODEL_NAME = "model.xml"
_RUN_ID_RE = re.compile(r"run-(\d+)")


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class RunRecord:
    """One archived run: enough metadata to list, reload, compare, and cite it."""

    id: str
    template: str
    parameters: dict = field(default_factory=dict)
    batches: int | None = None
    inactive: int | None = None
    particles: int | None = None
    seed: int | None = None
    keff: float | None = None
    keff_std: float | None = None
    created_utc: str = ""
    statepoint: str | None = None       # path relative to the project directory
    label: str = ""
    warnings: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RunRecord":
        known = {f for f in cls.__dataclass_fields__}  # tolerate older/newer keys
        return cls(**{k: v for k, v in data.items() if k in known})

    @property
    def keff_pcm(self) -> float | None:
        return None if self.keff_std is None else self.keff_std * 1.0e5

    def title(self) -> str:
        """A short human label for the history list."""
        if self.label:
            return self.label
        k = f"k={self.keff:.5f}" if self.keff is not None else "k=n/a"
        return f"{self.template} · {k}"


class Project:
    """A directory-backed project: model state + a run history that persists.

    Mutating operations (:meth:`add_run`, :meth:`delete_run`, :meth:`update_state`)
    save the manifest immediately, so a crash never loses recorded history.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.name: str = self.path.name
        self.created_utc: str = _utcnow()
        self.template: str | None = None
        self.param_values: dict[str, dict] = {}
        self.settings: dict = {}            # batches / particles / seed (last used)
        self.runs: list[RunRecord] = []

    # ---- construction -----------------------------------------------------
    @property
    def manifest_path(self) -> Path:
        return self.path / _MANIFEST

    @property
    def runs_dir(self) -> Path:
        return self.path / _RUNS_DIR

    @classmethod
    def create(cls, path: str | Path, name: str | None = None) -> "Project":
        proj = cls(path)
        if name:
            proj.name = name
        proj.path.mkdir(parents=True, exist_ok=True)
        proj.runs_dir.mkdir(exist_ok=True)
        proj.save()
        return proj

    @classmethod
    def open(cls, path: str | Path) -> "Project":
        path = Path(path)
        manifest = path / _MANIFEST
        if not manifest.exists():
            raise FileNotFoundError(f"No NBEAST project at {path} (missing {_MANIFEST})")
        data = json.loads(manifest.read_text())
        proj = cls(path)
        proj.name = data.get("name", path.name)
        proj.created_utc = data.get("created_utc", proj.created_utc)
        proj.template = data.get("template")
        proj.param_values = data.get("param_values", {}) or {}
        proj.settings = data.get("settings", {}) or {}
        proj.runs = [RunRecord.from_dict(r) for r in data.get("runs", [])]
        return proj

    @classmethod
    def open_or_create(cls, path: str | Path, name: str | None = None) -> "Project":
        path = Path(path)
        if (path / _MANIFEST).exists():
            return cls.open(path)
        return cls.create(path, name=name)

    # ---- persistence ------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "nbeast_project_version": PROJECT_VERSION,
            "name": self.name,
            "created_utc": self.created_utc,
            "template": self.template,
            "param_values": self.param_values,
            "settings": self.settings,
            "runs": [r.to_dict() for r in self.runs],
        }

    def save(self) -> Path:
        self.path.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=False))
        return self.manifest_path

    def update_state(
        self,
        *,
        template: str | None = None,
        param_values: dict[str, dict] | None = None,
        settings: dict | None = None,
    ) -> None:
        """Record the current editor state (last template/params/settings) and save."""
        if template is not None:
            self.template = template
        if param_values is not None:
            self.param_values = {k: dict(v) for k, v in param_values.items()}
        if settings is not None:
            self.settings = dict(settings)
        self.save()

    # ---- run history ------------------------------------------------------
    def _next_run_id(self) -> str:
        used = []
        for r in self.runs:
            m = _RUN_ID_RE.fullmatch(r.id or "")
            if m:
                used.append(int(m.group(1)))
        return f"run-{(max(used) + 1) if used else 1:04d}"

    def add_run(
        self,
        *,
        statepoint_src: str | Path,
        template: str,
        parameters: dict,
        batches: int | None = None,
        inactive: int | None = None,
        particles: int | None = None,
        seed: int | None = None,
        keff: float | None = None,
        keff_std: float | None = None,
        warnings: list[str] | None = None,
        provenance: dict | None = None,
        label: str = "",
        model_xml_src: str | Path | None = None,
    ) -> RunRecord:
        """Archive a finished run into the project and return its record.

        The statepoint (and, when given, the ``model.xml`` deck) is *copied* into
        ``runs/<id>/`` so the archive is self-contained and survives deletion of the
        original temp run directory.
        """
        run_id = self._next_run_id()
        dest_dir = self.runs_dir / run_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        statepoint_src = Path(statepoint_src)
        dest_sp = dest_dir / _STATEPOINT_NAME
        shutil.copy2(statepoint_src, dest_sp)
        if model_xml_src is not None and Path(model_xml_src).exists():
            shutil.copy2(model_xml_src, dest_dir / _MODEL_NAME)

        record = RunRecord(
            id=run_id,
            template=template,
            parameters=dict(parameters),
            batches=batches,
            inactive=inactive,
            particles=particles,
            seed=seed,
            keff=keff,
            keff_std=keff_std,
            created_utc=_utcnow(),
            statepoint=str(dest_sp.relative_to(self.path)),
            label=label,
            warnings=list(warnings or []),
            provenance=dict(provenance or {}),
        )
        self.runs.append(record)
        self.save()
        return record

    def statepoint_path(self, record: RunRecord) -> Path | None:
        """Absolute path to a record's archived statepoint, or None if unset."""
        if not record.statepoint:
            return None
        return self.path / record.statepoint

    def get_run(self, run_id: str) -> RunRecord | None:
        return next((r for r in self.runs if r.id == run_id), None)

    def delete_run(self, run_id: str) -> bool:
        record = self.get_run(run_id)
        if record is None:
            return False
        self.runs.remove(record)
        run_dir = self.runs_dir / run_id
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)
        self.save()
        return True
