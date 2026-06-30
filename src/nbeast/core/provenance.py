"""Capture the provenance of a run so it can be reproduced and trusted.

A Monte Carlo result is only citable if you can say *exactly* how it was produced:
which code version, which nuclear data, which parameters, which RNG seed. This
module gathers that into a :class:`RunMetadata` record that is written next to the
exported deck (``provenance.json``) and summarised in the report.
"""

from __future__ import annotations

import platform as _platform
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import openmc


def _data_library_label(cross_sections: str | None) -> str | None:
    """Best-effort human label for the nuclear-data library from its path."""
    if not cross_sections:
        return None
    p = Path(cross_sections)
    # …/endfb-viii.0-hdf5/cross_sections.xml -> "endfb-viii.0-hdf5"
    return p.parent.name or str(p)


@dataclass
class RunMetadata:
    nbeast_version: str
    openmc_version: str
    created_utc: str
    platform: str
    machine: str
    template: str | None = None
    parameters: dict = field(default_factory=dict)
    batches: int | None = None
    inactive: int | None = None
    particles: int | None = None
    seed: int | None = None
    temperature: float | None = None
    threads: str | None = None
    cross_sections: str | None = None
    data_library: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: str | Path) -> Path:
        import json

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=False))
        return path

    def summary_lines(self) -> list[str]:
        """Compact provenance block for the report / about box."""
        lines = [
            f"NBEAST {self.nbeast_version} · OpenMC {self.openmc_version}",
            f"run {self.created_utc}",
            f"data: {self.data_library or 'unknown'}",
        ]
        if self.seed is not None:
            lines.append(f"RNG seed: {self.seed} (reproducible)")
        else:
            lines.append("RNG seed: OpenMC default")
        if self.machine:
            lines.append(f"host: {self.machine}")
        return lines


def capture(
    *,
    template: str | None = None,
    parameters: dict | None = None,
    model: openmc.model.Model | None = None,
    cross_sections: str | None = None,
    threads: str | None = None,
    now: datetime | None = None,
) -> RunMetadata:
    """Snapshot the current environment + run settings into a RunMetadata record.

    Settings (batches/inactive/particles/seed) are read from ``model`` when given;
    ``cross_sections`` falls back to OpenMC's configured library.
    """
    from nbeast import __version__ as nbeast_version

    if cross_sections is None:
        try:
            cross_sections = str(openmc.config.get("cross_sections") or "") or None
        except Exception:  # noqa: BLE001
            cross_sections = None

    batches = inactive = particles = seed = temperature = None
    if model is not None and model.settings is not None:
        s = model.settings
        batches = getattr(s, "batches", None)
        inactive = getattr(s, "inactive", None)
        particles = getattr(s, "particles", None)
        seed = getattr(s, "seed", None)
        temp = getattr(s, "temperature", None)
        if isinstance(temp, dict):
            temperature = temp.get("default")

    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return RunMetadata(
        nbeast_version=nbeast_version,
        openmc_version=openmc.__version__,
        created_utc=stamp,
        platform=_platform.platform(),
        machine=_platform.machine(),
        template=template,
        parameters=dict(parameters or {}),
        batches=batches,
        inactive=inactive,
        particles=particles,
        seed=seed,
        temperature=temperature,
        threads=threads,
        cross_sections=cross_sections,
        data_library=_data_library_label(cross_sections),
    )
