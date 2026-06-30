"""The startup loader-path sanitizer that protects VTK/matplotlib rendering from a
foreign (MATLAB Runtime) libfreetype on macOS (no Qt / display needed)."""

import os

from nbeast.gui.app import _clean_loader_path

_MATLAB = "/Applications/MATLAB/MATLAB_Runtime/v91/bin/maci64"


def test_strips_only_matlab_entries():
    raw = os.pathsep.join(["/opt/legit/lib", _MATLAB])
    new, changed = _clean_loader_path(raw)
    assert changed is True
    assert new == "/opt/legit/lib"


def test_removes_var_when_all_entries_foreign():
    raw = os.pathsep.join([
        _MATLAB,
        "/Applications/MATLAB/MATLAB_Runtime/v91/runtime/maci64",
    ])
    new, changed = _clean_loader_path(raw)
    assert changed is True
    assert new is None  # nothing legitimate left -> caller drops the variable


def test_leaves_clean_path_untouched():
    raw = os.pathsep.join(["/opt/a/lib", "/opt/b/lib"])
    new, changed = _clean_loader_path(raw)
    assert changed is False
    assert new == raw
