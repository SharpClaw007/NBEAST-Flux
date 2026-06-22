"""Run OpenMC off the GUI thread and surface progress as Qt signals.

A worker QObject (moved to a QThread) calls ``nbeast.core.Runner.run``; its
per-batch callback emits a Qt signal that is delivered (queued) to the GUI
thread. ``cancel()`` is called from the GUI thread and is thread-safe (it just
SIGTERMs the OpenMC subprocess).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot

from nbeast.core.runner import Runner


class _Worker(QObject):
    started = Signal(int)
    batch = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, model, run_dir: str, cross_sections: str | None):
        super().__init__()
        self._model = model
        self._run_dir = run_dir
        self._runner = Runner(cross_sections=cross_sections)

    @Slot()
    def run(self) -> None:
        try:
            result = self._runner.run(
                self._model,
                self._run_dir,
                on_start=lambda n: self.started.emit(n or 0),
                on_batch=lambda u: self.batch.emit(u),
            )
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))

    def cancel(self) -> None:
        self._runner.cancel()


class RunController(QObject):
    started = Signal(int)
    batch = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, cross_sections: str | None = None, parent=None):
        super().__init__(parent)
        self._cross_sections = cross_sections
        self._thread: QThread | None = None
        self._worker: _Worker | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None

    def start(self, model, run_dir: str | Path) -> None:
        if self.running:
            return
        self._thread = QThread()
        self._worker = _Worker(model, str(run_dir), self._cross_sections)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.started.connect(self.started)
        self._worker.batch.connect(self.batch)
        self._worker.finished.connect(self._finish)
        self._worker.failed.connect(self._fail)
        self._thread.start()

    @Slot(object)
    def _finish(self, result) -> None:
        self._teardown()
        self.finished.emit(result)

    @Slot(str)
    def _fail(self, message: str) -> None:
        self._teardown()
        self.failed.emit(message)

    def _teardown(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._worker = None
        self._thread = None

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
