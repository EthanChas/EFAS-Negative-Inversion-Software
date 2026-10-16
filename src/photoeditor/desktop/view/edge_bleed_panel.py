from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

from ...features.edgebleed import logic as eb
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200
_LABEL_WIDTH = 100


class EdgeBleedPanel(CollapsiblePanel):
    """Edge Bleed, under Flat Field in the Negative tab: four tools for light that spills in from the clear film round a frame (features/edgebleed/logic.py). Holder and sprocket
    fill, Edge bleed repair (with an automatic estimate of its strength) and Edge gradient dodge work on the raw scan before the negative is converted; the Border mask is laid
    over the finished picture. The values travel as one dict, with the same two-tier preview / full-recompute split as the tone modules."""

    changed = pyqtSignal(object)
    preview_requested = pyqtSignal(object)
    estimate_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Edge Bleed",
            help_text=(
                "Light from the clear film round the frame, the gaps in the holder and the sprocket holes spills into the picture's edges and lifts them. Flat Field cannot fix "
                "that (it evens out light that falls off smoothly across the whole frame). Fill holder and sprockets paints whatever sits outside the picture but is not clear "
                "film (a holder's dark edge, a bright hole) with the film base, so it cannot spill light in or fool the metering. Edge bleed repair takes the light the border "
                "spreads into the picture off again: Strength is how much, Auto fits it from how the picture's own edge brightens, Reach is how far it spreads. Edge gradient dodge "
                "flattens each edge's brightness to the level just beyond Reach; it works even with no clear border, but a bright scene edge looks like bleed to it. Border mask "
                "lays a soft black, grey or white band over the outer edge for what is left, and can be kept out of the metering. The repair and the fill work from the edge of your crop "
                "(or, with no crop, a clear film border found round the picture), so crop to the picture first; the dodge does not need either. Double-click a slider to reset it."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)
        self._rows: dict[str, SliderRow] = {}
        self._status = QLabel("Open a photo to look for its film border.")
        self._status.setProperty("role", "hint")
        self._status.setWordWrap(True)
        body.addWidget(self._status)

        def add(key: str, label: str, tip: str, low: float, high: float, reset: float, decimals: int = 2, step: float = 0.01) -> SliderRow:
            row = SliderRow(label, min_value=low, max_value=high, reset_value=reset, decimals=decimals, step=step, label_width=_LABEL_WIDTH)
            row.setToolTip(tip)
            row.value_changed.connect(self._on_value_changed)
            self._rows[key] = row
            body.addWidget(row)
            return row

        def subtitle(text: str) -> None:
            title = QLabel(text)
            title.setProperty("role", "subtitle")
            body.addWidget(title)

        subtitle("ON THE SCAN")
        add("edge_holder", "Fill holder", "Paint what is outside the picture but not clear film (a holder's dark edge, a sprocket hole, an edge code) with the film base", 0.0, 1.0, 0.0)
        add("edge_bleed", "Bleed repair", "How much of the light the border spreads into the picture is taken off again (needs a clear film border)", 0.0, 1.0, 0.0)
        row = QHBoxLayout()
        row.addStretch(1)
        self._auto = QPushButton("Auto strength")
        self._auto.setToolTip("Set the Bleed repair strength from how the picture's own edge brightens toward the clear border. A guess: a bright scene edge reads as bleed")
        self._auto.clicked.connect(self.estimate_requested)
        row.addWidget(self._auto)
        body.addLayout(row)
        add("edge_dodge", "Edge dodge", "Flatten each edge's brightness to the level just beyond Reach (works without a clear border)", 0.0, 1.0, 0.0)
        add("edge_reach", "Reach", "How far in from the edge the bleed spreads and the dodge works, as a share of the picture's shorter side", *eb.REACH_RANGE, eb.DEFAULTS["edge_reach"])

        subtitle("ON THE PICTURE")
        add("edge_mask", "Mask width", "A soft band over the picture's outer edge, as a share of its shorter side (0 is off)", *eb.MASK_RANGE, 0.0, decimals=3, step=0.005)
        add("edge_feather", "Mask feather", "0 is a hard edge, 1 fades the whole band", 0.0, 1.0, eb.DEFAULTS["edge_feather"])
        colour_row = QHBoxLayout()
        colour_label = QLabel("Mask colour")
        colour_label.setFixedWidth(_LABEL_WIDTH)
        colour_row.addWidget(colour_label)
        self._colour = QComboBox()
        for key in eb.MASK_COLOURS:
            self._colour.addItem(eb.MASK_COLOUR_LABELS[key], key)
        self._colour.currentIndexChanged.connect(self._on_value_changed)
        colour_row.addWidget(self._colour, 1)
        body.addLayout(colour_row)
        self._meter = QCheckBox("Leave the band out of the metering")
        self._meter.setChecked(True)
        self._meter.setToolTip("The conversion reads the picture without the masked band, so a dark or clipped edge cannot pull the black and white points")
        self._meter.toggled.connect(self._on_value_changed)
        body.addWidget(self._meter)

        self._pending_preview: dict | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._preview_timer.timeout.connect(self._flush_pending_preview)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._settle_timer.timeout.connect(lambda: self.changed.emit(self._current()))

    def _current(self) -> dict:
        values = {key: self._rows[key].value() for key in eb.KEYS if key in self._rows}
        values["edge_mask_color"] = self._colour.currentData() or "black"
        values["edge_mask_meter"] = self._meter.isChecked()
        return values

    def values(self) -> dict:
        return self._current()

    def reset(self) -> None:
        """Back to neutral without emitting anything - used when a new file is opened, since the controller has already reset its own state."""
        self._settle_timer.stop()
        self._pending_preview = None
        self.set_values(eb.DEFAULTS)

    def set_values(self, values) -> None:
        """Sync the controls without emitting anything - used by reset() and after a history revert."""
        for key, row in self._rows.items():
            row.blockSignals(True)
            row.set_value(float(values.get(key, eb.DEFAULTS[key])))
            row.blockSignals(False)
        self._colour.blockSignals(True)
        self._colour.setCurrentIndex(max(0, self._colour.findData(values.get("edge_mask_color", "black"))))
        self._colour.blockSignals(False)
        self._meter.blockSignals(True)
        self._meter.setChecked(bool(values.get("edge_mask_meter", True)))
        self._meter.blockSignals(False)

    def set_strength(self, value: float) -> None:
        """Put the Bleed repair slider at `value` and apply it (the Auto strength button's answer)."""
        self._rows["edge_bleed"].set_value(float(value))
        self._on_value_changed()

    def show_status(self, text: str) -> None:
        self._status.setText(text)

    def _on_value_changed(self, _value=None) -> None:
        values = self._current()
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
