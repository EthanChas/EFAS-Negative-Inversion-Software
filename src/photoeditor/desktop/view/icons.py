import math

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QCursor, QPainter, QPen, QPixmap, QPolygon

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


def sun_icon(size: int = 16) -> QPixmap:
    """A tiny hand-painted sun icon - the Exposure tool tab."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    cx, cy = size / 2, size / 2
    core_r = size * 0.22
    ray_inner = core_r + max(1, size * 0.08)
    ray_outer = ray_inner + size * 0.18

    pen = QPen(QColor(THEME.channel_luminance), max(1.0, size / 10))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    for angle_deg in range(0, 360, 45):
        angle = math.radians(angle_deg)
        x1 = cx + math.cos(angle) * ray_inner
        y1 = cy + math.sin(angle) * ray_inner
        x2 = cx + math.cos(angle) * ray_outer
        y2 = cy + math.sin(angle) * ray_outer
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(THEME.channel_luminance))
    painter.drawEllipse(QPointF(cx, cy), core_r, core_r)
    painter.end()
    return pix


def eyedropper_icon(size: int = 16) -> QPixmap:
    """A tiny hand-painted eyedropper icon - the tone curve's pick-a-spot
    tool button, and (at a larger size) the cursor shown while it's active."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    bulb = QPointF(size * 0.78, size * 0.22)
    bend = QPointF(size * 0.34, size * 0.66)
    tip = QPointF(size * 0.22, size * 0.88)

    pen = QPen(QColor(THEME.channel_luminance), max(1.4, size * 0.14))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(bulb, bend)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(THEME.channel_luminance))
    painter.drawEllipse(bulb, size * 0.1, size * 0.1)

    pen2 = QPen(QColor(THEME.text_primary), max(1.0, size * 0.1))
    pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen2)
    painter.drawLine(bend, tip)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(THEME.accent_primary))
    painter.drawEllipse(tip, size * 0.08, size * 0.08)

    painter.end()
    return pix


def negative_icon(size: int = 16) -> QPixmap:
    """A tiny hand-painted icon - a light swatch with a dark inset,
    evoking a film negative's inverted tones - for the Negative tool tab."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(THEME.channel_luminance))
    painter.drawRect(0, 0, size - 1, size - 1)

    inset = round(size * 0.32)
    painter.setBrush(QColor(THEME.bg_app))
    painter.drawRect(inset, inset, size - 2 * inset - 1, size - 2 * inset - 1)

    painter.end()
    return pix


def correction_icon(size: int = 16) -> QPixmap:
    """A tiny hand-painted icon - two slider tracks with knobs - for the Correction tool tab."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setPen(Qt.PenStyle.NoPen)
    track = QColor(THEME.text_muted)
    knob = QColor(THEME.channel_luminance)
    for row, knob_at in ((0.28, 0.65), (0.68, 0.3)):
        y = round(size * row)
        painter.setBrush(track)
        painter.drawRect(1, y, size - 2, 2)
        painter.setBrush(knob)
        kx = round((size - 5) * knob_at)
        painter.drawRect(kx, y - 2, 5, 6)
    painter.end()
    return pix


def watermark_icon(size: int = 16) -> QPixmap:
    """A tiny hand-painted film canister - body, cap and a strip of film - for the Canister Watermark tool tab."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setPen(Qt.PenStyle.NoPen)
    body_w, body_h = round(size * 0.5), round(size * 0.66)
    x0, y0 = round(size * 0.12), round(size * 0.24)
    painter.setBrush(QColor(THEME.channel_luminance))
    painter.drawRect(x0, y0, body_w, body_h)
    painter.setBrush(QColor(THEME.text_muted))
    painter.drawRect(x0, y0 - 2, body_w, 2)
    painter.drawRect(x0 + body_w // 2 - 1, max(0, y0 - 4), 2, 2)
    painter.drawRect(x0 + body_w, y0 + body_h - 5, size - (x0 + body_w) - 1, 4)
    painter.end()
    return pix


def metadata_icon(size: int = 16) -> QPixmap:
    """A tiny hand-painted luggage tag - tag body, a punched hole and a cord - for the Metadata tool tab."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(THEME.channel_luminance))
    x0, y0, w, h = round(size * 0.22), round(size * 0.30), round(size * 0.56), round(size * 0.62)
    painter.drawRect(x0, y0 + 2, w, h - 2)
    painter.drawRect(x0 + 2, y0, w - 4, 2)
    painter.setBrush(QColor(THEME.bg_app))
    painter.drawRect(x0 + w // 2 - 1, y0 + 3, 3, 3)
    painter.setBrush(QColor(THEME.text_muted))
    painter.drawRect(x0 + w // 2, 0, 1, y0 + 3)
    for line in range(3):
        painter.drawRect(x0 + 2, y0 + 8 + line * 3, w - 4, 1)
    painter.end()
    return pix


def eyedropper_cursor(size: int = 28) -> QCursor:
    """The custom cursor shown over the image while the tone curve's
    eyedropper is active - the same icon, hot-spot at its pick-point tip
    so the cursor's tip (not its center) marks the exact pixel picked."""
    pixmap = eyedropper_icon(size)
    return QCursor(pixmap, int(size * 0.22), int(size * 0.88))
