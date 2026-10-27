"""The graph of the Waveform, RGB Parade and Vectorscope views (features/scopes): drawn from the picture on the screen."""

import math

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from ...features.scopes import logic as scopes
from ...theme.tokens import THEME

MODES = (("waveform", "Waveform"), ("parade", "Parade"), ("vector", "Vector"))


class ScopeView(QWidget):
    """A waveform, a parade or a vectorscope of the picture it was last given, with its graticule."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._mode = "waveform"
        self._picture: QImage | None = None
        self._data: np.ndarray | None = None      # keeps the image's memory alive
        self.setMinimumHeight(150)
        self.setToolTip("")

    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        if mode in dict(MODES) and mode != self._mode:
            self._mode = mode
            self._picture = None
            self.update()

    def set_picture(self, rgb: np.ndarray | None) -> None:
        """Draw the scope of this picture (None: an empty graph)."""
        if rgb is None:
            self._picture, self._data = None, None
        else:
            if self._mode == "waveform":
                data = scopes.tint(scopes.waveform(rgb))
            elif self._mode == "parade":
                data = scopes.tint(scopes.parade(rgb))
            else:
                data = scopes.tint(scopes.vectorscope(rgb))
            data = np.ascontiguousarray(data)
            self._data = data
            self._picture = QImage(data.data, data.shape[1], data.shape[0], data.shape[1] * 3, QImage.Format.Format_RGB888)
        self.update()

    def has_picture(self) -> bool:
        return self._picture is not None

    def _plot(self) -> QRectF:
        rect = QRectF(self.rect()).adjusted(26, 6, -6, -6)
        if self._mode == "vector":
            side = min(rect.width(), rect.height())
            return QRectF(rect.center().x() - side / 2, rect.top(), side, side)
        return rect

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(THEME.bg_input))
        plot = self._plot()
        painter.fillRect(plot, QColor("#050505"))
        if self._picture is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawImage(plot, self._picture)
        grid = QColor(255, 255, 255, 46)
        label = QColor(THEME.text_muted)
        painter.setPen(QPen(grid, 1))
        font = QFont(painter.font())
        font.setPointSizeF(max(font.pointSizeF() - 1.5, 6.5))
        painter.setFont(font)
        if self._mode == "vector":
            self._draw_vector_graticule(painter, plot, grid, label)
        else:
            for value in (0, 64, 128, 192, 255):
                y = plot.bottom() - plot.height() * value / 255.0
                painter.setPen(QPen(grid, 1))
                painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
                painter.setPen(label)
                painter.drawText(QRectF(0, y - 7, plot.left() - 4, 14), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), str(value))
            if self._mode == "parade":
                painter.setPen(QPen(grid, 1))
                for i in (1, 2):
                    x = plot.left() + plot.width() * i / 3.0
                    painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
        painter.setPen(QPen(QColor(THEME.border_color), 1))
        painter.drawRect(plot)

    def _draw_vector_graticule(self, painter: QPainter, plot: QRectF, grid: QColor, label: QColor) -> None:
        centre = plot.center()
        radius = plot.width() / 2.0
        painter.setPen(QPen(grid, 1))
        painter.drawLine(QPointF(plot.left(), centre.y()), QPointF(plot.right(), centre.y()))
        painter.drawLine(QPointF(centre.x(), plot.top()), QPointF(centre.x(), plot.bottom()))
        painter.drawEllipse(centre, radius * 0.5, radius * 0.5)
        painter.drawEllipse(centre, radius, radius)
        skin = QColor(255, 190, 120, 110)
        painter.setPen(QPen(skin, 1, Qt.PenStyle.DashLine))
        painter.drawLine(centre, QPointF(centre.x() + math.cos(scopes.SKIN_ANGLE) * radius, centre.y() - math.sin(scopes.SKIN_ANGLE) * radius))
        for name, color in scopes.TARGETS.items():
            fx, fy = scopes.vector_point(color)
            x, y = plot.left() + fx * plot.width(), plot.bottom() - fy * plot.height()
            painter.setPen(QPen(QColor(int(color[0] * 255), int(color[1] * 255), int(color[2] * 255), 200), 1))
            painter.drawRect(QRectF(x - 4, y - 4, 8, 8))
            painter.setPen(label)
            painter.drawText(QRectF(x + 5, y - 7, 14, 14), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), name)


class ZoneStrip(QWidget):
    """The eleven zones (0 black to X white) as a row of cells under a scope. Hovering one says which (zone_hovered, -1 when the pointer leaves) so the picture can show where that zone is;
    a double-click toggles the zone map."""

    zone_hovered = pyqtSignal(int)
    zone_map_toggled = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(24)
        self.setMouseTracking(True)
        self._hover = -1
        self._shares: list[float] = []
        self._base_tip = "Hover a zone to see where it is in the picture; double-click for the zone map"
        self.setToolTip(self._base_tip)

    def hovered(self) -> int:
        return self._hover

    def set_shares(self, shares: list[float] | None) -> None:
        self._shares = list(shares or [])
        self.update()

    def _cell(self, index: int) -> QRectF:
        w = self.width() / float(scopes.ZONE_COUNT)
        return QRectF(index * w, 0, w, self.height())

    def _zone_at(self, x: float) -> int:
        return max(0, min(scopes.ZONE_COUNT - 1, int(x / max(self.width(), 1) * scopes.ZONE_COUNT)))

    def mouseMoveEvent(self, event) -> None:
        zone = self._zone_at(event.position().x())
        if zone != self._hover:
            self._hover = zone
            share = f"  ({100 * self._shares[zone]:.0f}% of the picture)" if zone < len(self._shares) else ""
            self.setToolTip(f"Zone {scopes.ZONE_NAMES[zone]}{share}\n{self._base_tip}")
            self.zone_hovered.emit(zone)
            self.update()

    def leaveEvent(self, event) -> None:
        if self._hover != -1:
            self._hover = -1
            self.zone_hovered.emit(-1)
            self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        self.zone_map_toggled.emit()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        font = QFont(painter.font())
        font.setPointSizeF(max(font.pointSizeF() - 1.5, 6.5))
        painter.setFont(font)
        peak = max(self._shares) if self._shares else 0.0
        for i in range(scopes.ZONE_COUNT):
            cell = self._cell(i)
            level = int(round((i + 0.5) / scopes.ZONE_COUNT * 255))
            painter.fillRect(cell, QColor(level, level, level))
            if peak > 0 and i < len(self._shares):     # how much of the picture is in the zone: a bar up from the bottom of the cell
                painter.fillRect(QRectF(cell.left(), cell.bottom() - 3, cell.width() * self._shares[i] / peak, 3), QColor(THEME.accent_primary))
            painter.setPen(QColor(0, 0, 0) if level > 120 else QColor(255, 255, 255))
            painter.drawText(cell, int(Qt.AlignmentFlag.AlignCenter), scopes.ZONE_NAMES[i])
        if self._hover >= 0:
            painter.setPen(QPen(QColor(THEME.accent_hover), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self._cell(self._hover).adjusted(1, 1, -1, -1))
