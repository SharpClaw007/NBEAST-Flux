"""core.data: size table + import + reset (composition/plumbing, no downloads)."""

import glob
import os

import pytest

from nbeast.core import data


def test_size_table_and_aggregation():
    assert data.everything_size() > 1e9                 # full library is multiple GB
    assert data.element_size("U") > data.element_size("H")
    assert data.size_for(elements=["U", "O"]) == data.element_size("U") + data.element_size("O")
    assert data.size_for(nuclides=["Xe135", "Sm149"]) > 0
    assert "GB" in data.format_size(data.everything_size())
    assert data.format_size(0) == "size unknown"
    assert data.format_size(30_000_000).endswith("MB")


def test_standard_tier_is_a_sized_common_subset():
    """The Standard tier is the common-materials set, smaller than the full library."""
    assert {"B", "Fe", "Cr", "Ni", "C", "Al", "Gd"} <= set(data.STANDARD_ELEMENTS)
    assert 0 < data.standard_size() < data.everything_size()
    assert data.format_size(data.standard_size()).endswith(("MB", "GB"))


def test_downloaded_detection_and_per_element_delete(tmp_path):
    """Elements present in the active library but not the starter are 'downloaded' and
    deletable; deleting removes only that element's files from the user dir."""
    import shutil

    xs = os.environ.get("OPENMC_CROSS_SECTIONS")
    if not xs:
        pytest.skip("OPENMC_CROSS_SECTIONS not set — need real .h5 files to reindex")
    h5s = {os.path.basename(p): p for p in glob.glob(os.path.join(os.path.dirname(xs), "*.h5"))}
    h1 = next((p for n, p in h5s.items() if n.startswith("H1")), None)
    zr = next((p for n, p in h5s.items() if n.startswith("Zr90")), None)
    if not (h1 and zr):
        pytest.skip("bundled H1/Zr90 .h5 files not found next to the cross_sections.xml")

    starter = tmp_path / "starter"
    starter.mkdir()
    shutil.copy(h1, starter / os.path.basename(h1))
    starter_xml = str(data.build_index(str(starter)))

    user = tmp_path / "user"          # active library = starter + a 'downloaded' Zr
    user.mkdir()
    shutil.copy(h1, user / os.path.basename(h1))
    shutil.copy(zr, user / os.path.basename(zr))
    active_xml = str(data.build_index(str(user)))

    assert data.downloaded_elements(active_xml, starter_xml) == ["Zr"]
    new_xml = data.remove_items(elements=["Zr"], active_xml=active_xml, dest=str(user))
    assert new_xml is not None
    assert not (user / os.path.basename(zr)).exists()      # Zr file gone
    assert (user / os.path.basename(h1)).exists()          # starter H untouched
    assert data.downloaded_elements(str(new_xml), starter_xml) == []


def test_import_files_and_reset(tmp_path):
    xs = os.environ.get("OPENMC_CROSS_SECTIONS")
    if not xs:
        pytest.skip("OPENMC_CROSS_SECTIONS not set — need a real .h5 to reindex")
    h5s = glob.glob(os.path.join(os.path.dirname(xs), "*.h5"))
    if not h5s:
        pytest.skip("no bundled .h5 files found next to the cross_sections.xml")
    dest = tmp_path / "lib"
    xml = data.import_files([h5s[0]], dest=str(dest))
    assert xml.exists()
    assert (dest / os.path.basename(h5s[0])).exists()
    assert data.installed_h5(dest=str(dest)) == [os.path.basename(h5s[0])]
    # reset removes the whole user library dir
    data.reset_to_starter(dest=str(dest))
    assert not dest.exists()
    assert data.installed_h5(dest=str(dest)) == []
