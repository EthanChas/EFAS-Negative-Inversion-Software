"""The small pictures of the light check: a line chart of how things changed shot by shot, a map of how even the light is, and the picture of what was measured in a scan."""

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

from ...theme.tokens import THEME
from .plot_base import _Plot


def _step(span: float, target: int = 5) -> float:
    """A round step (1, 2, 5 times a power of ten) that puts about `target` lines across `span`."""
    raw = max(span, 1e-9) / target
    power = 10 ** np.floor(np.log10(raw))
    for k in (1, 2, 5, 10):
        if raw <= k * power:
            return float(k * power)
    return float(10 * power)


class SeriesChart(_Plot):
    """Lines against shot number or minutes, with the normal range shaded green and a zero line."""

    def __init__(self, title: str, height: int = 150, parent: QWidget | None = None):
        super().__init__(height, parent)
        self._title = title
        self._series: list[tuple[str, QColor, list[float]]] = []
        self._xs: list[float] = []
        self._band: tuple[float, float] | None = None
        self._x_label = ""
        self.setToolTip(title)

    def set_data(self, xs: list[float], series: list[tuple[str, str, list]], band: tuple[float, float] | None = None, x_label: str = "") -> None:
        self._xs = [float(x) for x in xs]
        self._series = [(name, QColor(colour), [None if v is None else float(v) for v in values]) for name, colour, values in series]
        self._band = band
        self._x_label = x_label
        values = [v for _n, _c, vs in self._series for v in vs if v is not None] + (list(band) if band else []) + [0.0]
        lo, hi = min(values), max(values)
        pad = max((hi - lo) * 0.12, 0.05)
        self._y = (lo - pad, hi + pad)
        x0, x1 = (min(self._xs), max(self._xs)) if self._xs else (0.0, 1.0)
        self._x = (x0 - (x1 - x0) * 0.03 - (0.5 if x0 == x1 else 0), x1 + (x1 - x0) * 0.03 + (0.5 if x0 == x1 else 0))
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        step_x = _step(self._x[1] - self._x[0])
        step_y = _step(self._y[1] - self._y[0], 4)
        a = self._area()
        if self._band is not None:
            top, bottom = self._px(self._x[0], self._band[1]), self._px(self._x[0], self._band[0])
            p.fillRect(QRectF(a.left(), top.y(), a.width(), bottom.y() - top.y()), QColor(76, 175, 80, 45))
        self._frame(p, self._x_label, step_x, step_y)
        zero = self._px(self._x[0], 0.0)
        p.setPen(QPen(QColor(THEME.text_muted), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(a.left(), zero.y()), QPointF(a.right(), zero.y()))
        p.setFont(QFont(THEME.font_family, 8))
        p.setPen(QColor(THEME.text_secondary))
        p.drawText(QRectF(a.left() + 6, a.top() + 1, a.width() - 12, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._title)
        key = a.right() - 4
        for name, colour, values in reversed(self._series):
            pts = [self._px(x, v) for x, v in zip(self._xs, values) if v is not None]
            p.setPen(QPen(colour, 2))
            for q, r in zip(pts, pts[1:]):
                p.drawLine(q, r)
            p.setBrush(colour)
            for q in pts:
                p.drawEllipse(q, 3, 3)
            p.setPen(colour)
            width = p.fontMetrics().horizontalAdvance(name) + 6
            p.drawText(QRectF(key - width, a.top() + 1, width, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, name)
            key -= width + 6
        p.end()


class EvennessMap(QWidget):
    """The patches of the lit area, each coloured by how much brighter (warm) or dimmer (cool) it is than the average, with the first and the last shot side by side."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        self._maps: list[tuple[str, np.ndarray]] = []
        self._limit = 5.0

    def set_maps(self, maps: list[tuple[str, np.ndarray]]) -> None:
        self._maps = maps
        spread = max([np.abs(100 * (m / m.mean() - 1)).max() for _n, m in maps] + [2.0])
        self._limit = float(min(max(spread, 3.0), 30.0))
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(THEME.bg_input))
        if not self._maps:
            return
        p.setFont(QFont(THEME.font_family, 8))
        gap = 12
        width = (self.width() - gap * (len(self._maps) + 1)) / len(self._maps)
        for k, (name, cells) in enumerate(self._maps):
            x0, y0 = gap + k * (width + gap), 18
            rows, cols = cells.shape
            cell = min(width / cols, (self.height() - y0 - 6) / rows)
            p.setPen(QColor(THEME.text_secondary))
            p.drawText(QRectF(x0, 1, width, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
            deviation = 100 * (cells / cells.mean() - 1)
            for i in range(rows):
                for j in range(cols):
                    t = float(np.clip(deviation[i, j] / self._limit, -1, 1))
                    colour = QColor(int(120 + 120 * max(t, 0)), int(120 + 40 * (1 - abs(t))), int(120 + 120 * max(-t, 0)))
                    p.fillRect(QRectF(x0 + j * cell, y0 + i * cell, cell - 1, cell - 1), colour)
        p.setPen(QColor(THEME.text_muted))
        p.drawText(QRectF(0, self.height() - 14, self.width() - 6, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"warm = brighter than average, cool = dimmer (full colour at {self._limit:.0f}%)")
        p.end()


class MeasuredScan(QWidget):
    """What was measured in one scan: the scan with the clear film green, the light in the sprocket holes red, the black holder blue and blown-out film pink."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(160)
        self._pixmap: QPixmap | None = None
        self._image: QImage | None = None
        self._text = ""

    def set_image(self, rgb: np.ndarray | None, text: str = "") -> None:
        self._text = text
        self._image = None
        if rgb is not None:
            data = np.ascontiguousarray(rgb)
            h, w = data.shape[:2]
            self._image = QImage(data.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(THEME.bg_input))
        p.setFont(QFont(THEME.font_family, 8))
        if self._image is not None:
            area = QRectF(6, 6, self.width() - 12, self.height() - 38)
            scaled = self._image.scaled(int(area.width()), int(area.height()), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            p.drawImage(int(area.left() + (area.width() - scaled.width()) / 2), int(area.top()), scaled)
        legend = [("clear film", "#50e650"), ("light in the sprocket holes", "#ff4646"), ("black holder", "#3c64ff"), ("blown out", "#ff82dc")]
        x = 8
        y = self.height() - 28
        for name, colour in legend:
            p.fillRect(QRectF(x, y + 2, 10, 10), QColor(colour))
            p.setPen(QColor(THEME.text_secondary))
            w = p.fontMetrics().horizontalAdvance(name)
            p.drawText(QRectF(x + 14, y, w + 4, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
            x += w + 28
        p.setPen(QColor(THEME.text_muted))
        p.drawText(QRectF(8, self.height() - 14, self.width() - 16, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._text)
        p.end()
