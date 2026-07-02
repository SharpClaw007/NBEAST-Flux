"""Adversarial GUI stress: a seeded "monkey" that fires long random sequences of
valid-but-illogical actions at the main window and asserts invariants after each one,
plus exhaustive combination coverage. Headless, no OpenMC runs — catches wiring,
state, undo, and rebuild bugs that hand-written tests miss.

Every failure prints the exact action sequence (all RNG is seeded) so it reproduces.
"""

from __future__ import annotations

import os
import random

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from nbeast.core import specs  # noqa: E402

TEMPLATES = list(specs.SPECS.keys())
CAD = "Custom CAD (DAGMC)"
ALL_MATERIAL_KEYS = None  # filled in the fixture (LIBRARY at import time)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _no_blocking(monkeypatch):
    """Neutralize every blocking UI primitive so the monkey never stalls."""
    from PySide6.QtWidgets import (
        QDialog,
        QFileDialog,
        QInputDialog,
        QMenu,
        QMessageBox,
    )

    monkeypatch.setattr(QDialog, "exec", lambda *a, **k: 0, raising=False)
    monkeypatch.setattr(QMenu, "exec", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No, raising=False)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok, raising=False)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok, raising=False)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""), raising=False)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *a, **k: ([], ""), raising=False)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""), raising=False)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: "", raising=False)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("", False), raising=False)


def _win(tmp_path):
    from nbeast.gui.main_window import MainWindow

    win = MainWindow(run_root=tmp_path, project_dir=tmp_path / "proj")
    win._open_cad_import = lambda: None            # CAD import is env-dependent
    win._open_cad_setup = lambda: None
    win.controller.start = lambda *a, **k: None    # never launch a real OpenMC run
    return win


def _assert_invariants(win):
    """Must hold after ANY action."""
    tree = win.model_tree
    assert tree.model_root is not None and tree.studies_root is not None
    assert tree.results_root is not None
    # document consistency (CAD stores its state in win._cad, not _param_values)
    if not win._is_cad:
        assert win._template in win._param_values
        assert isinstance(win._param_values[win._template], dict)
        assert isinstance(win._material_values.get(win._template, {}), dict)
    # undo stack index is always valid
    stack = win.doc.undo_stack
    assert 0 <= stack.index() <= stack.count()
    # at least the default k-eff study always exists
    kinds = [win.studies.get(s).kind for s in tree.study_ids()]
    assert "keff" in kinds
    # a non-CAD model with all materials available must build; the preview must be finite
    if not win._is_cad:
        win._refresh_geometry_preview()
        if not win._unavailable_materials():
            model = win._build_model()
            assert model.settings.run_mode == win.spec.run_mode


def _clamped(rng, p):
    if p.kind == "int":
        return rng.randint(int(p.minimum), int(p.maximum))
    return rng.uniform(p.minimum, p.maximum)


@pytest.mark.parametrize("seed", [1, 7, 42, 20250702, 99999])
def test_monkey_random_action_sequences(qapp, tmp_path, seed):
    win = _win(tmp_path)
    installed = [k for k, m in _library_available(win)]
    rng = random.Random(seed)
    log = []

    def do_switch():
        t = rng.choice(TEMPLATES + [CAD])
        log.append(f"template={t}")
        win.set_template(t)

    def do_param():
        if win._is_cad or not win.spec.parameters:
            return
        p = rng.choice(win.spec.parameters)
        v = _clamped(rng, p)
        log.append(f"param {p.key}={v:g}")
        win.set_param(p.key, v)

    def do_material():
        if win._is_cad or not win.spec.material_roles:
            return
        role = rng.choice(win.spec.material_roles)
        key = rng.choice(installed)
        log.append(f"material {role.key}={key}")
        win._on_material_selected(role.key, key)

    def do_units():
        win.units_combo.setCurrentIndex(rng.choice([0, 1]))
        log.append("units toggle")

    def do_add_study():
        kinds = [k for k, _ in win.model_tree._addable_kinds]
        if kinds:
            kind = rng.choice(kinds)
            log.append(f"add study {kind}")
            win._add_study(kind)

    def do_select_node():
        tree = win.model_tree
        pools = (tree.model_group_names(), tree.study_ids(), tree.result_scores())
        which = rng.choice([0, 1, 2])
        pool = pools[which]
        if not pool:
            return
        if which == 0:
            item = tree.model_group(rng.choice(pool))
        elif which == 1:
            tree.select_study(rng.choice(pool))
            item = tree.currentItem()
        else:
            tree.select_result(rng.choice(pool))
            item = tree.currentItem()
        if item is not None:
            log.append(f"select {item.text(0)}")
            win._on_tree_click(item, 0)

    def do_undo():
        if win.doc.undo_stack.canUndo():
            log.append("undo")
            win.doc.undo_stack.undo()

    def do_redo():
        if win.doc.undo_stack.canRedo():
            log.append("redo")
            win.doc.undo_stack.redo()

    def do_example():
        key = rng.choice(["godiva", "pincell", "assembly", "shield"])
        log.append(f"example {key}")
        win.load_example(key)

    actions = [do_switch, do_param, do_material, do_units, do_add_study,
               do_select_node, do_undo, do_redo, do_example]
    try:
        for _ in range(600):
            rng.choice(actions)()
            _assert_invariants(win)
    except Exception as exc:  # noqa: BLE001 — surface the reproducing sequence
        raise AssertionError(f"monkey crashed after: {' | '.join(log[-25:])}\n{exc}") from exc
    win.close()


def _library_available(win):
    from nbeast.core import materials

    avail = materials.available_names(win._cross_sections)
    return [(k, m) for k, m in materials.LIBRARY.items() if m.is_available(avail)]


# ---- exhaustive combination coverage ---------------------------------------
def test_every_template_x_every_material_builds(qapp, tmp_path):
    """Any installed material dropped into any slot of any (non-CAD) template must
    build — the 'any material anywhere' guarantee, exhaustively."""
    import openmc

    from nbeast.core import materials

    win = _win(tmp_path)
    installed = [k for k, _ in _library_available(win)]
    saved = openmc.config.get("cross_sections")
    if saved is not None:
        del openmc.config["cross_sections"]   # build data-free (installed-only in practice)
    try:
        for template in TEMPLATES:
            win.set_template(template)
            for role in win.spec.material_roles:
                for key in installed:
                    win.doc.set_material(template, role.key, key)
                    model = win._build_model()
                    assert model.settings.run_mode == win.spec.run_mode
    finally:
        if saved is not None:
            openmc.config["cross_sections"] = saved
    win.close()


def test_every_template_x_every_applicable_study(qapp, tmp_path):
    win = _win(tmp_path)
    for template in TEMPLATES + [CAD]:
        win.set_template(template)
        for kind, _label in list(win.model_tree._addable_kinds):
            win._add_study(kind)
            sid = win.model_tree.study_ids()[-1]
            win._show_study(sid)                      # config pane must render
            assert win._settings_stack.currentWidget() is win.study_pane
            win.study_pane.current_params()           # reading the form must not raise
    win.close()


def test_undo_all_restores_initial_state(qapp, tmp_path):
    """After any number of param/material edits, undoing everything returns the model
    to its exact starting values (per-template)."""
    import copy

    win = _win(tmp_path)
    win.set_template("Pin cell")
    initial = copy.deepcopy(dict(win._param_values)), copy.deepcopy(dict(win._material_values))
    rng = random.Random(99)
    installed = [k for k, _ in _library_available(win)]
    for _ in range(80):
        if rng.random() < 0.5 and win.spec.parameters:
            p = rng.choice(win.spec.parameters)
            win.set_param(p.key, _clamped(rng, p))
        else:
            role = rng.choice(win.spec.material_roles)
            win._on_material_selected(role.key, rng.choice(installed))
        if rng.random() < 0.3:
            win.set_template(rng.choice([t for t in TEMPLATES if t != CAD]))
    while win.doc.undo_stack.canUndo():
        win.doc.undo_stack.undo()
    assert dict(win._param_values) == initial[0]
    assert dict(win._material_values) == initial[1]
    win.close()


def test_every_param_editor_accepts_bounds(qapp, tmp_path):
    """Every parameter editor clamps min/max/over-range input; the value written back
    to the document stays within the parameter's declared range."""
    from PySide6.QtWidgets import QAbstractSpinBox

    win = _win(tmp_path)
    for template in TEMPLATES:
        win.set_template(template)
        for group in ("Geometry", "Materials"):
            item = win.model_tree.model_group(group)
            if item is None:
                continue
            win._on_tree_click(item, 0)
            for row in range(win.properties.rowCount()):
                editor = win.properties.cellWidget(row, 1)
                if isinstance(editor, QAbstractSpinBox):
                    editor.setValue(10 ** 8)              # absurd high (within int32)
                    assert editor.value() <= editor.maximum() + 1e-6
                    editor.setValue(-10 ** 8)             # absurd low
                    assert editor.value() >= editor.minimum() - 1e-6
    # every stored parameter is within its declared bounds
    for template, spec in specs.SPECS.items():
        for p in spec.parameters:
            v = win._param_values[template][p.key]
            assert p.minimum - 1e-6 <= v <= p.maximum + 1e-6, f"{template}.{p.key}={v}"
    win.close()


def test_all_dialogs_construct_for_every_template(qapp, tmp_path):
    """Every tool/dialog constructs without error for every template it could face
    (including the fixed-source and CAD cases that gate features off)."""
    from nbeast.gui.data_library import DataLibraryDialog
    from nbeast.gui.depletion_dialog import DepletionDialog
    from nbeast.gui.mgxs_dialog import MgxsDialog
    from nbeast.gui.moderation_dialog import ModerationDialog
    from nbeast.gui.poisoning_dialog import PoisoningDialog
    from nbeast.gui.report_center import ReportCenterDialog
    from nbeast.gui.sweep_dialog import SweepDialog
    from nbeast.gui.welcome import WelcomeDialog

    win = _win(tmp_path)
    for template in TEMPLATES:
        win.set_template(template)
        for cls in (SweepDialog, ModerationDialog, PoisoningDialog, MgxsDialog,
                    DepletionDialog, ReportCenterDialog):
            cls(win, parent=win).close()
    DataLibraryDialog(active_xml=win._cross_sections, starter_xml=win._starter_xml).close()
    WelcomeDialog(["/tmp/a"], show_startup=False).close()
    win.close()
