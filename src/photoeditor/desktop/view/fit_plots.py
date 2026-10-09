"""Plots of a characteristic curve for the Sensitometry panel and the characterization dialog: measured points with their uncertainty, the fit with its
band, the part the measurements do not cover, the residuals and the gradient. They only draw what features/densitometry/view_model.py computed."""

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF

from ...features.densitometry.view_model import ChannelView
from ...theme.tokens import THEME
from .plot_base import _Plot

_COLOURS = {"R": THEME.channel_red, "G": THEME.channel_green, "B": THEME.channel_blue, "K": "#e6e6e6"}


def _range(views: list[ChannelView], pad: float = 0.0):
    lo = min(float(v.grid[0]) for v in views)
    hi = max(float(v.grid[-1]) for v in views)
    return lo - pad, hi + pad


class FitPlot(_Plot):
    """Density above base against log exposure: points, fit, confidence band, and the unmeasured range shaded."""

    def __init__(self, parent=None):
        super().__init__(210, parent)
        self._views: list[ChannelView] = []
        self._exposure_label = "log exposure"
        self._empty = "No curve to show"
        self._band: tuple[float, float] | None = None

    def set_views(self, views: list[ChannelView], exposure_label: str = "log exposure", empty: str = "No curve to show", band: tuple[float, float] | None = None) -> None:
        self._views, self._exposure_label, self._empty, self._band = views, exposure_label, empty, band
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._views:
            self._x, self._y = (-4.0, 1.0), (0.0, 3.0)
            self._frame(p, self._exposure_label, 1.0, 1.0)
            p.setPen(QColor(THEME.text_muted))
            p.drawText(self.rect().adjusted(40, 0, -10, 0), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._empty)
            return
        lo, hi = _range(self._views)
        top = max(float(np.nanmax(v.curve)) for v in self._views)
        top = max(top, max(float(np.nanmax(v.y)) for v in self._views))
        self._x = (float(np.floor(lo * 2) / 2), float(np.ceil(hi * 2) / 2))
        self._y = (0.0, float(np.ceil((top + 0.2) * 2) / 2))
        self._frame(p, self._exposure_label, 1.0 if self._x[1] - self._x[0] > 3 else 0.5, 0.5)
        a = self._area()
        sup_lo = min(v.support[0] for v in self._views)
        sup_hi = max(v.support[1] for v in self._views)
        shade = QColor(255, 255, 255, 22)
        left, right = self._px(self._x[0], 0).x(), self._px(sup_lo, 0).x()
        if right > left:
            p.fillRect(QRectF(left, a.top(), right - left, a.height()), shade)
        left, right = self._px(sup_hi, 0).x(), self._px(self._x[1], 0).x()
        if right > left:
            p.fillRect(QRectF(left, a.top(), right - left, a.height()), shade)
        if self._band is not None:
            top_px, bottom_px = self._px(self._x[0], self._band[1]).y(), self._px(self._x[0], self._band[0]).y()
            p.fillRect(QRectF(a.left(), top_px, a.width(), bottom_px - top_px), QColor(255, 255, 255, 26))
        for v in self._views:
            colour = QColor(_COLOURS.get(v.channel, "#ffffff"))
            if v.band is not None:
                poly = QPolygonF([self._px(float(x), float(c + b)) for x, c, b in zip(v.grid, v.curve, v.band)] +
                                 [self._px(float(x), float(max(c - b, 0.0))) for x, c, b in zip(v.grid[::-1], v.curve[::-1], v.band[::-1])])
                fill = QColor(colour)
                fill.setAlpha(45)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(fill))
                p.drawPolygon(poly)
            inside = (v.grid >= v.support[0]) & (v.grid <= v.support[1])
            for mask, style in ((inside, Qt.PenStyle.SolidLine), (~inside, Qt.PenStyle.DotLine)):
                pen = QPen(colour, 1.6, style)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                idx = np.where(mask)[0]
                if idx.size > 1:
                    runs = np.split(idx, np.where(np.diff(idx) > 1)[0] + 1)
                    for run in runs:
                        if run.size > 1:
                            p.drawPolyline(QPolygonF([self._px(float(v.grid[i]), float(v.curve[i])) for i in run]))
            for xi, yi, si, ui in zip(v.x, v.y, v.sigma, v.used):
                c = self._px(float(xi), float(yi))
                p.setPen(QPen(colour, 1.0))
                p.drawLine(QPointF(c.x(), self._px(float(xi), float(yi + si)).y()), QPointF(c.x(), self._px(float(xi), float(max(yi - si, 0))).y()))
                p.setBrush(QBrush(colour) if ui else Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, 2.6, 2.6)
                if not ui:
                    p.drawLine(QPointF(c.x() - 3, c.y() - 3), QPointF(c.x() + 3, c.y() + 3))
                    p.drawLine(QPointF(c.x() - 3, c.y() + 3), QPointF(c.x() + 3, c.y() - 3))


class ResidualPlot(_Plot):
    """What the fit missed at each measured point, in density; the point's own uncertainty as a band. A fit with a pattern here has the wrong shape."""

    BOTTOM = 18

    def __init__(self, parent=None):
        super().__init__(70, parent)
        self._views: list[ChannelView] = []

    def set_views(self, views: list[ChannelView]) -> None:
        self._views = views
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._views:
            self._x, self._y = (-4.0, 1.0), (-0.1, 0.1)
            self._frame(p, "residual (density)", 1.0, 0.1)
            return
        lo, hi = _range(self._views)
        reach = max(0.05, max(float(np.nanmax(np.abs(v.residual))) for v in self._views) * 1.3, max(float(np.nanmax(v.sigma)) for v in self._views) * 1.2)
        self._x, self._y = (float(np.floor(lo * 2) / 2), float(np.ceil(hi * 2) / 2)), (-reach, reach)
        self._frame(p, "residual (density)", 1.0 if self._x[1] - self._x[0] > 3 else 0.5, round(reach, 2))
        a = self._area()
        zero = self._px(self._x[0], 0.0).y()
        p.setPen(QPen(QColor("#888888"), 1.0))
        p.drawLine(QPointF(a.left(), zero), QPointF(a.right(), zero))
        for v in self._views:
            colour = QColor(_COLOURS.get(v.channel, "#ffffff"))
            for xi, ri, si, ui in zip(v.x, v.residual, v.sigma, v.used):
                c = self._px(float(xi), float(ri))
                p.setPen(QPen(colour, 1.0))
                p.drawLine(QPointF(c.x(), zero), c)
                p.setBrush(QBrush(colour) if ui else Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, 2.0, 2.0)


class GradientPlot(_Plot):
    """Local gradient, dD / d log H, across the measured range: it climbs through the toe, levels at gamma and falls through the shoulder."""

    def __init__(self, parent=None):
        super().__init__(110, parent)
        self._views: list[ChannelView] = []

    def set_views(self, views: list[ChannelView]) -> None:
        self._views = views
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._views:
            self._x, self._y = (-4.0, 1.0), (0.0, 1.0)
            self._frame(p, "gradient (density per log exposure)", 1.0, 0.5)
            return
        lo = min(float(v.gradient_grid[0]) for v in self._views)
        hi = max(float(v.gradient_grid[-1]) for v in self._views)
        top = max(float(np.nanmax(v.gradient)) for v in self._views)
        self._x, self._y = (float(np.floor(lo * 2) / 2), float(np.ceil(hi * 2) / 2)), (0.0, float(np.ceil((top + 0.1) * 5) / 5))
        self._frame(p, "gradient (density per log exposure)", 1.0 if self._x[1] - self._x[0] > 3 else 0.5, 0.2 if self._y[1] <= 1.2 else 0.5)
        for v in self._views:
            colour = QColor(_COLOURS.get(v.channel, "#ffffff"))
            p.setPen(QPen(colour, 1.5))
            p.drawPolyline(QPolygonF([self._px(float(x), float(g)) for x, g in zip(v.gradient_grid, v.gradient)]))
            if v.gamma is not None and v.gamma_interval is not None:
                p.setPen(QPen(colour, 1.0, Qt.PenStyle.DotLine))
                p.drawLine(self._px(v.gamma_interval[0], v.gamma), self._px(v.gamma_interval[1], v.gamma))
