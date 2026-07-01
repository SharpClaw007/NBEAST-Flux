"""core.data: size table + import + reset (composition/plumbing, no downloads)."""

import glob
import os

from nbeast.core import data


def test_size_table_and_aggregation():
    assert data.everything_size() > 1e9                 # full library is multiple GB
    assert data.element_size("U") > data.element_size("H")
    assert data.size_for(elements=["U", "O"]) == data.element_size("U") + data.element_size("O")
    assert data.size_for(nuclides=["Xe135", "Sm149"]) > 0
    assert "GB" in data.format_size(data.everything_size())
    assert data.format_size(0) == "size unknown"
    assert data.format_size(30_000_000).endswith("MB")


def test_import_files_and_reset(tmp_path):
    xs = os.environ.get("OPENMC_CROSS_SECTIONS")
    if not xs:
        return  # need a real .h5 to reindex
    h5s = glob.glob(os.path.join(os.path.dirname(xs), "*.h5"))
    if not h5s:
        return
    dest = tmp_path / "lib"
    xml = data.import_files([h5s[0]], dest=str(dest))
    assert xml.exists()
    assert (dest / os.path.basename(h5s[0])).exists()
    assert data.installed_h5(dest=str(dest)) == [os.path.basename(h5s[0])]
    # reset removes the whole user library dir
    data.reset_to_starter(dest=str(dest))
    assert not dest.exists()
    assert data.installed_h5(dest=str(dest)) == []
