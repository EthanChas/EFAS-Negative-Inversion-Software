"""The graph of the Waveform, RGB Parade and Vectorscope views (features/scopes): drawn from the picture on the screen."""

import math

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
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
