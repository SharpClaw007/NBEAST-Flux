"""Shared test setup.

Ensures OpenMC runs cleanly when tests shell out via ``model.run()``:
  * FI_PROVIDER=tcp avoids the mpich/OFI finalize abort on macOS (bridge101).
  * The directory holding this Python (the conda env's bin) is put on PATH so the
    ``openmc`` executable is found even when the env isn't "activated".
"""

import os
import sys

os.environ.setdefault("FI_PROVIDER", "tcp")

_bindir = os.path.dirname(sys.executable)
_path = os.environ.get("PATH", "")
if _bindir not in _path.split(os.pathsep):
    os.environ["PATH"] = _bindir + os.pathsep + _path
