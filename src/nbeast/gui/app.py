"""Application entry point: ``nbeast`` (or ``python -m nbeast.gui.app``)."""

from __future__ import annotations

import os
import sys

# Environment variables that can put a foreign library directory ahead of the
# conda environment's own. The MATLAB Runtime is the common offender on macOS:
# its old libfreetype shadows conda's and breaks matplotlib/VTK with
# "Symbol not found: _FT_Bitmap_Init".
_DYLD_VARS = ("DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH")
_SANITIZED_FLAG = "_NBEAST_DYLD_SANITIZED"


def _clean_loader_path(raw: str) -> tuple[str | None, bool]:
    """Drop foreign (MATLAB Runtime) entries from one DYLD path value.

    Returns ``(new_value, changed)`` — ``new_value`` is None when nothing is left.
    """
    entries = raw.split(os.pathsep)
    kept = [p for p in entries if p and "matlab" not in p.lower()]
    if len(kept) == len(entries):
        return raw, False
    return (os.pathsep.join(kept) if kept else None), True


def _sanitize_library_path_and_reexec() -> None:
    """Strip foreign (e.g. MATLAB Runtime) entries from the dynamic-loader path.

    macOS ``dyld`` reads ``DYLD_*`` variables only at process launch, so a polluted
    path can't be repaired in-process — instead we drop the offending entries and
    re-exec once (guarded by a flag to prevent any loop). Without this, the GUI opens
    but VTK/matplotlib rendering crashes because a foreign ``libfreetype`` is loaded.
    """
    if os.environ.get(_SANITIZED_FLAG):
        return

    env = dict(os.environ)
    changed = False
    for var in _DYLD_VARS:
        raw = env.get(var)
        if not raw:
            continue
        new_value, var_changed = _clean_loader_path(raw)
        if var_changed:
            changed = True
            if new_value:
                env[var] = new_value
            else:
                env.pop(var, None)

    if not changed:
        return

    env[_SANITIZED_FLAG] = "1"
    # Replay the *original* invocation so the relaunch matches how we were started —
    # `python -m nbeast.gui.app`, the `nbeast` console script, etc. (sys.orig_argv,
    # 3.10+). Replaying sys.argv would be wrong under `-m`, where sys.argv[0] is the
    # module file path and re-running it as a script breaks the package imports.
    argv = list(getattr(sys, "orig_argv", None)
                or [sys.executable, "-m", "nbeast.gui.app", *sys.argv[1:]])
    try:
        os.execve(sys.executable, argv, env)
    except Exception:  # noqa: BLE001 — if re-exec fails, carry on (best-effort)
        os.environ[_SANITIZED_FLAG] = "1"


def main() -> int:
    # Must run before any matplotlib/VTK import pulls in libfreetype.
    _sanitize_library_path_and_reexec()

    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("NBEAST")
    window = MainWindow()
    window.show()
    window.maybe_show_welcome()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
