"""The Geometry viewport tab — see the model before any transport runs.

Paints the analytic slice previews from :mod:`nbeast.core.render_geometry` with
QPainter: xy and xz side by side, a material legend with needs-data badges, a scale
caption in the current display unit, and the template's honesty note (reflective /
infinite extents). Colors are role-based and explicitly chosen (theme-independent —
dark text/lines are never inherited from the palette).

Also renders to an offscreen pixmap (``render_pixmap``) for template-gallery
thumbnails.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from nbeast.core import materials

# Category → fill color (chosen for print-like clarity on light background).
_CATEGORY_COLORS = {
    "fuel": "#e2703a",
    "moderator": "#4a90d9",
    "coolant": "#7fc3e8",
    "cladding": "#9aa0a8",
    "structural": "#b09a6d",
    "absorber": "#6f5b9e",
    "reflector": "#5aa877",
}
_FALLBACK = "#c9b458"
_BACKGROUND = QColor("#ffffff")
_VOID = QColor("#f2f2f2")
_LINE = QColor("#444444")
_TEXT = QColor("#222222")


def material_color(key: str | None) -> QColor:
    if key is None:
        return _VOID
    spec = materials.LIBRARY.get(key)
    if spec is None:
        return QColor(_FALLBACK)
    if key in ("void",):
        return _VOID
    for cat in spec.categories:
        if cat in _CATEGORY_COLORS:
            return QColor(_CATEGORY_COLORS[cat])
    return QColor(_FALLBACK)


class GeometryView(QWidget):
    """Live pre-run preview of the current model geometry."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._preview = None          # core.render_geometry.GeometryPreview
        self._unit_system = "SI"
        self._available: set = set()
        self._hint = "Pick a template to preview its geometry."
        self.setMinimumSize(320, 240)

    def set_preview(self, preview, unit_system: str = "SI", available: set | None = None) -> None:
        self._preview = preview
        self._unit_system = unit_system
        self._available = available or set()
        self.update()

    def set_hint(self, text: str) -> None:
        self._preview = None
        self._hint = text
        self.update()

    # ---- painting ------------------------------------------------------------
    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), _BACKGROUND)
        if self._preview is None:
            painter.setPen(QPen(QColor("#888888")))
            painter.drawText(self.rect(), Qt.AlignCenter, self._hint)
            painter.end()
            return
        w, h = self.width(), self.height()
        legend_h = 46
        pane_w = w / 2
        self._paint_slice(painter, self._preview.xy, QRectF(0, 0, pane_w, h - legend_h))
        self._paint_slice(painter, self._preview.xz, QRectF(pane_w, 0, pane_w, h - legend_h))
        painter.setPen(QPen(QColor("#bbbbbb")))
        painter.drawLine(int(pane_w), 8, int(pane_w), h - legend_h - 8)
        self._paint_legend(painter, QRectF(0, h - legend_h, w, legend_h))
        painter.end()

    def _paint_slice(self, painter: QPainter, plot, rect: QRectF) -> None:
        from nbeast.core import units

        margin = 34.0
        avail_w, avail_h = rect.width() - 2 * margin, rect.height() - 2 * margin
        if avail_w <= 0 or avail_h <= 0 or plot.width <= 0 or plot.height <= 0:
            return
        scale = min(avail_w / plot.width, avail_h / plot.height)
        cx, cy = rect.center().x(), rect.center().y()

        def map_rect(shape) -> QRectF:
            return QRectF(cx + (shape.x - shape.w / 2) * scale,
                          cy - (shape.y + shape.h / 2) * scale,
                          shape.w * scale, shape.h * scale)

        for shape in plot.shapes:
            fill = material_color(shape.material)
            painter.setBrush(fill)
            painter.setPen(QPen(_LINE, 1.0))
            if shape.kind == "circle":
                painter.drawEllipse(map_rect(shape))
            else:
                painter.drawRect(map_rect(shape))

        # captions: plane name + extent in the display unit + honesty note
        painter.setPen(QPen(_TEXT))
        font = QFont(painter.font())
        font.setPointSizeF(10.0)
        painter.setFont(font)
        extent = units.cm_to_display(plot.width, self._unit_system)
        unit = units.length_unit(self._unit_system)
        painter.drawText(QRectF(rect.x(), rect.y() + 4, rect.width(), 16), Qt.AlignHCenter,
                         f"{plot.axes[0]}{plot.axes[1]} plane · {extent:.3g} {unit} across")
        if plot.note:
            painter.setPen(QPen(QColor("#777777")))
            painter.drawText(QRectF(rect.x(), rect.bottom() - 18, rect.width(), 16),
                             Qt.AlignHCenter, plot.note)

    def _paint_legend(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QPen(_TEXT))
        x = rect.x() + 12
        y = rect.y() + rect.height() / 2
        seen = set()
        for key, role in self._preview.legend:
            if (key, role) in seen:
                continue
            seen.add((key, role))
            spec = materials.LIBRARY.get(key)
            label = spec.label if spec else str(key)
            missing = bool(spec) and self._available and not spec.is_available(self._available)
            chip = QRectF(x, y - 6, 12, 12)
            painter.setBrush(material_color(key))
            painter.setPen(QPen(_LINE, 1.0))
            painter.drawRect(chip)
            text = f"{label} ({role})" + ("  ⬇ needs data" if missing else "")
            painter.setPen(QPen(QColor("#a33") if missing else _TEXT))
            width = painter.fontMetrics().horizontalAdvance(text)
            painter.drawText(QRectF(x + 16, y - 9, width + 8, 18), Qt.AlignVCenter, text)
            x += 16 + width + 26

    # ---- thumbnails (welcome screen / gallery) ---------------------------------
    def render_pixmap(self, width: int = 320, height: int = 220) -> QPixmap:
        """Render the current preview at an exact size. Uses a detached clone: a
        layout-managed widget ignores resize(), which would paint at the live size."""
        clone = GeometryView()
        clone._preview = self._preview
        clone._unit_system = self._unit_system
        clone._available = self._available
        clone._hint = self._hint
        clone.resize(width, height)
        pixmap = QPixmap(width, height)
        pixmap.fill(_BACKGROUND)
        clone.render(pixmap)
        clone.deleteLater()
        return pixmap
