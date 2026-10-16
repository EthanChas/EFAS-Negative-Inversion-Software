from PyQt6.QtCore import QPointF, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen
from PyQt6.QtWidgets import QWidget

from ...features.tonecurve.logic import DEFAULT_POINTS, build_lut
from ...theme.tokens import THEME
from .bevel_widgets import BevelPanel

_POINT_RADIUS = 4
_HIT_RADIUS = 8


class CurveEditor(BevelPanel):
    """A draggable tone curve graph - click an empty spot to add a control
    point, drag a point to move it, double-click a point to remove it (the
    two end anchors are permanent, so there's always at least a line).
    The point last touched is the selected one, shown with a ring; its
    values are reported by selection_changed and can be set by
    set_selected_point (the In / Out boxes beside the graph).

    Signals, mirroring the exposure slider's preview/full split:
    - points_changed: fires on every change, including every tick of an
      in-progress drag - the caller throttles this for a cheap live preview.
    - interaction_finished: fires once an edit is actually done (mouse
      released, a point added by a plain click, a point deleted) - the
      caller treats this as "now do the expensive recompute," no debounce
      needed since this widget already knows exactly when a drag ends.
    - selection_changed(index, x, y): the selected point (index -1 when none)."""

    points_changed = pyqtSignal(list)
    interaction_finished = pyqtSignal()
    selection_changed = pyqtSignal(int, int, int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(sunken=True, bg=THEME.bg_input, thickness=1, parent=parent)
        self.setMinimumSize(180, 160)
        self.setMouseTracking(True)
        self._points: list[tuple[int, int]] = list(DEFAULT_POINTS)
        self._dragging_index: int | None = None
        self._selected: int | None = None
        self._marker_value: float | None = None
        self._color = THEME.channel_luminance
        self._ghosts: list[tuple[list[tuple[int, int]], str]] = []

    def points(self) -> list[tuple[int, int]]:
        return list(self._points)

    def set_color(self, color: str) -> None:
        """The colour of the curve being edited (the channel's own, or the luminance colour for the master)."""
        self._color = color
        self.update()

    def set_ghosts(self, ghosts: list[tuple[list[tuple[int, int]], str]]) -> None:
        """Other curves to draw faintly behind this one, as (points, colour) - the three colour curves while the master is shown."""
        self._ghosts = [(list(points), color) for points, color in ghosts]
        self.update()

    def selected(self) -> tuple[int, int, int] | None:
        """(index, x, y) of the selected point, or None."""
        if self._selected is None or not 0 <= self._selected < len(self._points):
            return None
        x, y = self._points[self._selected]
        return self._selected, x, y

    def _select(self, index: int | None) -> None:
        self._selected = index
        chosen = self.selected()
        self.selection_changed.emit(*(chosen if chosen is not None else (-1, 0, 0)))
        self.update()

    def set_selected_point(self, x: int | None = None, y: int | None = None) -> None:
        """Move the selected point to the given input and/or output (the end points keep their inputs at 0 and 255, and a point stays between its neighbours)."""
        chosen = self.selected()
        if chosen is None:
            return
        index, old_x, old_y = chosen
        new_x = old_x if x is None else int(x)
        new_y = old_y if y is None else int(min(max(y, 0), 255))
        if index == 0:
            new_x = 0
        elif index == len(self._points) - 1:
            new_x = 255
        else:
            lo, hi = self._points[index - 1][0] + 1, self._points[index + 1][0] - 1
            new_x = max(lo, min(hi, new_x)) if lo <= hi else old_x
        if (new_x, new_y) == (old_x, old_y):
            return
        self._points[index] = (new_x, new_y)
        self.update()
        self.points_changed.emit(self.points())
        self.interaction_finished.emit()
        self.selection_changed.emit(index, new_x, new_y)

    def set_marker(self, value: float | None) -> None:
        """An eyedropper-style readout: mirrors HistogramPanel.set_marker,
        marking where the pixel currently hovered in the main image falls
        on this curve - its input brightness as a vertical line, and where
        the curve currently maps that input to as a dot on the curve."""
        self._marker_value = value
        self.update()

    def set_points(self, points: list[tuple[int, int]]) -> None:
        """Replace the curve without emitting its changes - used when a new
        file loads (the controller already resets its own curve state as
        part of that) or right before the caller emits its own signals for
        an explicit Reset click."""
        self._points = list(points)
        self._dragging_index = None
        self._selected = None
        self.selection_changed.emit(-1, 0, 0)
        self.update()

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

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        rect = self._plot_rect()
        pos = event.position()
        index = self._point_near(rect, pos)
        if index is not None:
            self._dragging_index = index
            self._select(index)
            return

        value = self._to_value(rect, pos)
        if value is None or any(x == value[0] for x, _ in self._points):
            return
        self._points.append(value)
        self._points.sort()
        self._dragging_index = self._points.index(value)
        self._select(self._dragging_index)
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
            x = 0
        elif index == len(self._points) - 1:
            x = 255
        else:
            lo, hi = self._points[index - 1][0] + 1, self._points[index + 1][0] - 1
            x = max(lo, min(hi, x)) if lo <= hi else self._points[index][0]
        self._points[index] = (x, y)
        self.update()
        self.points_changed.emit(self.points())
        self.selection_changed.emit(index, x, y)

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
            self._select(None)
            self.update()
            self.points_changed.emit(self.points())
            self.interaction_finished.emit()

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
        for points, color in self._ghosts:
            self._draw_curve(painter, rect, build_lut(points), color, 1, 110)
        self._draw_curve(painter, rect, lut, self._color, 2, 255)
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

    def _draw_curve(self, painter: QPainter, rect: QRect, lut, color: str, width: int, alpha: int) -> None:
        path = QPainterPath()
        path.moveTo(self._to_widget(rect, 0, lut[0]))
        for x in range(1, 256):
            path.lineTo(self._to_widget(rect, x, lut[x]))
        line = QColor(color)
        line.setAlpha(alpha)
        painter.setPen(QPen(line, width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
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
        painter.setBrush(QColor(self._color))
        for index, (vx, vy) in enumerate(self._points):
            center = self._to_widget(rect, vx, vy)
            r = _POINT_RADIUS + 1 if index == self._dragging_index else _POINT_RADIUS
            if index == self._selected:
                painter.setPen(QPen(QColor(THEME.text_primary), 2))
                painter.setBrush(QColor(THEME.bg_input))
                painter.drawEllipse(center, r + 1, r + 1)
                painter.setPen(QPen(QColor(THEME.border_color), 1))
                painter.setBrush(QColor(self._color))
            painter.drawEllipse(center, r, r)
