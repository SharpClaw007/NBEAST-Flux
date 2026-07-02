"""G6: Data Library search filter + disk footer + non-blocking download UI."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _visible_materials(dialog):
    out = []
    for i in range(dialog.tree.topLevelItemCount()):
        cat = dialog.tree.topLevelItem(i)
        for j in range(cat.childCount()):
            row = cat.child(j)
            if not row.isHidden():
                out.append(row.text(0))
    return out


def test_search_filters_materials(qapp):
    from nbeast.gui.data_library import DataLibraryDialog

    xs = os.environ.get("OPENMC_CROSS_SECTIONS")
    dialog = DataLibraryDialog(active_xml=xs, starter_xml=xs)
    dialog.search.setText("steel")
    visible = _visible_materials(dialog)
    assert visible and all("steel" in v.lower() for v in visible)
    # clearing shows everything again
    dialog.search.setText("")
    assert len(_visible_materials(dialog)) > len(visible)
    dialog.close()


def test_search_matches_needed_element(qapp):
    from nbeast.gui.data_library import DataLibraryDialog

    xs = os.environ.get("OPENMC_CROSS_SECTIONS")
    dialog = DataLibraryDialog(active_xml=xs, starter_xml=xs)
    dialog.search.setText("Gd")           # matches gadolinia's "needs Gd"
    assert any("Gd" in v or "Gado" in v for v in _visible_materials(dialog))
    dialog.close()


def test_disk_footer_and_progress(qapp):
    from nbeast.gui.data_library import DataLibraryDialog

    dialog = DataLibraryDialog(active_xml=None, starter_xml=None)
    assert "Disk:" in dialog.disk_label.text()
    # busy shows the progress bar + disables download buttons, but not the tree
    dialog._set_busy(True, "Downloading…")
    assert dialog.progress.isVisibleTo(dialog) is True
    assert not dialog.everything_btn.isEnabled()
    assert dialog.tree.isEnabled()        # browsing stays live during a download
    dialog._set_busy(False, "done")
    assert not dialog.everything_btn.isEnabled() is False
    dialog.close()
