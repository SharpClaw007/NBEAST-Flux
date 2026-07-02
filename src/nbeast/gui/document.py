"""The model document — single source of truth for what will be simulated.

Extracted from ``MainWindow``'s state dicts so that (a) every edit can go through a
``QUndoCommand`` on one undo stack (native Edit ▸ Undo/Redo), (b) the Model Builder
tree / settings pane / viewport are *views* over one object, and (c) projects and
studies serialize from a single place.

Two mutation layers:

* **plain setters** (``set_param``/``set_material``/``set_template``) — change state
  and emit signals; used by undo commands themselves, project restore, and examples
  (places that must not spam the undo stack);
* **undoable editors** (``edit_param``/``edit_material``) — push commands; used by
  the UI editors. Consecutive spins of the same field merge into one undo step.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from nbeast.core import specs

CAD_TEMPLATE = "Custom CAD (DAGMC)"

_CMD_PARAM = 1001
_CMD_MATERIAL = 1002


class _SetParamCommand(QUndoCommand):
    def __init__(self, doc: "Document", template: str, key: str, value, old):
        super().__init__(f"Set {key}")
        self._doc, self._template, self._key = doc, template, key
        self._new, self._old = value, old

    def id(self) -> int:  # noqa: A003 — QUndoCommand API
        return _CMD_PARAM

    def mergeWith(self, other) -> bool:  # noqa: N802
        """Consecutive edits of the same field (a spinbox being dragged) collapse
        into one undo step; undo then restores the value before the whole drag."""
        if not isinstance(other, _SetParamCommand):
            return False
        if other._template != self._template or other._key != self._key:
            return False
        self._new = other._new
        return True

    def redo(self) -> None:
        self._doc.set_param(self._template, self._key, self._new)

    def undo(self) -> None:
        self._doc.set_param(self._template, self._key, self._old)


class _SetMaterialCommand(QUndoCommand):
    def __init__(self, doc: "Document", template: str, role_key: str, value, old):
        super().__init__(f"Set {role_key} material")
        self._doc, self._template, self._role = doc, template, role_key
        self._new, self._old = value, old

    def id(self) -> int:  # noqa: A003
        return _CMD_MATERIAL

    def mergeWith(self, other) -> bool:  # noqa: N802
        if not isinstance(other, _SetMaterialCommand):
            return False
        if other._template != self._template or other._role != self._role:
            return False
        self._new = other._new
        return True

    def redo(self) -> None:
        self._doc.set_material(self._template, self._role, self._new)

    def undo(self) -> None:
        self._doc.set_material(self._template, self._role, self._old)


class Document(QObject):
    """Model state + undo stack. Views subscribe to the signals; editors call the
    ``edit_*`` methods; restore/examples call the plain ``set_*`` methods."""

    template_changed = Signal(str)
    param_changed = Signal(str, str)      # (template, key)
    material_changed = Signal(str, str)   # (template, role_key)
    changed = Signal()                    # any model edit (coalesced convenience)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.template: str = next(iter(specs.SPECS))
        self.param_values: dict[str, dict] = {
            label: spec.defaults() for label, spec in specs.SPECS.items()
        }
        self.material_values: dict[str, dict] = {
            label: spec.material_defaults() for label, spec in specs.SPECS.items()
        }
        self.undo_stack = QUndoStack(self)

    # ---- plain setters (no undo) -------------------------------------------
    def set_template(self, name: str) -> None:
        if name == self.template:
            return
        self.template = name
        self.template_changed.emit(name)
        self.changed.emit()

    def set_param(self, template: str, key: str, value) -> None:
        self.param_values.setdefault(template, {})[key] = value
        self.param_changed.emit(template, key)
        self.changed.emit()

    def set_material(self, template: str, role_key: str, mat_key: str) -> None:
        self.material_values.setdefault(template, {})[role_key] = mat_key
        self.material_changed.emit(template, role_key)
        self.changed.emit()

    # ---- undoable edits (UI entry points) ------------------------------------
    def edit_param(self, key: str, value) -> None:
        template = self.template
        old = self.param_values.get(template, {}).get(key)
        if old == value:
            return
        self.undo_stack.push(_SetParamCommand(self, template, key, value, old))

    def edit_material(self, role_key: str, mat_key: str) -> None:
        template = self.template
        old = self.material_values.get(template, {}).get(role_key)
        if old == mat_key:
            return
        self.undo_stack.push(_SetMaterialCommand(self, template, role_key, mat_key, old))

    # ---- convenience ----------------------------------------------------------
    @property
    def current_params(self) -> dict:
        return self.param_values.setdefault(self.template, {})

    @property
    def current_materials(self) -> dict:
        return self.material_values.setdefault(self.template, {})
