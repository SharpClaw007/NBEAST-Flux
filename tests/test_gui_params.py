"""Editable-parameter tests: edits in the UI actually change the built model."""

import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

_XS = os.environ.get("OPENMC_CROSS_SECTIONS")
requires_data = pytest.mark.skipif(
    not (_XS and pathlib.Path(_XS).exists()),
    reason="OPENMC_CROSS_SECTIONS not set or missing",
)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_geometry_click_shows_editors(qapp):
    """Selecting the Geometry group renders editable spin boxes in Properties."""
    from PySide6.QtWidgets import QDoubleSpinBox

    from nbeast.gui.main_window import MainWindow

    win = MainWindow()
    win.set_template("Pin cell")
    geom = next(
        win.model_tree.topLevelItem(i)
        for i in range(win.model_tree.topLevelItemCount())
        if win.model_tree.topLevelItem(i).text(0) == "Geometry"
    )
    win._on_tree_click(geom, 0)

    # pitch + 3 radii = 4 editable geometry parameters
    assert win.properties.rowCount() == 4
    assert isinstance(win.properties.cellWidget(0, 1), QDoubleSpinBox)
    win.close()


def test_assembly_nside_editor_is_int(qapp):
    """The assembly's 'pins per side' parameter uses an integer spin box."""
    from PySide6.QtWidgets import QSpinBox

    from nbeast.gui.main_window import MainWindow

    win = MainWindow()
    win.set_template("Fuel assembly")
    geom = next(
        win.model_tree.topLevelItem(i)
        for i in range(win.model_tree.topLevelItemCount())
        if win.model_tree.topLevelItem(i).text(0) == "Geometry"
    )
    win._on_tree_click(geom, 0)
    editors = [win.properties.cellWidget(r, 1) for r in range(win.properties.rowCount())]
    assert any(isinstance(e, QSpinBox) for e in editors), "n_side should be an int spin box"
    win.close()


def test_godiva_radius_param_changes_geometry(qapp):
    """Editing the Godiva radius changes the built geometry (data-free)."""
    from nbeast.gui.main_window import MainWindow

    win = MainWindow()
    win.set_template("Godiva")
    win.set_param("radius", 12.0)
    model = win._build_model()

    upper = model.geometry.bounding_box.upper_right
    assert abs(float(upper[0]) - 12.0) < 1e-6
    win.close()


@requires_data
def test_enrichment_param_changes_composition(qapp):
    """Editing enrichment changes the fuel's U-235 atom fraction."""
    from nbeast.gui.main_window import MainWindow

    def u235_fraction(model):
        fuel = next(m for m in model.materials if "UO2" in m.name)
        return {name: pct for (name, pct, _kind) in fuel.nuclides}["U235"]

    win = MainWindow()
    win.set_template("Pin cell")

    win.set_param("enrichment", 3.2)
    low = u235_fraction(win._build_model())
    win.set_param("enrichment", 8.0)
    high = u235_fraction(win._build_model())

    assert high > low, f"U235 fraction did not increase ({low} -> {high})"
    win.close()
