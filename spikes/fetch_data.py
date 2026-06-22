"""Phase 0 / Spike A deliverable: build a curated cross-section library.

Prototype for the v1 data pipeline. Findings baked in from Phase 0:
  * openmc_data_downloader pulls individual nuclide HDF5 files, which is exactly
    the curated-subset mechanism we want (full ENDF/B-VIII.0 is multi-GB).
  * Its ENDF/B-VIII.0 S(a,b) asset URLs are dead (404). S(a,b) is recovered from
    ENDF/B-7.1 instead (fine for a teaching tool; thermal scattering kernels are
    nearly identical between the two for c_H_in_H2O).
  * Enrichment expansion needs U234/U235/U236/U238 — enumerate nuclides
    explicitly rather than relying on whole-element ('-e') expansion.
  * The downloader rewrites cross_sections.xml per call, so we ignore its XML and
    build a single unified one from every .h5 in the data dir via DataLibrary.

Result for the pin-cell set: ~390 MB, well under the <1 GB v1 budget.

Usage:
    python spikes/fetch_data.py [dest_dir]
"""

import pathlib
import subprocess
import sys
import tempfile

from openmc.data import DataLibrary

# Curated nuclide set for the pin-cell / criticality spike. Expand for v1.
NEUTRON_NUCLIDES = [
    "U234", "U235", "U236", "U238",  # enrichment expansion
    "O16", "O17",
    "H1", "H2",
    "Zr90", "Zr91", "Zr92", "Zr94", "Zr96",
]
SAB_TABLES = ["c_H_in_H2O"]

NEUTRON_LIB = "ENDFB-8.0-NNDC"
SAB_LIB = "ENDFB-7.1-NNDC"  # 8.0 sab assets are 404; 7.1 works


def _dl(*args: str) -> None:
    subprocess.run(["openmc_data_downloader", *args], check=True)


def build(dest: pathlib.Path) -> pathlib.Path:
    dest.mkdir(parents=True, exist_ok=True)

    # Neutron data straight into dest.
    _dl("-l", NEUTRON_LIB, "-i", *NEUTRON_NUCLIDES, "-d", str(dest), "--no-overwrite")

    # S(a,b) into a temp dir, then copy the .h5 into dest.
    with tempfile.TemporaryDirectory() as tmp:
        _dl("-l", SAB_LIB, "-s", *SAB_TABLES, "-d", tmp)
        for h5 in pathlib.Path(tmp).glob("*.h5"):
            (dest / h5.name).write_bytes(h5.read_bytes())

    # One unified cross_sections.xml from every .h5 present.
    lib = DataLibrary()
    for h5 in sorted(dest.glob("*.h5")):
        lib.register_file(str(h5))
    xml = dest / "cross_sections.xml"
    lib.export_to_xml(str(xml))
    print(f"Wrote {xml} with {len(lib.libraries)} entries")
    return xml


if __name__ == "__main__":
    dest = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "data").resolve()
    build(dest)
