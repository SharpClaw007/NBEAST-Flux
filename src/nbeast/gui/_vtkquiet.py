"""Silence benign, repetitive third-party rendering noise.

VTK 9.6 logs a WARN every time its GPU-accelerated (Viskores) slice filter declines
a job and falls back to the standard implementation, and its NumPy bridge trips a
NumPy 2.5 deprecation. Both are harmless and have nothing to do with NBEAST, but they
flood the terminal on every result render. We lower VTK's stderr verbosity to ERROR
(real errors still print) and filter that one NumPy deprecation. Idempotent.
"""

from __future__ import annotations

import warnings

_done = False


def quiet() -> None:
    global _done
    if _done:
        return
    _done = True
    warnings.filterwarnings(
        "ignore", category=DeprecationWarning, module=r"vtkmodules\.util\.numpy_support"
    )
    try:
        from vtkmodules.vtkCommonCore import vtkLogger

        vtkLogger.SetStderrVerbosity(vtkLogger.VERBOSITY_ERROR)
    except Exception:  # noqa: BLE001 — quieting noise must never break rendering
        pass
