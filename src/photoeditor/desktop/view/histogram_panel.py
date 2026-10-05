import math

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen, QWheelEvent,
)
from PyQt6.QtWidgets import QWidget

from ...theme.tokens import THEME
from .bevel_widgets import BevelPanel

_CHANNEL_COLORS = {
    "r": THEME.channel_red,
    "g": THEME.channel_green,
    "b": THEME.channel_blue,
}
_CHANNEL_LABELS = (("r", "Red"), ("g", "Green"), ("b", "Blue"))

_AXIS_LABEL_HEIGHT = 14
_AXIS_LABEL_WIDTH = 34
_LEGEND_HEIGHT = 14
_FULL_RANGE = (0.0, 255.0)
_MIN_ZOOM_SPAN = 8.0
_ZOOM_STEP = 0.85


class HistogramPanel(BevelPanel):
    """The white balance graph - a sunken panel plotting the open image's
    tonal distribution from 0 (black, left) to 255 (white, right), with
    gridlines, axis labels, and mouse-wheel zoom on the value axis
    (double-click to reset).

    Two modes, switched by set_mode():
    - "color": the R/G/B channels, additively blended where they overlap
      (yellow/magenta/cyan/white) the same way Lightroom/Photoshop render
      their RGB histogram overlay, via QPainter's Screen composition mode -
      not three independently alpha-blended fills, which muddies rather
      than mixes the overlapping color.
    - "exposure": a single luminance histogram, with shadow/midtone/
      highlight zone shading and dividers

    Two markers can be drawn on top of either mode:
    - a solid marker line at the brightness of whatever pixel is currently
      hovered in the main image view (see set_marker)
    - hovering the graph itself draws its own dashed cursor line and emits
      bin_hovered(value, reading) with a live reading at that point
    """

    bin_hovered = pyqtSignal(int, dict)   # value 0-255, {"r":n,"g":n,"b":n} or {"luminance":n}
    hover_cleared = pyqtSignal()
    range_selected = pyqtSignal(int, int)  # Exposure view: a span of brightness dragged out on the graph, low and high (0-255)
    range_cleared = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(sunken=True, bg=THEME.bg_input, thickness=1, parent=parent)
        self.setMinimumHeight(180)
        self.setMouseTracking(True)
        self._rgb_histogram: dict[str, list[int]] | None = None
        self._luminance_histogram: list[int] | None = None
        self._mode = "color"
        self._marker_value: float | None = None
        self._cursor_value: int | None = None
        self._zoom_min, self._zoom_max = _FULL_RANGE
        self._selection: tuple[int, int] | None = None  # the dragged-out brightness span (Exposure view only)
        self._drag_anchor: tuple[int, int] | None = None  # (value, x) where the drag began
        self._share_text = ""  # "23.4% of pixels", drawn on the selection

    def set_data(self, rgb_histogram: dict[str, list[int]], luminance_histogram: list[int]) -> None:
        self._rgb_histogram = rgb_histogram
        self._luminance_histogram = luminance_histogram
        self.update()

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        if mode != "exposure":
            self.clear_selection()
        self.update()

    # ---- the selected span ----
    def selection(self) -> tuple[int, int] | None:
        return self._selection

    def clear_selection(self, emit: bool = False) -> None:
        had = self._selection is not None
        self._selection = self._drag_anchor = None
        self._share_text = ""
        self.update()
        if had and emit:
            self.range_cleared.emit()

    def set_share_text(self, text: str) -> None:
        """How much of the picture the selection covers, shown on the selection itself."""
        self._share_text = text
        self.update()

    def _clamped_value_at(self, x: float) -> int:
        rect = self._plot_rect()
        fraction = min(1.0, max(0.0, (x - rect.left()) / rect.width())) if rect.width() > 0 else 0.0
        return min(max(int(round(self._zoom_min + fraction * (self._zoom_max - self._zoom_min))), 0), 255)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._mode == "exposure" and self._luminance_histogram:
            pos = event.position()
            value = self._value_at_x(int(pos.x()), int(pos.y()))
            if value is not None:
                self._drag_anchor = (value, int(pos.x()))
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_anchor is not None:
            moved = self._selection is not None and self._drag_anchor is not None and getattr(self, "_drag_moved", False)
            self._drag_anchor = None
            self._drag_moved = False
            if not moved:  # a plain click: let go of the selection
                self.clear_selection(emit=True)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def set_marker(self, value: float | None) -> None:
        """The brightness marker driven by hovering the main image."""
        self._marker_value = value
        self.update()

    def clear(self) -> None:
        self._rgb_histogram = None
        self._luminance_histogram = None
        self._marker_value = None
        self._cursor_value = None
        self._zoom_min, self._zoom_max = _FULL_RANGE
        self.update()

    def zoom_percent(self) -> int:
        span = self._zoom_max - self._zoom_min
        return round((_FULL_RANGE[1] - _FULL_RANGE[0]) / span * 100) if span else 100

    def _active_series(self) -> list[int] | None:
        if self._mode == "exposure":
            return self._luminance_histogram
        return self._rgb_histogram["r"] if self._rgb_histogram else None

    # ---- geometry ----
    def _plot_rect(self) -> QRect:
        margin_side = THEME.border_width + THEME.space_sm + _AXIS_LABEL_WIDTH // 2
        margin_top = THEME.border_width + THEME.space_sm + _LEGEND_HEIGHT
        margin_bottom = THEME.border_width + THEME.space_sm + _AXIS_LABEL_HEIGHT
        return self.rect().adjusted(margin_side, margin_top, -margin_side, -margin_bottom)

    def _x_for_value(self, rect: QRect, value: float) -> float:
        span = self._zoom_max - self._zoom_min
        fraction = (value - self._zoom_min) / span if span else 0.5
        return rect.left() + fraction * rect.width()

    def _value_at_x(self, x: int, y: int) -> int | None:
        rect = self._plot_rect()
        if rect.width() <= 0 or not rect.contains(x, max(rect.top(), min(y, rect.bottom()))):
            return None
        fraction = (x - rect.left()) / rect.width()
        value = self._zoom_min + fraction * (self._zoom_max - self._zoom_min)
        return min(max(int(round(value)), 0), 255)

    # ---- mouse ----
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        super().mouseMoveEvent(event)
        if not self._active_series():
            return
        pos = event.position()
        if self._drag_anchor is not None and event.buttons() & Qt.MouseButton.LeftButton:
            anchor_value, anchor_x = self._drag_anchor
            if abs(pos.x() - anchor_x) >= 3 or self._selection is not None:  # a few pixels of travel make it a drag, not a click
                self._drag_moved = True
                now = self._clamped_value_at(pos.x())
                span = (min(anchor_value, now), max(anchor_value, now))
                if span != self._selection:
                    self._selection = span
                    self.update()
                    self.range_selected.emit(*span)
                return  # while dragging, the readout is about the selection, not the bin under the cursor
        value = self._value_at_x(int(pos.x()), int(pos.y()))
        if value is None:
            if self._cursor_value is not None:
                self._cursor_value = None
                self.update()
            self.hover_cleared.emit()
            return
        self._cursor_value = value
        self.update()
        if self._mode == "exposure":
            reading = {"luminance": self._luminance_histogram[value]}
        else:
            reading = {name: self._rgb_histogram[name][value] for name in ("r", "g", "b")}
        self.bin_hovered.emit(value, reading)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        if self._cursor_value is not None:
            self._cursor_value = None
            self.update()
        self.hover_cleared.emit()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self._active_series():
            return
        pos = event.position()
        center = self._value_at_x(int(pos.x()), int(self._plot_rect().center().y()))
        if center is None:
            center = (self._zoom_min + self._zoom_max) / 2
        factor = _ZOOM_STEP if event.angleDelta().y() > 0 else 1 / _ZOOM_STEP
        span = max(_MIN_ZOOM_SPAN, min(_FULL_RANGE[1] - _FULL_RANGE[0], (self._zoom_max - self._zoom_min) * factor))

        left_fraction = (center - self._zoom_min) / (self._zoom_max - self._zoom_min) if self._zoom_max > self._zoom_min else 0.5
        new_min = center - left_fraction * span
        new_max = new_min + span
        if new_min < _FULL_RANGE[0]:
            new_min, new_max = _FULL_RANGE[0], _FULL_RANGE[0] + span
        if new_max > _FULL_RANGE[1]:
            new_max, new_min = _FULL_RANGE[1], _FULL_RANGE[1] - span

        self._zoom_min, self._zoom_max = new_min, new_max
        self.update()
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self._zoom_min, self._zoom_max = _FULL_RANGE
        self.update()

    # ---- paint ----
    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        rect = self._plot_rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if self._mode == "exposure":
            self._draw_exposure_zones(painter, rect)
        self._draw_grid(painter, rect)
        self._draw_header(painter)

        if self._mode == "exposure" and self._luminance_histogram:
            peak = math.sqrt(max(self._luminance_histogram) or 1)
            points = self._series_points(rect, self._luminance_histogram, peak)
            self._fill_series(painter, rect, points, THEME.channel_luminance)
            self._stroke_series(painter, points, THEME.channel_luminance)
        elif self._mode == "color" and self._rgb_histogram:
            peak = math.sqrt(max(max(c) for c in self._rgb_histogram.values()) or 1)
            series = {
                name: self._series_points(rect, counts, peak)
                for name, counts in self._rgb_histogram.items()
            }
            # Additive (Screen) blending, not stacked alpha - where two
            # channels overlap this produces yellow/magenta/cyan and white
            # where all three do, matching how Lightroom/Photoshop render
            # their RGB histogram overlay so overlaps read as real colors
            # instead of a muddy gray.
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
            for name, points in series.items():
                self._fill_series(painter, rect, points, _CHANNEL_COLORS[name])
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            for name, points in series.items():
                self._stroke_series(painter, points, _CHANNEL_COLORS[name])

        if self._selection is not None and self._mode == "exposure":
            self._draw_selection(painter, rect)
        if self._marker_value is not None:
            self._draw_line(painter, rect, self._marker_value, QColor(THEME.text_primary), Qt.PenStyle.SolidLine, 2)
        if self._cursor_value is not None:
            self._draw_line(painter, rect, self._cursor_value, QColor(THEME.accent_primary), Qt.PenStyle.DashLine, 1)

        painter.end()

    def _draw_selection(self, painter: QPainter, rect: QRect) -> None:
        """The dragged-out span: a green band over the graph, with its limits and the share of the picture it covers."""
        low, high = self._selection
        x1 = max(rect.left(), self._x_for_value(rect, low - 0.5))
        x2 = min(rect.right(), self._x_for_value(rect, high + 0.5))
        if x2 <= x1:
            return
        green = QColor(60, 225, 90)
        painter.fillRect(QRect(int(x1), rect.top(), max(1, int(x2 - x1)), rect.height()), QColor(60, 225, 90, 55))
        painter.setPen(QPen(green, 1))
        painter.drawLine(int(x1), rect.top(), int(x1), rect.bottom())
        painter.drawLine(int(x2), rect.top(), int(x2), rect.bottom())
        text = f"{low}-{high}" + (f"   {self._share_text}" if self._share_text else "")
        font = painter.font()
        font.setPointSize(THEME.font_size_small)
        painter.setFont(font)
        width = painter.fontMetrics().horizontalAdvance(text) + 8
        left = int(min(max(rect.left(), (x1 + x2) / 2 - width / 2), rect.right() - width))
        label = QRect(left, rect.top() + 2, width, 14)
        painter.fillRect(label, QColor(0, 0, 0, 190))
        painter.setPen(green)
        painter.drawText(label, int(Qt.AlignmentFlag.AlignCenter), text)

    def _draw_header(self, painter: QPainter) -> None:
        x = self.rect().left() + THEME.border_width + THEME.space_sm
        y = self.rect().top() + THEME.border_width + THEME.space_sm
        font = painter.font()
        font.setPointSize(THEME.font_size_small)
        painter.setFont(font)

        if self._mode == "color":
            for key, name in _CHANNEL_LABELS:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(_CHANNEL_COLORS[key])))
                painter.drawRect(x, y + 3, 8, 8)
                painter.setPen(QColor(THEME.text_secondary))
                painter.drawText(x + 12, y + 11, name)
                x += 12 + painter.fontMetrics().horizontalAdvance(name) + THEME.space_md
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(THEME.channel_luminance)))
            painter.drawRect(x, y + 3, 8, 8)
            painter.setPen(QColor(THEME.text_secondary))
            painter.drawText(x + 12, y + 11, "Luminance")

        if self._zoom_min != _FULL_RANGE[0] or self._zoom_max != _FULL_RANGE[1]:
            zoom_text = f"{self.zoom_percent()}% (2x-click reset)"
            painter.setPen(QColor(THEME.text_muted))
            widget_rect = self.rect()
            label_rect = QRect(widget_rect.right() - 140, y, 140 - THEME.space_sm, _LEGEND_HEIGHT)
            painter.drawText(label_rect, int(Qt.AlignmentFlag.AlignRight), zoom_text)

    def _draw_exposure_zones(self, painter: QPainter, rect: QRect) -> None:
        for lo, hi, alpha in ((0, 85, 18), (85, 170, 0), (170, 255, 18)):
            if hi <= self._zoom_min or lo >= self._zoom_max:
                continue
            x1 = self._x_for_value(rect, max(lo, self._zoom_min))
            x2 = self._x_for_value(rect, min(hi, self._zoom_max))
            if alpha:
                painter.fillRect(QRect(int(x1), rect.top(), int(x2 - x1), rect.height()), QColor(255, 255, 255, alpha))

    def _draw_grid(self, painter: QPainter, rect: QRect) -> None:
        painter.setPen(QPen(QColor(THEME.text_muted), 1, Qt.PenStyle.DotLine))
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            x = rect.left() + fraction * rect.width()
            painter.drawLine(int(x), rect.top(), int(x), rect.bottom())
        for fraction in (0.0, 0.5, 1.0):
            y = rect.top() + fraction * rect.height()
            painter.drawLine(rect.left(), int(y), rect.right(), int(y))

        # Each label's rect is anchored so it never extends past the plot
        # area's own left/right edge - anchoring by an offset from the tick
        # position (as before) let the "0" and "255" labels' rects run off
        # the widget entirely at the two ends, clipping them off invisible.
        font = painter.font()
        font.setPointSize(THEME.font_size_small)
        painter.setFont(font)
        painter.setPen(QColor(THEME.text_secondary))
        label_y = rect.bottom() + 2
        mid_value = (self._zoom_min + self._zoom_max) / 2
        painter.drawText(
            QRect(rect.left(), label_y, _AXIS_LABEL_WIDTH, _AXIS_LABEL_HEIGHT),
            int(Qt.AlignmentFlag.AlignLeft), f"{self._zoom_min:.0f}",
        )
        painter.drawText(
            QRect(int(rect.center().x() - _AXIS_LABEL_WIDTH / 2), label_y, _AXIS_LABEL_WIDTH, _AXIS_LABEL_HEIGHT),
            int(Qt.AlignmentFlag.AlignHCenter), f"{mid_value:.0f}",
        )
        painter.drawText(
            QRect(rect.right() - _AXIS_LABEL_WIDTH, label_y, _AXIS_LABEL_WIDTH, _AXIS_LABEL_HEIGHT),
            int(Qt.AlignmentFlag.AlignRight), f"{self._zoom_max:.0f}",
        )

    def _series_points(self, rect: QRect, counts: list[int], peak: float) -> list[tuple[float, float]]:
        lo = max(0, int(math.floor(self._zoom_min)))
        hi = min(len(counts) - 1, int(math.ceil(self._zoom_max)))
        if hi <= lo:
            return []
        return [
            (self._x_for_value(rect, i), rect.bottom() - (math.sqrt(counts[i]) / peak) * rect.height())
            for i in range(lo, hi + 1)
        ]

    def _fill_series(self, painter: QPainter, rect: QRect, points: list[tuple[float, float]], color_hex: str) -> None:
        if not points:
            return
        path = QPainterPath()
        path.moveTo(points[0][0], rect.bottom())
        for x, y in points:
            path.lineTo(x, y)
        path.lineTo(points[-1][0], rect.bottom())
        path.closeSubpath()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(color_hex)))
        painter.drawPath(path)

    def _stroke_series(self, painter: QPainter, points: list[tuple[float, float]], color_hex: str) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(color_hex), 1))
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

    def _draw_line(self, painter: QPainter, rect: QRect, value: float, color: QColor, style, width: int) -> None:
        if value < self._zoom_min or value > self._zoom_max:
            return
        x = self._x_for_value(rect, value)
        painter.setPen(QPen(color, width, style))
        painter.drawLine(int(x), rect.top(), int(x), rect.bottom())
