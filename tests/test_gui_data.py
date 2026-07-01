"""Data Library dialog: headless construction, categories, status + sizes."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_data_library_categorizes_everything(qapp):
    from nbeast.gui.data_library import DataLibraryDialog

    dialog = DataLibraryDialog(active_xml=None, starter_xml=None)
    cats = [dialog.tree.topLevelItem(i).text(0)
            for i in range(dialog.tree.topLevelItemCount())]
    assert {"Fuels", "Moderators & reflectors", "Coolants",
            "Cladding & structural", "Absorbers"} <= set(cats)
    assert any("Poisons" in c for c in cats) and "Depletion chains" in cats
    assert any("All elements" in c for c in cats)
    # every-download button carries a size estimate
    assert "GB" in dialog.everything_btn.text() or "MB" in dialog.everything_btn.text()
    dialog.close()


def test_data_library_exposes_every_element(qapp):
    """Beyond the catalog materials, the full periodic table of data is installable."""
    from nbeast.core import data
    from nbeast.gui.data_library import DataLibraryDialog

    dialog = DataLibraryDialog(active_xml=None, starter_xml=None)
    all_cat = next(dialog.tree.topLevelItem(i) for i in range(dialog.tree.topLevelItemCount())
                   if "All elements" in dialog.tree.topLevelItem(i).text(0))
    assert all_cat.childCount() == len(data.all_elements())
    assert len(data.all_elements()) > 90     # ~97 elements, the full library
    dialog.close()


def test_data_library_shows_status_and_sizes(qapp):
    """With the bundled H/O/U/Zr library active, installed materials read 'installed'
    and needs-data ones show which nuclides + an approximate size."""
    from nbeast.gui.data_library import DataLibraryDialog

    xs = os.environ.get("OPENMC_CROSS_SECTIONS")
    dialog = DataLibraryDialog(active_xml=xs, starter_xml=xs)
    fuels = next(dialog.tree.topLevelItem(i) for i in range(dialog.tree.topLevelItemCount())
                 if dialog.tree.topLevelItem(i).text(0) == "Fuels")
    rows = {fuels.child(j).text(0): fuels.child(j) for j in range(fuels.childCount())}
    if xs:  # only meaningful when the bundle is the active library
        assert "installed" in rows["UO₂ fuel"].text(1)
        mox = rows["MOX (U,Pu)O₂"]
        assert "needs" in mox.text(1) and "MB" in mox.text(2)
    dialog.close()
