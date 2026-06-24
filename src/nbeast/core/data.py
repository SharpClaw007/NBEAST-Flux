"""On-demand cross-section data download into a user data directory.

Complements the bundled curated library: the user can fetch more elements /
nuclides (or the full library) on demand. Downloads accumulate in one directory
seeded from the bundled data, and a single cross_sections.xml indexes everything
present — so a downloaded library is always a *superset* of the bundle, never a
replacement that loses the starter nuclides.

Workarounds carried over from the bundled-data work: neutron data from
ENDF/B-VIII.0, S(α,β) from ENDF/B-7.1 (the 8.0 thermal-scattering URLs 404), and
retry-with-backoff around the flaky per-nuclide download host.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

from openmc.data import DataLibrary

# Resolve the console script next to this Python so we don't depend on PATH
# (it has no `-m` entry point).
_DOWNLOADER = str(pathlib.Path(sys.executable).with_name("openmc_data_downloader"))

LIBRARIES = ["ENDFB-8.0-NNDC", "ENDFB-7.1-NNDC"]
SAB_LIBRARY = "ENDFB-7.1-NNDC"

# Named presets → element/nuclide tokens (for openmc_data_downloader -e/-i) + S(a,b).
PRESETS: dict[str, dict] = {
    "Thermal reactor (UO₂ / water / Zr)": {
        "elements": ["U", "O", "H", "Zr"], "sab": ["c_H_in_H2O"],
    },
    "Actinides": {"elements": ["U", "Pu", "Th", "Np", "Am"], "sab": []},
    "Common absorbers": {"elements": ["B", "Gd", "Cd", "Hf", "Ag", "In"], "sab": []},
    "Everything (stable isotopes — large)": {"elements": ["all"], "sab": []},
}


def default_data_dir() -> pathlib.Path:
    return pathlib.Path(os.path.expanduser("~/.nbeast/data"))


def _dl(*args: str, retries: int = 5) -> None:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            subprocess.run([_DOWNLOADER, *args], check=True)
            return
        except subprocess.CalledProcessError as exc:
            last = exc
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"data download failed after {retries} attempts: {last}")


def seed_from(source_xml, dest) -> None:
    """Copy the .h5 files next to an existing cross_sections.xml into dest (idempotent)."""
    source_dir = pathlib.Path(source_xml).parent
    dest = pathlib.Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for h5 in source_dir.glob("*.h5"):
        target = dest / h5.name
        if not target.exists():
            shutil.copy(h5, target)


def build_index(dest) -> pathlib.Path:
    """(Re)build cross_sections.xml indexing every .h5 in dest."""
    dest = pathlib.Path(dest)
    lib = DataLibrary()
    for h5 in sorted(dest.glob("*.h5")):
        lib.register_file(str(h5))
    xml = dest / "cross_sections.xml"
    lib.export_to_xml(str(xml))
    return xml


def download(
    dest,
    library: str = "ENDFB-8.0-NNDC",
    elements=(),
    nuclides=(),
    sab=(),
) -> pathlib.Path:
    """Download the selection into dest, then rebuild the index. Returns the xml path."""
    dest = pathlib.Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    if elements or nuclides:
        args = ["-l", library, "-d", str(dest), "--no-overwrite"]
        if elements:
            args += ["-e", *elements]
        if nuclides:
            args += ["-i", *nuclides]
        _dl(*args)

    if sab:
        # 8.0 S(a,b) assets 404; pull them from 7.1 into a temp dir and copy in.
        with tempfile.TemporaryDirectory() as tmp:
            _dl("-l", SAB_LIBRARY, "-s", *sab, "-d", tmp)
            for h5 in pathlib.Path(tmp).glob("*.h5"):
                shutil.copy(h5, dest / h5.name)

    return build_index(dest)
