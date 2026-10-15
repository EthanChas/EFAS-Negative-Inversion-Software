from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QCursor, QPainter, QPixmap, QPolygon

from ...theme.tokens import THEME


def photo_icon(size: int = 14) -> QPixmap:
    """A tiny hand-painted picture-frame icon for the title bar - no asset
    files, consistent with the rest of the app's QPainter-drawn chrome."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setPen(QColor(THEME.text_primary))
    painter.setBrush(QColor(THEME.on_accent))
    painter.drawRect(0, 0, size - 1, size - 1)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(THEME.channel_luminance))
    painter.drawEllipse(size - 6, 1, 3, 3)

    painter.setBrush(QColor(THEME.text_primary))
    mountain = QPolygon([
        QPoint(1, size - 2),
        QPoint(size // 2, size // 3),
        QPoint(size - 2, size - 2),
    ])
    painter.drawPolygon(mountain)
    painter.end()
    return pix


def eyedropper_cursor(size: int = 28) -> QCursor:
    """The cursor shown over the image while a dropper is active: the pipette icon file, with the hot-spot at its tip so the tip (not its centre) marks the exact pixel."""
    from . import panel_icons

    pixmap = panel_icons.pixmap(panel_icons.OTHER["dropper"], size, THEME.text_primary)
    return QCursor(pixmap, int(size * 0.1), int(size * 0.9))
