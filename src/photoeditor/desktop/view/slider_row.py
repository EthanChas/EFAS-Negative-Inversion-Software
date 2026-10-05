from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QDoubleSpinBox, QHBoxLayout, QLabel, QSlider, QWidget

from ...theme.tokens import THEME

_SLIDER_STEPS = 100  # slider units per 1.0 of range


class ResettableSlider(QSlider):
    """A QSlider that snaps back to a fixed reset position on double-click -
    same convention as the Exposure slider's own reset. reset_to is a raw
    slider unit (not a value in the row's own min..max span)."""

    def __init__(self, reset_to: int = 0, parent: QWidget | None = None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._reset_to = reset_to

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
    ):
        super().__init__(parent)
        self._min = -value_range if min_value is None else min_value
        self._max = value_range if max_value is None else max_value
        self._reset_value = reset_value
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(THEME.space_sm)

        name = QLabel(label)
        name.setFixedWidth(80)
        row.addWidget(name)

        self._updating = False

        self._slider = ResettableSlider(reset_to=self._to_slider(self._reset_value))
        self._slider.setRange(0, _SLIDER_STEPS)
        self._slider.setValue(self._to_slider(self._reset_value))
        self._slider.valueChanged.connect(self._on_slider_changed)
        row.addWidget(self._slider, 1)

        self._spin = QDoubleSpinBox()
        self._spin.setRange(self._min, self._max)
        self._spin.setSingleStep(step)
        self._spin.setDecimals(decimals)
        self._spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._spin.setValue(self._reset_value)
        self._spin.valueChanged.connect(self._on_spin_changed)
        row.addWidget(self._spin)

    def _to_slider(self, value: float) -> int:
        span = self._max - self._min
        return round((value - self._min) / span * _SLIDER_STEPS) if span else 0

    def _from_slider(self, raw: int) -> float:
        return self._min + (raw / _SLIDER_STEPS) * (self._max - self._min)

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
