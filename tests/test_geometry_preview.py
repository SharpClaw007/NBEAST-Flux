"""G2: data-free analytic geometry previews (core primitives + the viewport)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from nbeast.core import render_geometry  # noqa: E402


def test_all_templates_have_previews():
    from nbeast.core import specs

    for label, spec in specs.SPECS.items():
        params = spec.defaults()
        mats = spec.material_defaults()
        preview = render_geometry.preview(label, params, mats)
        assert preview is not None, f"no preview for {label}"
        assert preview.xy.shapes and preview.xz.shapes
        assert preview.legend
        assert preview.xy.width > 0 and preview.xz.height > 0


def test_pin_cell_preview_tracks_parameters():
    p1 = render_geometry.preview("Pin cell", {"pitch": 1.26, "fuel_radius": 0.39,
                                              "clad_inner_radius": 0.40,
                                              "clad_outer_radius": 0.46},
                                 {"fuel": "uo2", "clad": "zircaloy", "moderator": "water"})
    assert p1.xy.width == pytest.approx(1.26)
    fuel = [s for s in p1.xy.shapes if s.label == "fuel"][0]
    assert fuel.w == pytest.approx(0.78)          # diameter = 2·radius
    assert fuel.material == "uo2"
    # the honest annotations are present
    assert "reflective" in p1.xy.note and "infinite" in p1.xz.note


def test_assembly_preview_scales_with_n():
    mats = {"fuel": "uo2", "clad": "zircaloy", "moderator": "water"}
    small = render_geometry.preview("Fuel assembly", {"n_side": 3, "pitch": 1.26,
                                                      "fuel_radius": 0.39,
                                                      "clad_inner_radius": 0.40,
                                                      "clad_outer_radius": 0.46}, mats)
    big = render_geometry.preview("Fuel assembly", {"n_side": 7, "pitch": 1.26,
                                                    "fuel_radius": 0.39,
                                                    "clad_inner_radius": 0.40,
                                                    "clad_outer_radius": 0.46}, mats)
    assert big.xy.width > small.xy.width
    assert len(big.xy.shapes) > len(small.xy.shapes)   # 49 pins vs 9


def test_geometry_view_renders_and_thumbnails(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from nbeast.gui.geometry_view import GeometryView, material_color

    view = GeometryView()
    preview = render_geometry.preview("Pin cell",
                                      {"pitch": 1.26, "fuel_radius": 0.39,
                                       "clad_inner_radius": 0.40, "clad_outer_radius": 0.46},
                                      {"fuel": "uo2", "clad": "zircaloy", "moderator": "water"})
    view.set_preview(preview, "SI", {"U235", "O16", "H1", "Zr90", "c_H_in_H2O"})
    pix = view.render_pixmap(320, 220)
    assert not pix.isNull() and pix.width() == 320
    # role-based colors are distinct + theme-independent
    assert material_color("uo2").name() != material_color("water").name()
    assert material_color(None).name() == "#f2f2f2"    # void
    view.close()


def test_mainwindow_geometry_tab_is_default_and_live(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from nbeast.gui.main_window import MainWindow

    win = MainWindow(run_root=tmp_path, project_dir=tmp_path / "p")
    assert win.tabs.currentWidget() is win.geometry_view    # see the model first
    win.set_template("Godiva")
    win._refresh_geometry_preview()                          # (debounced in real use)
    assert win.geometry_view._preview is not None
    core = [s for s in win.geometry_view._preview.xy.shapes if s.label == "core"][0]
    assert core.w == pytest.approx(2 * win._param_values["Godiva"]["radius"])
    # a param edit reaches the preview after the debounce
    win.set_param("radius", 9.5)
    win._refresh_geometry_preview()
    core = [s for s in win.geometry_view._preview.xy.shapes if s.label == "core"][0]
    assert core.w == pytest.approx(19.0)
    win.close()
