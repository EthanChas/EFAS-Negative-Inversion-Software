"""The common plotting area of the scientific panels: a margin for axis labels and a mapping from data to pixels."""

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from ...theme.tokens import THEME


class _Plot(QWidget):
    """A plain plotting area: a margin for axis labels and a mapping from data to pixels."""

    LEFT, RIGHT, TOP, BOTTOM = 34, 8, 8, 34

    def __init__(self, height: int = 150, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(height)
        self._x = (0.0, 1.0)
        self._y = (0.0, 1.0)

    def _area(self) -> QRectF:
        return QRectF(self.LEFT, self.TOP, max(10, self.width() - self.LEFT - self.RIGHT), max(10, self.height() - self.TOP - self.BOTTOM))

    def _px(self, x: float, y: float) -> QPointF:
        a = self._area()
        fx = (x - self._x[0]) / max(self._x[1] - self._x[0], 1e-9)
        fy = (y - self._y[0]) / max(self._y[1] - self._y[0], 1e-9)
        return QPointF(a.left() + fx * a.width(), a.bottom() - fy * a.height())

    def _frame(self, p: QPainter, x_label: str, step_x: float, step_y: float) -> None:
        p.fillRect(self.rect(), QColor(THEME.bg_input))
        a = self._area()
        grid, text = QColor(THEME.border_color), QColor(THEME.text_muted)
        grid.setAlpha(255)
        p.setFont(QFont(THEME.font_family, 7))
        v = np.ceil(self._x[0] / step_x) * step_x
        while v <= self._x[1] + 1e-9:
            pt = self._px(v, self._y[0])
            p.setPen(QPen(QColor("#2a2a2a")))
            p.drawLine(QPointF(pt.x(), a.top()), QPointF(pt.x(), a.bottom()))
            p.setPen(text)
            p.drawText(QRectF(pt.x() - 18, a.bottom() + 2, 36, 14), Qt.AlignmentFlag.AlignCenter, f"{v + 0.0:g}")
            v += step_x
        v = np.ceil(self._y[0] / step_y) * step_y
        while v <= self._y[1] + 1e-9:
            pt = self._px(self._x[0], v)
            p.setPen(QPen(QColor("#2a2a2a")))
            p.drawLine(QPointF(a.left(), pt.y()), QPointF(a.right(), pt.y()))
            p.setPen(text)
            p.drawText(QRectF(0, pt.y() - 7, self.LEFT - 4, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{v + 0.0:g}")
            v += step_y
        p.setPen(QPen(grid))
        p.drawRect(a)
        p.setPen(text)
        p.drawText(QRectF(a.left(), a.bottom() + 16, a.width(), 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, x_label)
