from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200


class ColorToolPanel(CollapsiblePanel):
    """A third sibling under the Negative tab, below Negative and Crop &
    Rotate - basic color adjustments (features/color/logic.py) for a
    (usually just-inverted) negative scan: Saturation, Temperature, and
    Tint. Same two-tier preview/full-recompute split as Exposure and Tone
    Curve, just carrying all three values together in one signal instead
    of adding three separate preview/changed signal pairs."""

    color_changed = pyqtSignal(float, float, float)
    preview_requested = pyqtSignal(float, float, float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Color",
            help_text=(
                "Basic color adjustments. Saturation: -1 is grayscale, +1 "
                "doubles color intensity. Temperature: warms (+) or cools "
                "(-) the image. Tint: shifts toward magenta (+) or green "
                "(-). Double-click a slider to reset it to 0."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)

        rows = QVBoxLayout()
        rows.setSpacing(THEME.space_sm)

        self._saturation = SliderRow("Saturation")
        self._saturation.value_changed.connect(self._on_value_changed)
        rows.addWidget(self._saturation)

        self._temperature = SliderRow("Temperature")
        self._temperature.value_changed.connect(self._on_value_changed)
        rows.addWidget(self._temperature)

        self._tint = SliderRow("Tint")
        self._tint.value_changed.connect(self._on_value_changed)
        rows.addWidget(self._tint)

        body.addLayout(rows)

        self._pending_preview: tuple[float, float, float] | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._preview_timer.timeout.connect(self._flush_pending_preview)

        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._settle_timer.timeout.connect(self._on_settled)

    def _current(self) -> tuple[float, float, float]:
        return (self._saturation.value(), self._temperature.value(), self._tint.value())

    def reset(self) -> None:
        """Back to all-zero without emitting anything - used when a new
        file is opened, since the controller has already reset its own
        color state as part of that load."""
        self._settle_timer.stop()
        self._pending_preview = None
        self.set_values(0.0, 0.0, 0.0)

    def set_values(self, saturation: float, temperature: float, tint: float) -> None:
        """Sync the three sliders without emitting anything - used by reset() and after a history revert."""
        self._saturation.set_value(saturation)
        self._temperature.set_value(temperature)
        self._tint.set_value(tint)

    def _on_value_changed(self, _value: float) -> None:
        values = self._current()
        self._request_preview(values)
        self._settle_timer.start()

    def _request_preview(self, values: tuple[float, float, float]) -> None:
        if self._preview_timer.isActive():
            self._pending_preview = values
            return
        self.preview_requested.emit(*values)
        self._preview_timer.start()

    def _flush_pending_preview(self) -> None:
        if self._pending_preview is not None:
            values, self._pending_preview = self._pending_preview, None
            self.preview_requested.emit(*values)
            self._preview_timer.start()

    def _on_settled(self) -> None:
        self.color_changed.emit(*self._current())
