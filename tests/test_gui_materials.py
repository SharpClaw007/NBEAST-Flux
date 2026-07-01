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


def test_combo_populates_and_flags_needs_data(qapp, tmp_path):
    win = _win(tmp_path)
    win.set_template("Pin cell")
    win._render_materials_editors()
    assert win.properties.rowCount() == 5  # 3 roles + enrichment + temperature
    combo = win.properties.cellWidget(0, 1)
    keys = [combo.itemData(i) for i in range(combo.count())]
    labels = [combo.itemText(i) for i in range(combo.count())]
    assert "uo2" in keys and "mox" in keys
    assert any(label == "UO₂ fuel" for label in labels)             # available: clean label
    assert any("MOX" in label and "needs data" in label for label in labels)  # flagged
    win.close()


def test_select_material_updates_state_tree_and_build(qapp, tmp_path):
    win = _win(tmp_path)
    win.set_template("Pin cell")
    win._on_material_selected("fuel", "u_metal")
    assert win._material_values["Pin cell"]["fuel"] == "u_metal"
    tree = win.model_tree.topLevelItem(0)
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


def test_data_manager_prefills_one_material(qapp, tmp_path):
    from nbeast.gui.data_manager import DataManagerDialog

    dialog = DataManagerDialog(active_xml=None, prefill=(["Fe", "Cr"], ["c_Graphite"]))
    assert dialog.elements_edit.text() == "Fe Cr"
    assert dialog.sab_edit.text() == "c_Graphite"
    assert "this material" in dialog.status.text().lower()
    dialog.close()


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
