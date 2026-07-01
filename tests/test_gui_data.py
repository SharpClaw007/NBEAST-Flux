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


def test_element_drilldown_shows_isotopes_and_materials(qapp):
    """Expanding an element reveals its individual isotopes + the materials that use it."""
    from nbeast.gui.data_library import DataLibraryDialog

    dialog = DataLibraryDialog(active_xml=None, starter_xml=None)
    all_cat = next(dialog.tree.topLevelItem(i) for i in range(dialog.tree.topLevelItemCount())
                   if "All elements" in dialog.tree.topLevelItem(i).text(0))
    u = next(all_cat.child(j) for j in range(all_cat.childCount()) if all_cat.child(j).text(0) == "U")
    dialog._on_item_expanded(u)   # lazy fill

    subs = [u.child(k) for k in range(u.childCount())]
    iso = next(s for s in subs if "Isotopes" in s.text(0))
    isotopes = [iso.child(m).text(0) for m in range(iso.childCount())]
    assert "U235" in isotopes and "U238" in isotopes
    used = next(s for s in subs if "Used in" in s.text(0))
    mats = [used.child(m).text(0) for m in range(used.childCount())]
    assert any("UO" in m for m in mats)                # UO₂ uses U
    dialog.close()


def test_downloaded_items_sort_into_categories(qapp, monkeypatch):
    """Downloaded data lives in its category (deletable there), not a top-pinned block:
    elements → 'All elements' with Delete, S(α,β) → Moderators with Delete."""
    from nbeast.core import data, materials
    from nbeast.gui.data_library import DataLibraryDialog

    xs = os.environ.get("OPENMC_CROSS_SECTIONS")
    if not xs:
        return
    bundle = materials.available_names(xs)
    monkeypatch.setattr(data, "downloaded_elements", lambda a, s: ["Pu"])
    monkeypatch.setattr(data, "downloaded_sab", lambda a, s: ["c_D_in_D2O"])
    monkeypatch.setattr(materials, "available_names",
                        lambda x: set(bundle) | {"Pu239", "Pu240", "c_D_in_D2O"})

    dialog = DataLibraryDialog(active_xml=xs, starter_xml=xs)
    cats = [dialog.tree.topLevelItem(i).text(0) for i in range(dialog.tree.topLevelItemCount())]
    assert not any("Installed downloads" in c for c in cats)   # no top block
    assert cats[0] == "Fuels"

    # Pu (downloaded) shows Delete in All elements
    all_cat = next(dialog.tree.topLevelItem(i) for i in range(dialog.tree.topLevelItemCount())
                   if "All elements" in dialog.tree.topLevelItem(i).text(0))
    pu = next(all_cat.child(j) for j in range(all_cat.childCount()) if all_cat.child(j).text(0) == "Pu")
    assert dialog.tree.itemWidget(pu, 3).text() == "Delete" and "downloaded" in pu.text(1)

    # downloaded S(α,β) shows in Moderators with Delete
    mod = next(dialog.tree.topLevelItem(i) for i in range(dialog.tree.topLevelItemCount())
               if dialog.tree.topLevelItem(i).text(0) == "Moderators & reflectors")
    sab = [mod.child(j) for j in range(mod.childCount()) if "thermal scattering" in mod.child(j).text(0)]
    assert sab and dialog.tree.itemWidget(sab[0], 3).text() == "Delete"
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
