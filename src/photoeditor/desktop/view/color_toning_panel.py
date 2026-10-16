from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ...features.colormix import logic as cm
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200
_LABEL_WIDTH = 80
_REGION_LABELS = {"shadows": "SHADOWS", "mids": "MIDTONES", "highs": "HIGHLIGHTS"}


class ColorToningToolPanel(CollapsiblePanel):
    """Color Toning, under Color: a tint for the shadows, the midtones and the highlights, each a Hue (degrees round the colour wheel, with a swatch showing the colour) and a
    Strength (features/colormix/logic.py). The tint is added in OKLab so the lightness stays put. Same two-tier preview / full-recompute split as the other colour modules,
    carrying all six values in one signal pair."""

    changed = pyqtSignal(object)
    preview_requested = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Color Toning",
            help_text=(
                "Tints the shadows, the midtones and the highlights toward a colour each - the split toning of a darkroom print. Hue picks the colour (the swatch shows it; 0 is "
                "a red-magenta, 90 a yellow, 180 a cyan-green, 270 a blue) and Strength how much; a region with no strength is left alone. The tint keeps the picture's lightness. "
                "It is applied last, after the Color Mixer and the Lab Look's scanner colour, so it sits on top of them. Double-click a slider to reset it."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)
        self._values = {k: 0.0 for k in cm.TONING_KEYS}
        self._hue: dict[str, SliderRow] = {}
        self._amount: dict[str, SliderRow] = {}
        self._swatch: dict[str, QLabel] = {}
        for region in cm.REGIONS:
            head = QHBoxLayout()
            head.setSpacing(THEME.space_sm)
            title = QLabel(_REGION_LABELS[region])
            title.setProperty("role", "subtitle")
            swatch = QLabel("")
            swatch.setFixedSize(34, 14)
            self._swatch[region] = swatch
            head.addWidget(title)
            head.addStretch(1)
            head.addWidget(swatch)
            body.addLayout(head)
            hue = SliderRow("Hue", min_value=0.0, max_value=360.0, reset_value=0.0, decimals=0, step=1.0, label_width=_LABEL_WIDTH)
            hue.setToolTip("The colour this region is tinted toward, in degrees round the colour wheel")
            hue.value_changed.connect(lambda value, r=region: self._on_value(f"tone_hue_{r}", value))
            amount = SliderRow("Strength", min_value=0.0, max_value=1.0, reset_value=0.0, decimals=2, step=0.01, label_width=_LABEL_WIDTH)
            amount.setToolTip("How strongly this region is tinted (0 leaves it alone)")
            amount.value_changed.connect(lambda value, r=region: self._on_value(f"tone_amt_{r}", value))
            self._hue[region], self._amount[region] = hue, amount
            body.addWidget(hue)
            body.addWidget(amount)

        self._pending_preview: dict | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._preview_timer.timeout.connect(self._flush_pending_preview)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._settle_timer.timeout.connect(lambda: self.changed.emit(dict(self._values)))
        self._paint_swatches()

    def _paint_swatches(self) -> None:
        for region, swatch in self._swatch.items():
            r, g, b = cm.tint_swatch(self._values[f"tone_hue_{region}"])
            on = self._values[f"tone_amt_{region}"] > 1e-9
            ring = THEME.text_secondary if on else THEME.border_color
            swatch.setStyleSheet(f"QLabel {{ background: rgb({r}, {g}, {b}); border: 2px solid {ring}; border-radius: 3px; }}")
            swatch.setToolTip(f"{int(round(self._values[f'tone_hue_{region}']))}°" + ("" if on else " (no strength: not applied)"))

    # ------------------------------------------------------------ values
    def values(self) -> dict:
        return dict(self._values)

    def reset(self) -> None:
        """Back to neutral without emitting anything - used when a new file is opened, since the controller has already reset its own state."""
        self._settle_timer.stop()
        self._pending_preview = None
        self.set_values({})

    def set_values(self, values) -> None:
        """Sync the sliders without emitting anything - used by reset() and after a history revert. `values` is a dict of the keys, or a sequence in TONING_KEYS order."""
        if not isinstance(values, dict):
            values = dict(zip(cm.TONING_KEYS, values))
        self._values = {k: float(values.get(k, 0.0)) for k in cm.TONING_KEYS}
        for region in cm.REGIONS:
            for slider, key in ((self._hue[region], f"tone_hue_{region}"), (self._amount[region], f"tone_amt_{region}")):
                slider.blockSignals(True)
                slider.set_value(self._values[key])
                slider.blockSignals(False)
        self._paint_swatches()

    def _on_value(self, key: str, value: float) -> None:
        self._values[key] = float(value)
        self._paint_swatches()
        self._emit_preview()

    def _emit_preview(self) -> None:
        values = dict(self._values)
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
