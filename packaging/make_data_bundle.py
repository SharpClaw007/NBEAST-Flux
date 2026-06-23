"""Build the bundled cross-section data tarball with a RELATIVE-path index.

The dev cross_sections.xml uses absolute paths (fine in place), but a bundled
copy must reference its .h5 files relatively so it works wherever the installer
puts it. We re-register the nuclides by bare filename and re-export.

Usage: python make_data_bundle.py <data_dir> <out_tarball>
"""

import os
import pathlib
import shutil
import sys
import tarfile
import tempfile

from openmc.data import DataLibrary


def main(data_dir: str, out_tarball: str) -> None:
    data_dir = pathlib.Path(data_dir)
    out_tarball = pathlib.Path(out_tarball)
    out_tarball.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        staged = pathlib.Path(tmp) / "data"
        staged.mkdir()
        for h5 in sorted(data_dir.glob("*.h5")):
            shutil.copy(h5, staged / h5.name)

        cwd = os.getcwd()
        os.chdir(staged)
        try:
            lib = DataLibrary()
            for h5 in sorted(pathlib.Path(".").glob("*.h5")):
                lib.register_file(h5.name)  # store the bare (relative) name
            lib.export_to_xml("cross_sections.xml")
        finally:
            os.chdir(cwd)

        with tarfile.open(out_tarball, "w:gz") as tar:
            tar.add(staged, arcname="data")

    size_mb = out_tarball.stat().st_size / 1e6
    print(f"wrote {out_tarball} ({size_mb:.0f} MB)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
