from PyQt6.QtCore import QPointF, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen
from PyQt6.QtWidgets import QWidget

from ...features.tonecurve.logic import DEFAULT_POINTS, build_lut
from ...theme.tokens import THEME
from .bevel_widgets import BevelPanel

_POINT_RADIUS = 4
_HIT_RADIUS = 8  # a bit larger than the drawn point, so it's easy to grab


class CurveEditor(BevelPanel):
    """A draggable tone curve graph - click an empty spot to add a control
    point, drag a point to move it, double-click a point to remove it (the
    two end anchors are permanent, so there's always at least a line).

    Two signals, mirroring the exposure slider's preview/full split:
    - points_changed: fires on every change, including every tick of an
      in-progress drag - the caller throttles this for a cheap live preview.
    - interaction_finished: fires once an edit is actually done (mouse
      released, a point added by a plain click, a point deleted) - the
      caller treats this as "now do the expensive recompute," no debounce
      needed since this widget already knows exactly when a drag ends."""

    points_changed = pyqtSignal(list)
    interaction_finished = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(sunken=True, bg=THEME.bg_input, thickness=1, parent=parent)
        self.setMinimumSize(180, 160)
        self.setMouseTracking(True)
        self._points: list[tuple[int, int]] = list(DEFAULT_POINTS)
        self._dragging_index: int | None = None
        self._marker_value: float | None = None

    def points(self) -> list[tuple[int, int]]:
        return list(self._points)

    def set_marker(self, value: float | None) -> None:
        """An eyedropper-style readout: mirrors HistogramPanel.set_marker,
        marking where the pixel currently hovered in the main image falls
        on this curve - its input brightness as a vertical line, and where
        the curve currently maps that input to as a dot on the curve."""
        self._marker_value = value
        self.update()

    def set_points(self, points: list[tuple[int, int]]) -> None:
        """Replace the curve without emitting anything - used when a new
        file loads (the controller already resets its own curve state as
        part of that) or right before the caller emits its own signals for
        an explicit Reset click."""
        self._points = list(points)
        self._dragging_index = None
        self.update()

    # ---- geometry ----
    def _plot_rect(self) -> QRect:
        margin = THEME.border_width + THEME.space_sm
        return self.rect().adjusted(margin, margin, -margin, -margin)

    def _to_widget(self, rect: QRect, value_x: float, value_y: float) -> QPointF:
        px = rect.left() + (value_x / 255.0) * rect.width()
        py = rect.bottom() - (value_y / 255.0) * rect.height()
        return QPointF(px, py)

    def _to_value(self, rect: QRect, pos: QPointF) -> tuple[int, int] | None:
        if rect.width() <= 0 or rect.height() <= 0:
            return None
        x = (pos.x() - rect.left()) / rect.width() * 255.0
        y = (rect.bottom() - pos.y()) / rect.height() * 255.0
        return round(min(max(x, 0), 255)), round(min(max(y, 0), 255))

    def _point_near(self, rect: QRect, pos: QPointF) -> int | None:
        best_index, best_dist = None, _HIT_RADIUS
        for index, (vx, vy) in enumerate(self._points):
            widget_pos = self._to_widget(rect, vx, vy)
            dist = (widget_pos - pos).manhattanLength()
            if dist < best_dist:
                best_index, best_dist = index, dist
        return best_index

    # ---- mouse ----
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        rect = self._plot_rect()
        pos = event.position()
        index = self._point_near(rect, pos)
        if index is not None:
            self._dragging_index = index
            return

        value = self._to_value(rect, pos)
        if value is None or any(x == value[0] for x, _ in self._points):
            return  # outside the plot, or an x collision with an existing point
        self._points.append(value)
        self._points.sort()
        self._dragging_index = self._points.index(value)
        self.update()
        self.points_changed.emit(self.points())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging_index is None:
            return
        rect = self._plot_rect()
        value = self._to_value(rect, event.position())
        if value is None:
            return
        index = self._dragging_index
        x, y = value
        if index == 0:
            x = 0  # the left anchor's x is locked - only y (black point) moves
        elif index == len(self._points) - 1:
            x = 255  # the right anchor's x is locked - only y (white point) moves
        else:
            lo, hi = self._points[index - 1][0] + 1, self._points[index + 1][0] - 1
            x = max(lo, min(hi, x)) if lo <= hi else self._points[index][0]
        self._points[index] = (x, y)
        self.update()
        self.points_changed.emit(self.points())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._dragging_index is not None:
            self._dragging_index = None
            self.interaction_finished.emit()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        rect = self._plot_rect()
        index = self._point_near(rect, event.position())
        if index is not None and 0 < index < len(self._points) - 1:
            del self._points[index]
            self._dragging_index = None
            self.update()
            self.points_changed.emit(self.points())
            self.interaction_finished.emit()

    # ---- paint ----
    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        rect = self._plot_rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        lut = build_lut(self._points)
        self._draw_grid(painter, rect)
        self._draw_diagonal(painter, rect)
        self._draw_curve(painter, rect, lut)
        self._draw_points(painter, rect)
        if self._marker_value is not None:
            self._draw_marker(painter, rect, lut)

        painter.end()

    def _draw_grid(self, painter: QPainter, rect: QRect) -> None:
        painter.setPen(QPen(QColor(THEME.text_muted), 1, Qt.PenStyle.DotLine))
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            x = rect.left() + fraction * rect.width()
            painter.drawLine(int(x), rect.top(), int(x), rect.bottom())
            y = rect.top() + fraction * rect.height()
            painter.drawLine(rect.left(), int(y), rect.right(), int(y))

    def _draw_diagonal(self, painter: QPainter, rect: QRect) -> None:
        painter.setPen(QPen(QColor(THEME.text_muted), 1, Qt.PenStyle.DashLine))
        painter.drawLine(rect.bottomLeft(), rect.topRight())

    def _draw_curve(self, painter: QPainter, rect: QRect, lut) -> None:
        path = QPainterPath()
        path.moveTo(self._to_widget(rect, 0, lut[0]))
        for x in range(1, 256):
            path.lineTo(self._to_widget(rect, x, lut[x]))
        painter.setPen(QPen(QColor(THEME.channel_luminance), 2))
        painter.drawPath(path)

    def _draw_marker(self, painter: QPainter, rect: QRect, lut) -> None:
        value = min(max(self._marker_value, 0), 255)
        x = self._to_widget(rect, value, 0).x()
        painter.setPen(QPen(QColor(THEME.text_primary), 1, Qt.PenStyle.DashLine))
        painter.drawLine(int(x), rect.top(), int(x), rect.bottom())

        mapped = float(lut[round(value)])
        dot = self._to_widget(rect, value, mapped)
        painter.setPen(QPen(QColor(THEME.border_color), 1))
        painter.setBrush(QColor(THEME.text_primary))
        painter.drawEllipse(dot, _POINT_RADIUS, _POINT_RADIUS)

    def _draw_points(self, painter: QPainter, rect: QRect) -> None:
        painter.setPen(QPen(QColor(THEME.border_color), 1))
        painter.setBrush(QColor(THEME.channel_luminance))
        for index, (vx, vy) in enumerate(self._points):
            center = self._to_widget(rect, vx, vy)
            r = _POINT_RADIUS + 1 if index == self._dragging_index else _POINT_RADIUS
            painter.drawEllipse(center, r, r)
