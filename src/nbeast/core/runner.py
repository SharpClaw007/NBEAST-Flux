"""Drive OpenMC in an isolated subprocess and stream results to callbacks.

This is the engine API the GUI binds to. ``run()`` blocks the calling thread and
invokes callbacks per batch — the GUI runs it on a worker thread and calls
``cancel()`` from the UI thread (e.g. a Stop button); ``terminate()`` is
thread-safe. Crash isolation: a transport failure kills the subprocess, not the app.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import openmc


@dataclass
class BatchUpdate:
    batch: int
    keff: float | None              # None for a fixed-source run
    keff_std: float | None
    entropy: float | None = None  # Shannon entropy of the fission source (live)


@dataclass
class RunResult:
    keff: float | None = None
    keff_std: float | None = None
    statepoint: str | None = None
    batches: list[BatchUpdate] = field(default_factory=list)
    cancelled: bool = False
    error: str | None = None


def _write_entropy_mesh(model: openmc.model.Model, run_dir: Path) -> None:
    """Drop the entropy mesh bounds where the worker can find them, so it can
    compute Shannon entropy live (openmc.lib does not expose it directly)."""
    mesh = getattr(model.settings, "entropy_mesh", None)
    if mesh is None:
        return
    try:
        spec = {
            "lower_left": [float(v) for v in mesh.lower_left],
            "upper_right": [float(v) for v in mesh.upper_right],
            "dimension": [int(d) for d in mesh.dimension],
        }
        (run_dir / "entropy_mesh.json").write_text(json.dumps(spec))
    except Exception:  # noqa: BLE001 — live entropy is best-effort, never fatal
        pass


def _write_run_meta(model: openmc.model.Model, run_dir: Path) -> None:
    """Tell the worker the run mode so it knows whether to report k-effective."""
    run_mode = getattr(model.settings, "run_mode", "eigenvalue") or "eigenvalue"
    try:
        (run_dir / "run_meta.json").write_text(json.dumps({"run_mode": run_mode}))
    except Exception:  # noqa: BLE001
        pass


class Runner:
    """Launches the worker subprocess and dispatches its JSON event stream."""

    def __init__(self, cross_sections: str | None = None):
        self._cross_sections = cross_sections
        self._proc: subprocess.Popen | None = None

    def run(
        self,
        model: openmc.model.Model,
        run_dir: str | Path,
        *,
        on_start: Callable[[int | None], None] | None = None,
        on_batch: Callable[[BatchUpdate], None] | None = None,
    ) -> RunResult:
        run_dir = Path(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        model.export_to_model_xml(str(run_dir / "model.xml"))
        n_batches = model.settings.batches
        _write_entropy_mesh(model, run_dir)
        _write_run_meta(model, run_dir)

        env = dict(os.environ)
        env["FI_PROVIDER"] = "tcp"
        if self._cross_sections:
            env["OPENMC_CROSS_SECTIONS"] = self._cross_sections

        self._proc = subprocess.Popen(
            [sys.executable, "-m", "nbeast.core.worker", str(run_dir), str(n_batches)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )

        result = RunResult()
        assert self._proc.stderr is not None
        for line in self._proc.stderr:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # stray non-JSON (e.g. a warning leaked to stderr)
            kind = msg.get("type")
            if kind == "start":
                if on_start:
                    on_start(msg.get("batches"))
            elif kind == "batch":
                update = BatchUpdate(
                    msg["batch"], msg.get("keff"), msg.get("keff_std"), msg.get("entropy")
                )
                result.batches.append(update)
                if on_batch:
                    on_batch(update)
            elif kind == "cancelled":
                result.cancelled = True
            elif kind == "done":
                result.keff = msg.get("keff")
                result.keff_std = msg.get("keff_std")
                result.statepoint = msg.get("statepoint")
            elif kind == "error":
                result.error = msg.get("message")

        self._proc.wait()
        self._proc = None
        return result

    def cancel(self) -> None:
        """Request a clean stop (SIGTERM). Safe to call from another thread."""
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
