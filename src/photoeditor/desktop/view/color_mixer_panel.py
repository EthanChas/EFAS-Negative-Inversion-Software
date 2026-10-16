from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPushButton, QWidget

from ...features.colormix import logic as cm
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200
_LABEL_WIDTH = 80
# the swatch shown for each colour range (display colours, not the range's centre hue)
_SWATCH = {"red": "#d9453d", "orange": "#e8913a", "yellow": "#e3c93f", "green": "#4fae5a", "aqua": "#3ab5b8", "blue": "#4a7fd6", "purple": "#8a5fc4", "magenta": "#cc4fa0"}


class ColorMixerToolPanel(CollapsiblePanel):
    """Color Mixer, under Color: Vibrance, and Hue, Saturation and Lightness for each of eight colour ranges (features/colormix/logic.py), worked in OKLCH so a colour moves
    without dragging its lightness or hue along. Same two-tier preview / full-recompute split as the other tone modules, carrying all values in one signal pair."""

    changed = pyqtSignal(object)
    preview_requested = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Color Mixer",
            help_text=(
                "Vibrance raises the colour of the muted parts of the picture more than the vivid ones, and leaves skin tones and greys alone (- mutes). Below it, pick one of eight "
                "colour ranges and change its Hue (turn it along the colour wheel), Saturation (how colourful) and Lightness (how bright) on their own. The ranges blend into their "
                "neighbours and never touch a grey. A dot beside a swatch means that range has been changed. Double-click a slider to reset it."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)
        self._values = {k: 0.0 for k in cm.MIXER_PANEL_KEYS}
        self._vibrance = SliderRow("Vibrance", min_value=-1.0, max_value=1.0, reset_value=0.0, decimals=2, step=0.01, label_width=_LABEL_WIDTH)
        self._vibrance.setToolTip("Raises (+) or lowers (-) the colour of the muted parts more than the vivid ones; skin tones and greys are spared")
        self._vibrance.value_changed.connect(self._on_vibrance)
        body.addWidget(self._vibrance)

        title = QLabel("COLOUR RANGES")
        title.setProperty("role", "subtitle")
        body.addWidget(title)
        row = QHBoxLayout()
        row.setSpacing(THEME.space_sm)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._swatches: dict[str, QPushButton] = {}
        for band in cm.BANDS:
            button = QPushButton("")
            button.setCheckable(True)
            button.setFixedSize(22, 22)
            button.setToolTip(band.capitalize())
            button.clicked.connect(lambda _checked=False, b=band: self._select(b))
            self._group.addButton(button)
            self._swatches[band] = button
            row.addWidget(button)
        row.addStretch(1)
        body.addLayout(row)
        self._band = cm.BANDS[0]
        self._rows: dict[str, SliderRow] = {}
        for kind, label, tip in (("hue", "Hue", "Turns this colour range along the colour wheel"), ("sat", "Saturation", "How colourful this range is"),
                                 ("lum", "Lightness", "How bright this range is")):
            slider = SliderRow(label, min_value=-1.0, max_value=1.0, reset_value=0.0, decimals=2, step=0.01, label_width=_LABEL_WIDTH)
            slider.setToolTip(tip)
            slider.value_changed.connect(lambda value, k=kind: self._on_band_value(k, value))
            self._rows[kind] = slider
            body.addWidget(slider)

        self._pending_preview: dict | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._preview_timer.timeout.connect(self._flush_pending_preview)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._settle_timer.timeout.connect(lambda: self.changed.emit(dict(self._values)))
        self._select(cm.BANDS[0])
        self._paint_swatches()

    # ------------------------------------------------------------ the band shown
    def _select(self, band: str) -> None:
        self._band = band
        self._swatches[band].setChecked(True)
        for kind, slider in self._rows.items():
            slider.blockSignals(True)
            slider.set_value(self._values[f"mix_{kind}_{band}"])
            slider.blockSignals(False)
        self._paint_swatches()

    def _paint_swatches(self) -> None:
        for band, button in self._swatches.items():
            edited = any(abs(self._values[f"mix_{kind}_{band}"]) > 1e-9 for kind in ("hue", "sat", "lum"))
            ring = THEME.accent_primary if button.isChecked() else (THEME.text_secondary if edited else THEME.border_color)
            width = 3 if button.isChecked() else 2 if edited else 1
            button.setStyleSheet(f"QPushButton {{ background: {_SWATCH[band]}; border: {width}px solid {ring}; border-radius: 11px; }}")

    # ------------------------------------------------------------ values
    def values(self) -> dict:
        return dict(self._values)

    def reset(self) -> None:
        """Back to neutral without emitting anything - used when a new file is opened, since the controller has already reset its own state."""
        self._settle_timer.stop()
        self._pending_preview = None
        self.set_values({})

    def set_values(self, values) -> None:
        """Sync the sliders without emitting anything - used by reset() and after a history revert. `values` is a dict of the keys, or a sequence in KEYS order."""
        if not isinstance(values, dict):
            values = dict(zip(cm.MIXER_PANEL_KEYS, values))
        self._values = {k: float(values.get(k, 0.0)) for k in cm.MIXER_PANEL_KEYS}
        self._vibrance.blockSignals(True)
        self._vibrance.set_value(self._values["vibrance"])
        self._vibrance.blockSignals(False)
        self._select(self._band)

    def _on_vibrance(self, value: float) -> None:
        self._values["vibrance"] = float(value)
        self._emit_preview()

    def _on_band_value(self, kind: str, value: float) -> None:
        self._values[f"mix_{kind}_{self._band}"] = float(value)
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
