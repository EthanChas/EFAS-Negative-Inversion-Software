import math

import numpy as np

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen, QPolygonF, QWheelEvent,
)
from PyQt6.QtWidgets import QWidget

from ...features.whitebalance.logic import CLIP_HIGHLIGHT_MIN, CLIP_SHADOW_MAX
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
D_AXIS_MAX = 2.4                                                        # the print density at the left of the Density graph (the paper's black is about 2.3); its right is the paper white, 0
STYLES = {"chunky": "Chunky", "smooth": "Smooth", "bars": "Bars"}     # the ways the graph can be drawn; the first is the default
_BAR_COUNT = 64                                                        # bars in the Bars style, across whatever range is shown
_CLIP_SHADOW_COLOUR = "#3270ff"      # the colours the clipping marks on the picture use (features/whitebalance/logic.py)
_CLIP_HIGHLIGHT_COLOUR = "#ff2828"


def code_density(code):
    """The print density (against the paper's own white) a display code stands for: D = -log10 of the light, light being the code undone from sRGB. 255 is 0; 0 is as dense as it gets."""
    v = np.clip(np.asarray(code, dtype=np.float64) / 255.0, 0.0, 1.0)
    light = np.where(v <= 0.04045, v / 12.92, np.power((v + 0.055) / 1.055, 2.4))
    return -np.log10(np.maximum(light, 1e-6))


def density_code(density):
    """The display code (0 to 255, not rounded) of a print density: the inverse of code_density."""
    light = np.power(10.0, -np.asarray(density, dtype=np.float64))
    v = np.where(light <= 0.0031308, light * 12.92, 1.055 * np.power(light, 1 / 2.4) - 0.055)
    return np.clip(v, 0.0, 1.0) * 255.0


def density_of_bin(index: float) -> float:
    """The print density at the left edge of bin `index` (0 to 256) of the Density graph, whose bins are equal steps of density, densest first."""
    return D_AXIS_MAX * (1.0 - index / 256.0)


def to_density_bins(counts) -> list[int]:
    """A 256-level histogram of display codes as 256 bins of equal print density, the counts of a level spread evenly over the density it covers (what is denser than the axis goes in the
    first bin), so the picture is the same one with its tones laid out by how dense the print is rather than by how bright it looks."""
    c = np.asarray(counts, dtype=np.float64)
    cumulative = np.concatenate(([0.0], np.cumsum(c)))                          # at the edges of the levels: level v covers [v, v + 1)
    edges = density_code(density_of_bin(np.arange(257))) + 0.5                  # where each bin edge falls on the level axis
    cut = np.interp(np.clip(edges, 0.0, 256.0), np.arange(257), cumulative)     # cumulative counts at the bin edges, running from dense to light
    bins = np.diff(cut)
    bins[0] += cut[0]
    return [int(round(v)) for v in bins]


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

    bin_hovered = pyqtSignal(int, dict)
    hover_cleared = pyqtSignal()
    range_selected = pyqtSignal(int, int)
    range_cleared = pyqtSignal()
    clip_toggled = pyqtSignal(str)   # "shadows" or "highlights": the arrow beside a clipped share was clicked

    def __init__(self, parent: QWidget | None = None):
        super().__init__(sunken=True, bg=THEME.bg_input, thickness=1, parent=parent)
        self.setMinimumHeight(180)
        self.setMouseTracking(True)
        self._rgb_histogram: dict[str, list[int]] | None = None
        self._luminance_histogram: list[int] | None = None
        self._mode = "color"
        self._density = False
        self._orig_rgb: dict[str, list[int]] | None = None
        self._orig_lum: list[int] | None = None
        self._log = False
        self._split = False
        self._style = "chunky"
        self._marker_value: float | None = None
        self._cursor_value: int | None = None
        self._zoom_min, self._zoom_max = _FULL_RANGE
        self._selection: tuple[int, int] | None = None
        self._drag_anchor: tuple[int, int] | None = None
        self._share_text = ""
        self._clip_share = (0.0, 0.0)        # percent of the picture in the blocked shadows / blown highlights
        self._clip_marking = (False, False)  # whether each is marked on the picture
        self._clip_rects: dict[str, QRect] = {}

    def set_density(self, on: bool) -> None:
        """The Density graph: the same picture on an axis of print density (how dense the print is, 0 at the paper's white to about 2.4 at its black) instead of display levels."""
        on = bool(on)
        if on != self._density:
            self._density = on
            self._selection = self._drag_anchor = None
            self._share_text = ""
            self._zoom_min, self._zoom_max = _FULL_RANGE
            self._apply_axis()
            self.update()

    def density(self) -> bool:
        return self._density

    def _apply_axis(self) -> None:
        """The series the graph draws: the levels as they are, or laid out by print density."""
        if self._density:
            self._rgb_histogram = {k: to_density_bins(v) for k, v in self._orig_rgb.items()} if self._orig_rgb else None
            self._luminance_histogram = to_density_bins(self._orig_lum) if self._orig_lum else self._orig_lum
        else:
            self._rgb_histogram, self._luminance_histogram = self._orig_rgb, self._orig_lum

    def value_label(self, value: float) -> str:
        """What a place on the axis is called: its level, or its print density."""
        return f"Density: {density_of_bin(value + 0.5):.2f} D" if self._density else f"Value: {int(value)}"

    def _view_value(self, code: float) -> float:
        """Where a display level (0 to 255) falls on the axis shown."""
        if not self._density:
            return code
        return float(min(255.0, max(0.0, (1.0 - float(code_density(code)) / D_AXIS_MAX) * 256.0 - 0.5)))

    def _axis_text(self, value: float) -> str:
        return f"{density_of_bin(value + 0.5):.1f}" if self._density else f"{value:.0f}"

    def _code_span(self, span: tuple[int, int]) -> tuple[int, int]:
        """A span of the axis shown as the span of display levels it covers (what picks pixels on the picture)."""
        if not self._density:
            return span
        lo, hi = span
        a, b = density_code(density_of_bin(lo)), density_code(density_of_bin(hi + 1))      # the densest edge is the darkest level
        low = 0 if lo <= 0 else int(max(0, min(255, math.floor(min(a, b)))))               # (the first bin holds everything denser than the axis)
        return (low, int(max(0, min(255, math.ceil(max(a, b))))))

    def set_data(self, rgb_histogram: dict[str, list[int]], luminance_histogram: list[int]) -> None:
        self._orig_rgb = rgb_histogram
        self._orig_lum = luminance_histogram
        self._apply_axis()
        total = float(sum(luminance_histogram)) if luminance_histogram else 0.0
        self._clip_share = ((100.0 * sum(luminance_histogram[:CLIP_SHADOW_MAX + 1]) / total), (100.0 * sum(luminance_histogram[CLIP_HIGHLIGHT_MIN:]) / total)) if total else (0.0, 0.0)
        self.update()

    def clip_share(self) -> tuple[float, float]:
        """The percent of the picture in the blocked shadows and in the blown highlights (the tones the clipping marks cover)."""
        return self._clip_share

    def set_clip_marking(self, shadows: bool, highlights: bool) -> None:
        """Which of the two kinds of clipping are marked on the picture now, so the arrows show it."""
        self._clip_marking = (bool(shadows), bool(highlights))
        self.update()

    def set_log(self, on: bool) -> None:
        """A logarithmic height: small counts (the thin tails of the tones) show up next to the big peaks."""
        self._log = bool(on)
        self.update()

    def set_split(self, on: bool) -> None:
        """Colour mode: draw red, green and blue one above the other, each on its own scale, instead of blended on top of each other."""
        self._split = bool(on)
        self.update()

    def set_style(self, style: str) -> None:
        """How the graph is drawn: "chunky" (the value of every level, as it has always been), "smooth" (a smoothed curve with value bars) or "bars" (a bar graph in 64 steps)."""
        self._style = style if style in STYLES else "chunky"
        self.update()

    def style(self) -> str:
        return self._style

    def log_scale(self) -> bool:
        return self._log

    def channels_split(self) -> bool:
        return self._split

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        if mode != "exposure":
            self.clear_selection()
        self.update()

    def selection(self) -> tuple[int, int] | None:
        """The selected span, as a span of display levels (also on the Density graph, where it is the levels that span of density covers)."""
        return None if self._selection is None else self._code_span(self._selection)

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

    def _clip_at(self, pos) -> str | None:
        point = pos.toPoint()
        return next((kind for kind, rect in self._clip_rects.items() if rect.contains(point)), None)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            kind = self._clip_at(event.position())
            if kind is not None:
                self.clip_toggled.emit(kind)
                event.accept()
                return
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
            if not moved:
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
        self._clip_share = (0.0, 0.0)
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

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        super().mouseMoveEvent(event)
        over = self._clip_at(event.position())
        self.setCursor(Qt.CursorShape.PointingHandCursor if over else Qt.CursorShape.ArrowCursor)
        if over:
            share = self._clip_share[0 if over == "shadows" else 1]
            self.setToolTip(f"{share:.2f}% of the picture is in the {'blocked shadows' if over == 'shadows' else 'blown highlights'}. Click to mark "
                            f"{'them in blue' if over == 'shadows' else 'them in red'} on the picture.")
        if not self._active_series():
            return
        pos = event.position()
        if self._drag_anchor is not None and event.buttons() & Qt.MouseButton.LeftButton:
            anchor_value, anchor_x = self._drag_anchor
            if abs(pos.x() - anchor_x) >= 3 or self._selection is not None:
                self._drag_moved = True
                now = self._clamped_value_at(pos.x())
                span = (min(anchor_value, now), max(anchor_value, now))
                if span != self._selection:
                    self._selection = span
                    self.update()
                    self.range_selected.emit(*self._code_span(span))
                return
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

        self._draw_data(painter, rect)

        if self._selection is not None and self._mode == "exposure":
            self._draw_selection(painter, rect)
        if self._marker_value is not None:
            self._draw_line(painter, rect, self._view_value(self._marker_value), QColor(THEME.text_primary), Qt.PenStyle.SolidLine, 2)
        if self._cursor_value is not None:
            self._draw_line(painter, rect, self._cursor_value, QColor(THEME.accent_primary), Qt.PenStyle.DashLine, 1)

        painter.end()

    # ------------------------------------------------------------ the data, in the chosen style
    def _draw_data(self, painter: QPainter, rect: QRect) -> None:
        """The histogram itself: the luminance, the three channels one above the other (Split) or the three blended; chunky, smooth or as bars."""
        style = self._style
        if self._mode == "exposure" and self._luminance_histogram:
            parts = [(rect, self._luminance_histogram, THEME.channel_luminance)]
            blend = False
        elif self._mode == "color" and self._rgb_histogram and self._split:
            parts = [(band, self._rgb_histogram[name], _CHANNEL_COLORS[name]) for name, band in zip(("r", "g", "b"), self._bands(rect))]
            blend = False
        elif self._mode == "color" and self._rgb_histogram:
            parts = [(rect, self._rgb_histogram[name], _CHANNEL_COLORS[name]) for name in ("r", "g", "b")]
            blend = True
        else:
            return
        if style == "bars":
            self._draw_bars(painter, rect, parts, blend)
            return
        if style == "smooth":
            parts = [(band, self._smoothed(counts), colour) for band, counts, colour in parts]
        peak_all = max((max(counts) for _b, counts, _c in parts), default=0) or 1
        series = []
        for band, counts, colour in parts:
            peak = peak_all if blend else (max(counts) or 1)         # blended channels share one scale; Split gives each its own
            series.append((band, self._series_points(band, counts, peak), colour, peak))
        if blend:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
            for band, points, colour, _peak in series:
                self._fill_series(painter, band, points, colour, smooth=style == "smooth")
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        else:
            for band, points, colour, _peak in series:
                self._fill_series(painter, band, points, colour, smooth=style == "smooth")
        for band, points, colour, _peak in series:
            self._stroke_series(painter, points, colour, smooth=style == "smooth")
        if style == "smooth":       # the value bars go over the curve, so they show on a bright fill too
            self._draw_value_bars(painter, rect, [(band, peak) for band, _p, _c, peak in series[: (3 if self._split and self._mode == "color" else 1)]])

    def _smoothed(self, counts: list[int]) -> list[float]:
        """The counts blurred with a gaussian, as wide as a hundred and twentieth of what is shown (never less than a level), the edges mirrored: a curve instead of a comb."""
        lo = max(0, int(math.floor(self._zoom_min)))
        hi = min(len(counts) - 1, int(math.ceil(self._zoom_max)))
        sigma = max(1.2, (hi - lo) / 120.0)
        radius = int(math.ceil(3 * sigma))
        kernel = [math.exp(-0.5 * (i / sigma) ** 2) for i in range(-radius, radius + 1)]
        total = sum(kernel)
        kernel = [k / total for k in kernel]
        n = len(counts)
        out = []
        for i in range(n):
            acc = 0.0
            for j, k in enumerate(kernel, -radius):
                p = i + j
                p = -p if p < 0 else (2 * (n - 1) - p if p > n - 1 else p)
                acc += k * counts[min(max(p, 0), n - 1)]
            out.append(acc)
        return out

    def _nice_values(self) -> list[int]:
        """The levels the vertical bars stand at: round numbers inside what is shown, about eight at most."""
        span = max(1.0, self._zoom_max - self._zoom_min)
        step = next((s for s in (1, 2, 4, 8, 16, 32, 64) if span / s <= 8), 64)
        first = int(math.ceil(self._zoom_min / step)) * step
        return [v for v in range(first, int(self._zoom_max) + 1, step) if 0 <= v <= 255]

    def _share_at(self, fraction: float, peak: float) -> float:
        """The share of the tallest point's count that a height of `fraction` of the graph stands for, undoing the square root or the log the heights are drawn with."""
        if self._log:
            return math.expm1(fraction * math.log1p(peak)) / peak if peak else 0.0
        return fraction * fraction

    def _draw_value_bars(self, painter: QPainter, rect: QRect, bands: list[tuple[QRect, float]]) -> None:
        """The smooth style's bars: a vertical bar at each round level with its number along the foot, and horizontal bars at 25, 50, 75 and 100% of the height (of the tallest point's
        count, undoing the way the heights are drawn) with their percentages."""
        font = painter.font()
        font.setPointSize(THEME.font_size_small)
        painter.setFont(font)
        fine = QColor(THEME.text_muted)
        fine.setAlpha(150)
        painter.setPen(QPen(fine, 1))
        values = self._nice_values()
        for value in values:
            x = int(self._x_for_value(rect, value))
            painter.drawLine(x, rect.top(), x, rect.bottom())
        fractions = (0.5, 1.0) if len(bands) > 1 else (0.25, 0.5, 0.75, 1.0)       # (Split has three short strips: fewer bars)
        for band, peak in bands:
            for fraction in fractions:
                y = int(band.bottom() - fraction * band.height())
                painter.setPen(QPen(fine, 1))
                painter.drawLine(band.left(), y, band.right(), y)
                text = f"{round(100 * self._share_at(fraction, peak))}%"
                box = QRect(band.left() + 2, y + 1, painter.fontMetrics().horizontalAdvance(text) + 6, 11)
                painter.fillRect(box, QColor(0, 0, 0, 120))
                painter.setPen(QColor(THEME.text_primary))
                painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)
        painter.setPen(QColor(THEME.text_secondary))
        for value in values:
            x = int(self._x_for_value(rect, value))
            painter.drawText(QRect(x - _AXIS_LABEL_WIDTH // 2, rect.bottom() + 2, _AXIS_LABEL_WIDTH, _AXIS_LABEL_HEIGHT), int(Qt.AlignmentFlag.AlignHCenter), self._axis_text(value))

    def _draw_bars(self, painter: QPainter, rect: QRect, parts: list, blend: bool) -> None:
        """The bar style: the shown range cut into 64 bars, each as tall as the fullest level in it. With the channels blended each bar is three thin ones, red, green and blue; in Exposure
        a bar has the grey of the tone it stands for."""
        lo, hi = self._zoom_min, self._zoom_max
        step = (hi - lo) / _BAR_COUNT
        if step <= 0:
            return
        scale = math.log1p if self._log else math.sqrt
        n_series = len(parts)
        peaks = {id(counts): (max(counts) or 1) for _b, counts, _c in parts}
        peak_all = max(peaks.values())
        if blend:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)      # the channels mix where they overlap, as in the other styles
        for k in range(_BAR_COUNT):
            a, b = lo + k * step, lo + (k + 1) * step
            i0, i1 = int(math.floor(a)), min(255, max(int(math.floor(a)), int(math.ceil(b)) - 1))
            slot_left = self._x_for_value(rect, a - 0.5)
            slot_right = self._x_for_value(rect, b - 0.5)
            slot = max(1.0, slot_right - slot_left)
            for index, (band, counts, colour) in enumerate(parts):
                top_count = max(counts[max(0, i0): max(0, i1) + 1] or [0])
                peak = peak_all if blend else peaks[id(counts)]
                height = (scale(top_count) / (scale(peak) or 1.0)) * band.height()
                if height < 1:
                    continue
                width, x = slot - 1.5, slot_left + 0.75
                fill = QColor(colour)
                if not blend and n_series == 1:
                    grey = int(round(255 * ((a + b) / 2) / 255.0))
                    fill = QColor(grey, grey, grey).lighter(110) if self._mode == "exposure" else fill
                x = max(float(rect.left()), x)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fill)
                painter.drawRoundedRect(QRectF(x, band.bottom() - height, max(1.0, width), height), 1.5, 1.5)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

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

        # the names beside the colour squares give way to the squares alone when the clipped shares and the log mark would not fit beside them
        metrics = painter.fontMetrics()
        room = self.rect().width() - 2 * (THEME.border_width + THEME.space_sm) - self._clip_shares_width(metrics) - (36 if self._log else 0) - THEME.space_md
        names = (self._mode == "color" and sum(12 + metrics.horizontalAdvance(n) + THEME.space_md for _k, n in _CHANNEL_LABELS) <= room) or                 (self._mode != "color" and 12 + metrics.horizontalAdvance("Luminance") <= room)
        if self._mode == "color":
            for key, name in _CHANNEL_LABELS:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(_CHANNEL_COLORS[key])))
                painter.drawRect(x, y + 3, 8, 8)
                if names:
                    painter.setPen(QColor(THEME.text_secondary))
                    painter.drawText(x + 12, y + 11, name)
                x += 12 + (metrics.horizontalAdvance(name) if names else 0) + THEME.space_md
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(THEME.channel_luminance)))
            painter.drawRect(x, y + 3, 8, 8)
            if names:
                painter.setPen(QColor(THEME.text_secondary))
                painter.drawText(x + 12, y + 11, "Luminance")

        shift = self._draw_clip_shares(painter, y)
        if self._log:
            painter.setPen(QColor(THEME.text_muted))
            painter.drawText(QRect(self.rect().right() - 34 - THEME.space_sm - shift, y, 34, _LEGEND_HEIGHT), int(Qt.AlignmentFlag.AlignRight), "log")
            shift += 36
        if self._zoom_min != _FULL_RANGE[0] or self._zoom_max != _FULL_RANGE[1]:
            zoom_text = f"{self.zoom_percent()}% (2x-click reset)"
            painter.setPen(QColor(THEME.text_muted))
            widget_rect = self.rect()
            label_rect = QRect(widget_rect.right() - 140 - shift, y, 140 - THEME.space_sm, _LEGEND_HEIGHT)
            painter.drawText(label_rect, int(Qt.AlignmentFlag.AlignRight), zoom_text)

    @staticmethod
    def _percent_text(share: float) -> str:
        return "0%" if share < 0.005 else f"{share:.1f}%" if share >= 0.1 else f"{share:.2f}%"

    def _clip_shares_width(self, metrics) -> int:
        """The room the two clipped shares and their arrows take at the header's right edge."""
        return (10 + 3 + metrics.horizontalAdvance(self._percent_text(self._clip_share[0])) + THEME.space_sm
                + metrics.horizontalAdvance(self._percent_text(self._clip_share[1])) + 3 + 10 + THEME.space_md)

    def _draw_clip_shares(self, painter: QPainter, y: int) -> int:
        """\u25c0 shadows % and highlights % \u25b6 in the header's right corner, each lit in its marking colour while that clipping is marked on the picture.
        Returns the width taken from the right edge."""
        left_text, right_text = self._percent_text(self._clip_share[0]), self._percent_text(self._clip_share[1])
        metrics = painter.fontMetrics()
        arrow = 10
        gap = THEME.space_sm
        left_w = arrow + 3 + metrics.horizontalAdvance(left_text)
        right_w = metrics.horizontalAdvance(right_text) + 3 + arrow
        edge = self.rect().right() - THEME.border_width - THEME.space_sm
        right_rect = QRect(edge - right_w, y, right_w, _LEGEND_HEIGHT)
        left_rect = QRect(right_rect.left() - gap - left_w, y, left_w, _LEGEND_HEIGHT)
        self._clip_rects = {"shadows": left_rect, "highlights": right_rect}
        for kind, rect, text, colour, on, share in (
            ("shadows", left_rect, left_text, _CLIP_SHADOW_COLOUR, self._clip_marking[0], self._clip_share[0]),
            ("highlights", right_rect, right_text, _CLIP_HIGHLIGHT_COLOUR, self._clip_marking[1], self._clip_share[1]),
        ):
            lit = QColor(colour) if on else QColor(THEME.text_secondary if share >= 0.005 else THEME.text_muted)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(lit)
            cy = rect.center().y() + 1
            if kind == "shadows":
                x0 = rect.left()
                painter.drawPolygon(QPolygonF([QPointF(x0 + arrow - 1, cy - 4), QPointF(x0 + arrow - 1, cy + 4), QPointF(x0, cy)]))
                text_rect = QRect(rect.left() + arrow + 3, rect.top(), rect.width() - arrow - 3, rect.height())
            else:
                x0 = rect.right() - arrow + 1
                painter.drawPolygon(QPolygonF([QPointF(x0, cy - 4), QPointF(x0, cy + 4), QPointF(x0 + arrow - 1, cy)]))
                text_rect = QRect(rect.left(), rect.top(), rect.width() - arrow - 3, rect.height())
            painter.setPen(lit)
            painter.drawText(text_rect, int((Qt.AlignmentFlag.AlignLeft if kind == "shadows" else Qt.AlignmentFlag.AlignRight) | Qt.AlignmentFlag.AlignVCenter), text)
        return right_rect.right() - left_rect.left() + THEME.space_md

    def _draw_exposure_zones(self, painter: QPainter, rect: QRect) -> None:
        for lo, hi, alpha in ((0, 85, 18), (85, 170, 0), (170, 255, 18)):
            if hi <= self._zoom_min or lo >= self._zoom_max:
                continue
            x1 = self._x_for_value(rect, max(lo, self._zoom_min))
            x2 = self._x_for_value(rect, min(hi, self._zoom_max))
            if alpha:
                painter.fillRect(QRect(int(x1), rect.top(), int(x2 - x1), rect.height()), QColor(255, 255, 255, alpha))

    def _bands(self, rect: QRect) -> list[QRect]:
        """The plot area cut into three strips, one for each colour channel, with a small gap between."""
        gap = 3
        height = (rect.height() - 2 * gap) // 3
        return [QRect(rect.left(), rect.top() + i * (height + gap), rect.width(), height) for i in range(3)]

    def _draw_grid(self, painter: QPainter, rect: QRect) -> None:
        if self._style == "smooth" and (self._rgb_histogram or self._luminance_histogram):
            return          # its value bars, with their numbers, are drawn with the curve (_draw_value_bars)
        painter.setPen(QPen(QColor(THEME.text_muted), 1, Qt.PenStyle.DotLine))
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            x = rect.left() + fraction * rect.width()
            painter.drawLine(int(x), rect.top(), int(x), rect.bottom())
        if self._mode == "color" and self._split and self._rgb_histogram:
            for band in self._bands(rect):
                painter.drawLine(band.left(), band.bottom(), band.right(), band.bottom())
        else:
            for fraction in (0.0, 0.5, 1.0):
                y = rect.top() + fraction * rect.height()
                painter.drawLine(rect.left(), int(y), rect.right(), int(y))

        font = painter.font()
        font.setPointSize(THEME.font_size_small)
        painter.setFont(font)
        painter.setPen(QColor(THEME.text_secondary))
        label_y = rect.bottom() + 2
        mid_value = (self._zoom_min + self._zoom_max) / 2
        painter.drawText(
            QRect(rect.left(), label_y, _AXIS_LABEL_WIDTH, _AXIS_LABEL_HEIGHT),
            int(Qt.AlignmentFlag.AlignLeft), self._axis_text(self._zoom_min),
        )
        painter.drawText(
            QRect(int(rect.center().x() - _AXIS_LABEL_WIDTH / 2), label_y, _AXIS_LABEL_WIDTH, _AXIS_LABEL_HEIGHT),
            int(Qt.AlignmentFlag.AlignHCenter), self._axis_text(mid_value),
        )
        painter.drawText(
            QRect(rect.right() - _AXIS_LABEL_WIDTH, label_y, _AXIS_LABEL_WIDTH, _AXIS_LABEL_HEIGHT),
            int(Qt.AlignmentFlag.AlignRight), self._axis_text(self._zoom_max),
        )

    def _series_points(self, rect: QRect, counts: list[int], peak: float) -> list[tuple[float, float]]:
        lo = max(0, int(math.floor(self._zoom_min)))
        hi = min(len(counts) - 1, int(math.ceil(self._zoom_max)))
        if hi <= lo:
            return []
        scale = math.log1p if self._log else math.sqrt  # a log height keeps the thin tails visible; the square root is the gentler default
        top = scale(peak) or 1.0
        return [
            (self._x_for_value(rect, i), rect.bottom() - (scale(counts[i]) / top) * rect.height())
            for i in range(lo, hi + 1)
        ]

    @staticmethod
    def _curve_to(path: QPainterPath, points: list[tuple[float, float]]) -> None:
        """Carry the path through the points as a smooth curve (a Catmull-Rom spline, as cubic Beziers), from where the path is now to the last point."""
        n = len(points)
        for i in range(n - 1):
            p0, p1, p2, p3 = points[max(0, i - 1)], points[i], points[i + 1], points[min(n - 1, i + 2)]
            path.cubicTo(p1[0] + (p2[0] - p0[0]) / 6.0, p1[1] + (p2[1] - p0[1]) / 6.0, p2[0] - (p3[0] - p1[0]) / 6.0, p2[1] - (p3[1] - p1[1]) / 6.0, p2[0], p2[1])

    def _fill_series(self, painter: QPainter, rect: QRect, points: list[tuple[float, float]], color_hex: str, smooth: bool = False) -> None:
        if not points:
            return
        path = QPainterPath()
        path.moveTo(points[0][0], rect.bottom())
        if smooth:
            path.lineTo(points[0][0], points[0][1])
            self._curve_to(path, points)
        else:
            for x, y in points:
                path.lineTo(x, y)
        path.lineTo(points[-1][0], rect.bottom())
        path.closeSubpath()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(color_hex)))
        painter.drawPath(path)

    def _stroke_series(self, painter: QPainter, points: list[tuple[float, float]], color_hex: str, smooth: bool = False) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if smooth and points:
            path = QPainterPath()
            path.moveTo(*points[0])
            self._curve_to(path, points)
            painter.setPen(QPen(QColor(color_hex), 1.6))
            painter.drawPath(path)
            return
        painter.setPen(QPen(QColor(color_hex), 1))
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

    def _draw_line(self, painter: QPainter, rect: QRect, value: float, color: QColor, style, width: int) -> None:
        if value < self._zoom_min or value > self._zoom_max:
            return
        x = self._x_for_value(rect, value)
        painter.setPen(QPen(color, width, style))
        painter.drawLine(int(x), rect.top(), int(x), rect.bottom())
