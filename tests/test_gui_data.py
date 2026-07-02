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


def test_data_library_has_materials_and_elements_tabs(qapp):
    from nbeast.gui.data_library import DataLibraryDialog

    dialog = DataLibraryDialog(active_xml=None, starter_xml=None)
    assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == ["Materials", "Elements"]
    # Materials tab: categories + Poisons + Depletion, and collapsed on open
    cats = [dialog.tree.topLevelItem(i).text(0) for i in range(dialog.tree.topLevelItemCount())]
    assert {"Fuels", "Moderators & reflectors", "Coolants",
            "Cladding & structural", "Absorbers"} <= set(cats)
    assert any("Poisons" in c for c in cats) and "Depletion chains" in cats
    assert not any("All elements" in c for c in cats)          # elements moved to their own tab
    assert all(not dialog.tree.topLevelItem(i).isExpanded()
               for i in range(dialog.tree.topLevelItemCount()))
    assert "GB" in dialog.everything_btn.text() or "MB" in dialog.everything_btn.text()
    dialog.close()


def test_elements_tab_is_a_full_periodic_table(qapp):
    """The Elements tab holds a periodic-table cell for every element that has data."""
    from nbeast.core import data
    from nbeast.gui.data_library import DataLibraryDialog, _ElementCell

    dialog = DataLibraryDialog(active_xml=None, starter_xml=None)
    cells = dialog._pt_scroll.widget().findChildren(_ElementCell)
    clickable = [c for c in cells if c._on_click is not None]
    assert len(clickable) == len(data.all_elements())          # every data element is clickable
    assert len(cells) > len(clickable)                         # plus greyed no-data positions
    dialog.close()


def test_element_click_shows_isotopes_and_materials(qapp):
    """Clicking an element swaps to a grouped list of its isotopes + materials that use it."""
    from PySide6.QtWidgets import QTreeWidget
    from nbeast.gui.data_library import DataLibraryDialog

    dialog = DataLibraryDialog(active_xml=None, starter_xml=None)
    dialog._show_element_detail("U")
    assert dialog.tabs.currentIndex() == 1 and dialog.el_stack.currentIndex() == 1
    detail = dialog.el_stack.currentWidget().findChild(QTreeWidget)
    groups = {detail.topLevelItem(i).text(0): detail.topLevelItem(i)
              for i in range(detail.topLevelItemCount())}
    iso = next(g for name, g in groups.items() if "Isotopes" in name)
    isotopes = [iso.child(m).text(0) for m in range(iso.childCount())]
    assert "U235" in isotopes and "U238" in isotopes
    used = next(g for name, g in groups.items() if "Used in" in name)
    mats = [used.child(m).text(0) for m in range(used.childCount())]
    assert any("UO" in m for m in mats)
    dialog._show_periodic_table()                              # Back returns to the table
    assert dialog.el_stack.currentIndex() == 0
    dialog.close()


def test_downloaded_items_are_deletable_in_context(qapp, monkeypatch):
    """No top-pinned block: downloaded S(α,β) delete in Moderators; a downloaded element
    deletes from its periodic-table detail page."""
    from PySide6.QtWidgets import QPushButton
    from nbeast.core import data, materials
    from nbeast.gui.data_library import DataLibraryDialog

    xs = os.environ.get("OPENMC_CROSS_SECTIONS")
    if not xs:
        pytest.skip("OPENMC_CROSS_SECTIONS not set")
    bundle = materials.available_names(xs)
    monkeypatch.setattr(data, "downloaded_elements", lambda a, s: ["Pu"])
    monkeypatch.setattr(data, "downloaded_sab", lambda a, s: ["c_D_in_D2O"])
    monkeypatch.setattr(materials, "available_names",
                        lambda x: set(bundle) | {"Pu239", "Pu240", "c_D_in_D2O"})

    dialog = DataLibraryDialog(active_xml=xs, starter_xml=xs)
    cats = [dialog.tree.topLevelItem(i).text(0) for i in range(dialog.tree.topLevelItemCount())]
    assert not any("Installed downloads" in c for c in cats) and cats[0] == "Fuels"

    mod = next(dialog.tree.topLevelItem(i) for i in range(dialog.tree.topLevelItemCount())
               if dialog.tree.topLevelItem(i).text(0) == "Moderators & reflectors")
    sab = [mod.child(j) for j in range(mod.childCount()) if "thermal scattering" in mod.child(j).text(0)]
    assert sab and dialog.tree.itemWidget(sab[0], 3).text() == "Delete"

    dialog._show_element_detail("Pu")                          # downloaded element → Delete in detail
    buttons = [b.text() for b in dialog.el_stack.currentWidget().findChildren(QPushButton)]
    assert any(t.startswith("Delete Pu") for t in buttons)
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
