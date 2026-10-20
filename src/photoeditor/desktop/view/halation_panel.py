from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QLabel, QWidget

from ...features.halation import logic as hal
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200
_LABEL_WIDTH = 100


class HalationPanel(CollapsiblePanel):
    """Halation, under Color: a *simulated* soft red-orange glow round the brightest parts of the picture (features/halation/logic.py). The values travel as one dict, with the same
    two-tier preview / full-recompute split as the other colour modules."""

    changed = pyqtSignal(object)
    preview_requested = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Halation",
            help_text=(
                "Real film has halation: light bounces off the back of the film and exposes it again round bright highlights, as a red-orange glow. A scan of a negative already contains the "
                "film's own, so this module recovers nothing: it adds a SIMULATED glow, for a stronger look or when the capture lost some of it. It is off at Amount 0, and nothing turns "
                "it on for you. Amount is how strong the glow is. Radius is how far it spreads. Threshold is how bright a part must be to glow (lower lets more of the picture glow). "
                "Warmth goes from a neutral glow (0) to film's red-orange (1). It works on the finished, cropped picture and can only brighten. Double-click a slider to reset it."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)
        self._rows: dict[str, SliderRow] = {}

        def add(key: str, label: str, tip: str, low: float, high: float, reset: float) -> None:
            row = SliderRow(label, min_value=low, max_value=high, reset_value=reset, decimals=2, step=0.01, label_width=_LABEL_WIDTH)
            row.setToolTip(tip)
            row.value_changed.connect(self._on_value_changed)
            self._rows[key] = row
            body.addWidget(row)

        add("hal_amount", "Amount", "How strong the simulated glow is (0 = off)", 0.0, 1.0, 0.0)
        add("hal_radius", "Radius", "How far the glow spreads", 0.0, 1.0, hal.DEFAULTS["hal_radius"])
        add("hal_threshold", "Threshold", "How bright a part must be to glow: lower lets more of the picture glow", *hal.THRESHOLD_RANGE, hal.DEFAULTS["hal_threshold"])
        add("hal_warmth", "Warmth", "0 = a neutral glow, 1 = the red-orange of film's halation", 0.0, 1.0, hal.DEFAULTS["hal_warmth"])
        note = QLabel("Simulated: a film scan already has its own halation.")
        note.setProperty("role", "hint")
        note.setWordWrap(True)
        body.addWidget(note)

        self._pending_preview: dict | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._preview_timer.timeout.connect(self._flush_pending_preview)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._settle_timer.timeout.connect(lambda: self.changed.emit(self.values()))

    def values(self) -> dict:
        return {key: row.value() for key, row in self._rows.items()}

    def reset(self) -> None:
        """Back to neutral without emitting anything - used when a new file is opened, since the controller has already reset its own state."""
        self._settle_timer.stop()
        self._pending_preview = None
        self.set_values(hal.DEFAULTS)

    def set_values(self, values) -> None:
        """Sync the sliders without emitting anything - used by reset() and after a history revert."""
        for key, row in self._rows.items():
            row.blockSignals(True)
            row.set_value(float(values.get(key, hal.DEFAULTS[key])))
            row.blockSignals(False)

    def _on_value_changed(self, _value=None) -> None:
        values = self.values()
        if self._preview_timer.isActive():
            self._pending_preview = values
        else:
            self.preview_requested.emit(values)
            self._preview_timer.start()
        self._settle_timer.start()

    def _flush_pending_preview(self) -> None:
        if self._pending_preview is not None:
            values, self._pending_preview = self._pending_preview, None
            self.preview_requested.emit(values)
            self._preview_timer.start()
