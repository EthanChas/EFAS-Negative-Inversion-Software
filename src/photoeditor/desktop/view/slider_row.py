from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QDoubleSpinBox, QHBoxLayout, QLabel, QSlider, QStyle, QStyleOptionSlider, QWidget

from ...theme.tokens import THEME

_SLIDER_STEPS = 100  # the Default theme's; the Modern theme has more stops across a span (THEME.slider_steps), so a slider moves smoothly


class ResettableSlider(QSlider):
    """A QSlider that snaps back to a fixed reset position on double-click -
    same convention as the Exposure slider's own reset. reset_to is a raw
    slider unit (not a value in the row's own min..max span)."""

    def __init__(self, reset_to: int = 0, parent: QWidget | None = None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._reset_to = reset_to

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Modern theme: a click on the groove puts the handle right there (and a drag carries on from it) instead of stepping a page at a time."""
        if THEME.style == "modern" and event.button() == Qt.MouseButton.LeftButton:
            option = QStyleOptionSlider()
            self.initStyleOption(option)
            handle = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self)
            if not handle.contains(event.position().toPoint()):
                groove = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, self)
                half = handle.width() // 2
                span = max(1, groove.width() - handle.width())
                self.setValue(QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), int(event.position().x()) - groove.x() - half, span))
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setValue(self._reset_to)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class SliderRow(QWidget):
    """A labeled slider+spinbox pair over a min..max span, kept in sync via
    a re-entrancy guard - the same pattern as ExposureToolPanel's own
    single slider, packaged so a panel with several of these (Color's
    Saturation/Temperature/Tint, Shadows & Highlights' two, Sharpening's
    three) doesn't duplicate that logic per slider.

    Double-click resets to `reset_value` (default 0.0) - for a tool like
    Sharpening whose sliders aren't centered on 0, pass the actual
    no-op/default value so double-click still means "reset", not
    "jump to a value outside the useful range"."""

    value_changed = pyqtSignal(float)

    def __init__(
        self,
        label: str,
        value_range: float = 1.0,
        min_value: float | None = None,
        max_value: float | None = None,
        reset_value: float = 0.0,
        decimals: int = 2,
        step: float = 0.01,
        parent: QWidget | None = None,
        label_width: int = 80,
        spin_min: float | None = None,
        spin_max: float | None = None,
    ):
        """`spin_min` and `spin_max` let the box beside the slider take values beyond the slider's own ends (typed in); the slider then rests at its end."""
        super().__init__(parent)
        self._min = -value_range if min_value is None else min_value
        self._max = value_range if max_value is None else max_value
        self._reset_value = reset_value
        self._steps = THEME.slider_steps
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(THEME.space_sm)

        self.label_text = label
        name = QLabel(label)
        name.setFixedWidth(label_width)
        row.addWidget(name)

        self._updating = False

        self._slider = ResettableSlider(reset_to=self._to_slider(self._reset_value))
        self._slider.setRange(0, self._steps)
        self._slider.setSingleStep(max(1, self._steps // 100))
        self._slider.setPageStep(self._steps // 10)
        self._slider.setValue(self._to_slider(self._reset_value))
        self._slider.valueChanged.connect(self._on_slider_changed)
        row.addWidget(self._slider, 1)

        self._spin = QDoubleSpinBox()
        self._spin.setRange(self._min if spin_min is None else spin_min, self._max if spin_max is None else spin_max)
        self._spin.setSingleStep(step)
        self._spin.setDecimals(decimals)
        self._spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._spin.setValue(self._reset_value)
        self._spin.valueChanged.connect(self._on_spin_changed)
        row.addWidget(self._spin)

    def _to_slider(self, value: float) -> int:
        span = self._max - self._min
        return round((value - self._min) / span * self._steps) if span else 0

    def _from_slider(self, raw: int) -> float:
        return self._min + (raw / self._steps) * (self._max - self._min)

    def apply_theme(self) -> None:
        """A theme change can change how many stops the slider has; the value it shows stays put."""
        if self._steps == THEME.slider_steps:
            return
        value = self.value()
        self._steps = THEME.slider_steps
        self._updating = True
        self._slider.setRange(0, self._steps)
        self._slider.setSingleStep(max(1, self._steps // 100))
        self._slider.setPageStep(self._steps // 10)
        self._slider._reset_to = self._to_slider(self._reset_value)
        self._slider.setValue(self._to_slider(value))
        self._updating = False

    def value(self) -> float:
        return self._spin.value()

    def set_value(self, value: float) -> None:
        self._updating = True
        self._slider.setValue(self._to_slider(value))
        self._spin.setValue(value)
        self._updating = False

    def _on_slider_changed(self, raw: int) -> None:
        if self._updating:
            return
        value = self._from_slider(raw)
        self._updating = True
        self._spin.setValue(value)
        self._updating = False
        self.value_changed.emit(value)

    def _on_spin_changed(self, value: float) -> None:
        if self._updating:
            return
        self._updating = True
        self._slider.setValue(self._to_slider(value))
        self._updating = False
        self.value_changed.emit(value)
