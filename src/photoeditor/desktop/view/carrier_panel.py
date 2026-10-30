from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QLabel, QWidget

from ...features.carrier import logic as car
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200
_LABEL_WIDTH = 100


class CarrierPanel(CollapsiblePanel):
    """Negative Carrier, under Finishing: the black rebate frame of a filed-out negative carrier (features/carrier/logic.py, after NegPy's). The values travel as one dict, with the same
    two-tier preview / full-recompute split as the other modules."""

    changed = pyqtSignal(object)
    preview_requested = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Negative Carrier",
            help_text=(
                "A negative carrier whose aperture is filed larger than the frame prints the film's own rebate: the dark edge of the film, then a margin of bare paper, with the uneven edge of "
                "the filed metal. This simulates it, as NegPy does. Width is how wide the rebate prints, in mm on a 30 cm print (0 = off); it scales with the picture, so a preview and an "
                "export look the same. Rough is how ragged the filed edge is. Corner is how round the filed aperture's corners are. Flare is the bright line light makes along the filed "
                "bevel. The pattern is fixed: the same photo always prints the same edge. It works on the finished, cropped picture, before the border. Double-click a slider to reset it."
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

        add("carrier_width", "Width (mm)", "How wide the rebate prints, in mm on a 30 cm print (0 = off)", *car.WIDTH_RANGE, 0.0)
        add("carrier_rough", "Rough", "How ragged the filed edge is", 0.0, 1.0, car.DEFAULTS["carrier_rough"])
        add("carrier_corner", "Corner", "How round the filed aperture's corners are", 0.0, 1.0, car.DEFAULTS["carrier_corner"])
        add("carrier_flare", "Flare", "The bright line light makes along the filed bevel (0 = none)", 0.0, 1.0, car.DEFAULTS["carrier_flare"])
        note = QLabel("A simulation of a filed negative carrier, after NegPy's.")
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
        self.set_values(car.DEFAULTS)

    def set_values(self, values) -> None:
        """Sync the sliders without emitting anything - used by reset() and after a history revert."""
        for key, row in self._rows.items():
            row.blockSignals(True)
            row.set_value(float(values.get(key, car.DEFAULTS[key])))
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
