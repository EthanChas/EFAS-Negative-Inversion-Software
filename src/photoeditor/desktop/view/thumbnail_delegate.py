import math

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QStyle, QStyledItemDelegate

from ...theme.tokens import THEME

FLAG_ROLE = Qt.ItemDataRole.UserRole + 1  # "keeper" | "rejected" | None
RATING_ROLE = Qt.ItemDataRole.UserRole + 2  # 0-5 stars
_FLAG_TINTS = {
    "rejected": QColor(220, 40, 40, 115),  # toned red
    "keeper": QColor(70, 200, 100, 60),  # lightly toned green
}
_BORDER_WIDTH_SELECTED = 3
_BORDER_WIDTH_HOVER = 1
_BORDER_WIDTH_DEFAULT = 1
_STAR_PX = 9


def _star(cx: float, cy: float, r: float) -> QPolygonF:
    pts = []
    for i in range(10):
        radius = r if i % 2 == 0 else r * 0.45
        a = -math.pi / 2 + i * math.pi / 5
        pts.append(QPointF(cx + radius * math.cos(a), cy + radius * math.sin(a)))
    return QPolygonF(pts)


class ThumbnailDelegate(QStyledItemDelegate):
    """Draws a darktable-style highlight around the currently selected
    thumbnail(s) in the import grid/filmstrip - a thick accent border when
    selected, a thin muted one on hover, and a plain thin border the rest
    of the time (not nothing - each tile reads as its own distinct, framed
    tile even unselected, which also gives every tile a consistent edge to
    sit the item spacing's gap against - see Filmstrip/ImportWindow's own
    setSpacing calls). Qt's own grid already paints the icon/text/default
    selection background; this just adds the border overlay on top, since
    Fusion's flat selection fill is easy to miss against a thumbnail image.
    A tile's star rating is drawn as small gold stars along its bottom-left."""

    def paint(self, painter: QPainter, option, index) -> None:
        super().paint(painter, option, index)

        tint = _FLAG_TINTS.get(index.data(FLAG_ROLE))
        if tint is not None:
            painter.fillRect(option.rect, tint)

        stars = index.data(RATING_ROLE) or 0
        if stars:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(QPen(QColor(0, 0, 0, 170), 1))
            painter.setBrush(QColor(THEME.status_warning))
            x0, y0 = option.rect.left() + 8, option.rect.bottom() - 8
            for i in range(int(stars)):
                painter.drawPolygon(_star(x0 + i * (_STAR_PX + 1), y0, _STAR_PX / 2))
            painter.restore()

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            color, width = THEME.accent_primary, _BORDER_WIDTH_SELECTED
        elif hover:
            color, width = THEME.text_muted, _BORDER_WIDTH_HOVER
        else:
            color, width = THEME.border_color, _BORDER_WIDTH_DEFAULT

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(QColor(color), width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        half = width // 2
        painter.drawRect(option.rect.adjusted(half, half, -half - 1, -half - 1))
        painter.restore()
