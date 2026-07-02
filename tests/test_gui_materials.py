"""Headless GUI checks for the searchable material dropdowns (data-free)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

# A cross_sections.xml describing exactly the bundled (offline) nuclide set, so
# availability flags are deterministic regardless of the test machine's data.
_BUNDLE_XML = (
    '<?xml version="1.0"?><cross_sections>'
    + "".join(
        f'<library materials="{n}" path="x" type="neutron"/>'
        for n in ["H1", "H2", "O16", "O17", "O18", "U234", "U235", "U236", "U238",
                  "Zr90", "Zr91", "Zr92", "Zr94", "Zr96"]
    )
    + '<library materials="c_H_in_H2O" path="x" type="thermal"/></cross_sections>'
)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _no_blocking_dialogs(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)


def _win(tmp_path):
    from nbeast.gui.main_window import MainWindow

    xml = tmp_path / "xs.xml"
    xml.write_text(_BUNDLE_XML)
    win = MainWindow(run_root=tmp_path, project_dir=tmp_path / "p")
    win._cross_sections = str(xml)   # deterministic availability
    return win


def test_combo_lists_every_installed_material_cross_category(qapp, tmp_path):
    win = _win(tmp_path)
    win.set_template("Pin cell")
    win._render_materials_editors()
    assert win.properties.rowCount() == 5  # 3 roles + enrichment + temperature
    combo = win.properties.cellWidget(0, 1)                     # the Fuel slot
    keys = [combo.itemData(i) for i in range(combo.count())]
    labels = [combo.itemText(i) for i in range(combo.count())]
    assert "uo2" in keys                                        # installed fuel present
    assert "mox" not in keys                                    # needs Pu → not shown
    assert not any("needs data" in label for label in labels)  # no greyed needs-data entries
    # every installed material is assignable to any slot — even non-fuels in the Fuel slot
    assert "water" in keys and "zircaloy" in keys
    win.close()


def test_select_material_updates_state_tree_and_build(qapp, tmp_path):
    win = _win(tmp_path)
    win.set_template("Pin cell")
    win._on_material_selected("fuel", "u_metal")
    assert win._material_values["Pin cell"]["fuel"] == "u_metal"
    tree = win.model_tree.model_group("Materials")
    assert "Uranium metal" in tree.child(0).text(0)
    model = win._build_model()
    assert any("U metal" in m.name for m in model.materials)
    win.close()


def test_needs_data_material_blocks_run(qapp, tmp_path):
    win = _win(tmp_path)
    win.set_template("Pin cell")
    win._on_material_selected("clad", "steel_304")  # needs Fe/Cr/Ni/Mn
    win.start_run()
    assert not win.controller.running
    assert "need cross-section data" in win.statusBar().currentMessage()
    win.close()


def test_downloaded_element_appears_in_material_dropdown(qapp, tmp_path):
    """A downloaded element shows up as an assignable material in any geometry slot."""
    from nbeast.core import materials

    win = _win(tmp_path)                          # active library = bundled H/O/U/Zr
    materials.refresh_auto_materials(win._cross_sections, None)   # treat them as downloaded
    try:
        win.set_template("Godiva")
        win._render_materials_editors()
        combo = win.properties.cellWidget(0, 1)   # Godiva core-material slot
        keys = [combo.itemData(i) for i in range(combo.count())]
        assert "element_U" in keys                # downloaded uranium selectable for Godiva
    finally:
        materials.refresh_auto_materials(None, None)
    win.close()


def test_stale_auto_material_selection_is_sanitized(qapp, tmp_path):
    """A persisted auto element material whose data isn't in the active library (e.g.
    'element_Pu' saved, then Pu removed) must revert to the role default, not crash the
    tree/build on the missing LIBRARY key."""
    from nbeast.core import materials

    win = _win(tmp_path)
    win.set_template("Pin cell")
    win._material_values["Pin cell"]["fuel"] = "element_Pu"   # stale (no Pu in bundle)
    assert "element_Pu" not in materials.LIBRARY
    win._sanitize_material_values()
    assert win._material_values["Pin cell"]["fuel"] == "uo2"   # reverted to default
    win._refresh_tree()                                        # must not raise
    win.close()


def test_data_library_category_for_material(qapp, tmp_path):
    """A needs-data material opens the Data Library scrolled to its category."""
    from nbeast.core import materials
    from nbeast.gui.main_window import MainWindow

    win = MainWindow(run_root=tmp_path, project_dir=tmp_path / "p")
    assert win._data_category_for(materials.LIBRARY["steel_304"]) == "Cladding & structural"
    assert win._data_category_for(materials.LIBRARY["b4c"]) == "Absorbers"
    assert win._data_category_for(materials.LIBRARY["uo2"]) == "Fuels"
    win.close()


def test_material_selection_persists_across_reopen(qapp, tmp_path):
    from nbeast.gui.main_window import MainWindow

    win = _win(tmp_path)
    win.set_template("Pin cell")
    win._on_material_selected("fuel", "u_metal")
    win._persist_state()
    win.close()

    reopened = MainWindow(run_root=tmp_path, project_dir=tmp_path / "p")
    assert reopened._material_values["Pin cell"]["fuel"] == "u_metal"
    reopened.close()
