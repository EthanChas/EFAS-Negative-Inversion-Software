"""The two small graphs in the panels of darktable's Tone Equalizer and Color Balance RGB: the equalizer's curve with a node for each octave of brightness that can be dragged, and the three
overlapping masks (shadows, midtones, highlights) over the luminance range. Painted from the values they are given; no module logic is in here beyond asking the module's own functions."""
import math

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ...features.colorbalancergb import logic as cbr
from ...features.toneequalizer import logic as teq
from ...theme.tokens import THEME

_MARGIN = 8


def _frame(widget: QWidget) -> QRectF:
    return QRectF(_MARGIN, _MARGIN, widget.width() - 2 * _MARGIN, widget.height() - 2 * _MARGIN)


class ToneEqGraph(QWidget):
    """The correction in EV (up and down, +/-2) against the brightness in EV (-8 to 0), as the equalizer's curve, with the histogram of the mask behind it when one is known. Drag a node up or
    down to set that octave; double-click to put every node back to 0."""

    node_moved = pyqtSignal(int, float)      # the band (0..8) and its new correction in EV
    reset_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMouseTracking(True)
        self.setToolTip("The exposure correction for each octave of brightness. Drag a node up to lighten, down to darken. Double-click to reset the curve.")
        self._values: dict = dict(teq.DEFAULTS)
        self._histogram: np.ndarray | None = None
        self._drag = -1
        self._hover = -1

    def set_values(self, values: dict) -> None:
        self._values = {**teq.DEFAULTS, **values}
        self.update()

    def set_histogram(self, histogram) -> None:
        """The histogram of the luminance mask between -8 and 0 EV (256 bins), or None."""
        self._histogram = None if histogram is None else np.asarray(histogram, dtype=np.float64)
        self.update()

    # ------------------------------------------------------------ geometry
    def _x(self, ev: float) -> float:
        f = _frame(self)
        return f.left() + (ev - teq.MIN_EV) / (teq.MAX_EV - teq.MIN_EV) * f.width()

    def _y(self, correction_ev: float) -> float:
        f = _frame(self)
        return f.center().y() - correction_ev / 2.0 * f.height() / 2.0

    def _correction_at(self, y: float) -> float:
        f = _frame(self)
        return float(np.clip((f.center().y() - y) / (f.height() / 2.0) * 2.0, -2.0, 2.0))

    def _node(self, i: int) -> QPointF:
        return QPointF(self._x(teq.MIN_EV + i), self._y(float(self._values.get(teq.BANDS[i], 0.0))))

    def _nearest(self, pos: QPointF) -> int:
        best, dist = -1, 14.0
        for i in range(len(teq.BANDS)):
            d = math.hypot(self._node(i).x() - pos.x(), self._node(i).y() - pos.y())
            if d < dist:
                best, dist = i, d
        return best

    # ------------------------------------------------------------ painting
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        f = _frame(self)
        p.fillRect(self.rect(), QColor(THEME.bg_input))
        grid = QColor(THEME.text_muted)
        grid.setAlpha(90)
        p.setPen(QPen(grid, 1))
        for i in range(9):
            p.drawLine(QPointF(self._x(teq.MIN_EV + i), f.top()), QPointF(self._x(teq.MIN_EV + i), f.bottom()))
        for ev in (-2, -1, 0, 1, 2):
            p.drawLine(QPointF(f.left(), self._y(ev)), QPointF(f.right(), self._y(ev)))
        if self._histogram is not None and self._histogram.max() > 0:
            h = self._histogram / self._histogram.max()
            fill = QColor(THEME.text_secondary)
            fill.setAlpha(70)
            n = len(h)
            for k in range(n):
                x0 = f.left() + k / n * f.width()
                height = (h[k] ** 0.5) * f.height() * 0.9
                p.fillRect(QRectF(x0, f.bottom() - height, f.width() / n + 0.5, height), fill)
        ev, correction = teq.correction_curve(self._values, 128)
        path = QPainterPath()
        for k, (a, b) in enumerate(zip(ev, correction)):
            point = QPointF(self._x(float(a)), self._y(float(b)))
            path.moveTo(point) if k == 0 else path.lineTo(point)
        p.setPen(QPen(QColor(THEME.accent_hover), 2))
        p.drawPath(path)
        for i in range(len(teq.BANDS)):
            node = self._node(i)
            active = i in (self._drag, self._hover)
            p.setBrush(QColor(THEME.accent_hover if active else THEME.text_primary))
            p.setPen(QPen(QColor(THEME.border_color), 1))
            p.drawEllipse(node, 5.0 if active else 4.0, 5.0 if active else 4.0)
        p.setPen(QColor(THEME.text_hint))
        p.drawText(QPointF(f.left() + 2, f.bottom() - 2), "-8 EV")
        p.drawText(QPointF(f.right() - 28, f.bottom() - 2), "0 EV")
        p.end()

    # ------------------------------------------------------------ the mouse
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = self._nearest(event.position())
            if self._drag >= 0:
                self.node_moved.emit(self._drag, self._correction_at(event.position().y()))
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag >= 0:
            self.node_moved.emit(self._drag, self._correction_at(event.position().y()))
        else:
            hover = self._nearest(event.position())
            if hover != self._hover:
                self._hover = hover
                self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag = -1
        self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_requested.emit()

    def leaveEvent(self, event) -> None:
        self._hover = -1
        self.update()


class MaskRangesGraph(QWidget):
    """The opacity of the shadows, midtones and highlights masks over the luminance (darker to the left), from the three sliders that shape them."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setToolTip("Where the shadows, midtones and highlights sliders of the other tabs act on the luminance range")
        self._values: dict = dict(cbr.DEFAULTS)

    def set_values(self, values: dict) -> None:
        self._values = {**cbr.DEFAULTS, **values}
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        f = _frame(self)
        p.fillRect(self.rect(), QColor(THEME.bg_input))
        d = cbr._commit({**cbr.DEFAULTS, **self._values})
        # the masks are functions of the luminance to the power 0.41, which is the axis shown (middle grey near the middle)
        x = np.linspace(0.0, 1.0, 160)
        off = x - d["mask_grey_fulcrum"]
        norm = off / d["mask_grey_fulcrum"]
        alpha = 1.0 / (1.0 + np.exp(np.clip(norm * d["shadows_weight"], -80, 80)))
        beta = 1.0 / (1.0 + np.exp(np.clip(-norm * d["highlights_weight"], -80, 80)))
        gamma = np.exp(-(off ** 2) * d["midtones_weight"] / 4.0) * (1.0 - alpha) ** 2 * (1.0 - beta) ** 2 * 8.0
        grid = QColor(THEME.text_muted)
        grid.setAlpha(90)
        p.setPen(QPen(grid, 1))
        for k in range(1, 4):
            p.drawLine(QPointF(f.left() + k * f.width() / 4, f.top()), QPointF(f.left() + k * f.width() / 4, f.bottom()))
        for curve, colour in ((alpha, "#6ba8ff"), (gamma, "#e6e6e6"), (beta, "#ffb36b")):
            path = QPainterPath()
            for k, (px, py) in enumerate(zip(x, np.clip(curve, 0.0, 1.0))):
                point = QPointF(f.left() + px * f.width(), f.bottom() - py * f.height())
                path.moveTo(point) if k == 0 else path.lineTo(point)
            p.setPen(QPen(QColor(colour), 2))
            p.drawPath(path)
        p.end()
