from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ...features.edgecolor import logic as ec
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200
_LABEL_WIDTH = 100


class EdgeColorPanel(CollapsiblePanel):
    """Edge Color, under Color: a tint, a warmth and a brightness correction that grows toward the picture's edges (features/edgecolor/logic.py) - for a flash or a lens that lit the
    middle of the frame and left the edges to a room's own light (green fluorescent edges, orange tungsten ones). Auto measures the outer band against the middle. The values travel as
    one dict, with the same two-tier preview / full-recompute split as the other colour modules."""

    changed = pyqtSignal(object)
    preview_requested = pyqtSignal(object)
    auto_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Edge Color",
            help_text=(
                "Corrects a colour or brightness difference that grows toward the edges of the picture: a flash that lit the middle and left the edges to the room's own light (a green "
                "edge from fluorescent tubes, an orange one from tungsten bulbs), a lens that darkens its corners. Flat Field cannot do this: it corrects the scanner's light, and this is "
                "in the picture. Tint shifts the edges toward magenta (+) or green (-), Warmth toward yellow (+) or blue (-), Light makes them brighter (+) or darker (-). Size is where the "
                "correction starts, from the centre (0) to the edge (1); Shape is 0 for an ellipse (a flash's falloff) to 1 for an even band round all four sides. Auto compares the colour of the "
                "outer band with that of the middle of the picture and sets Tint and Warmth to match them (press it again to refine); it leaves Light to you, since a picture often has "
                "bright or dark things at its edges. It works on the cropped picture, so crop off the film's "
                "border first. Double-click a slider to reset it."
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

        add("ec_tint", "Tint", "At the edges: toward magenta (+) or green (-)", -1.0, 1.0, 0.0)
        add("ec_warmth", "Warmth", "At the edges: toward yellow (+) or blue (-)", -1.0, 1.0, 0.0)
        add("ec_light", "Light", "At the edges: brighter (+) or darker (-)", -1.0, 1.0, 0.0)
        add("ec_size", "Size", "Where the correction starts, from the centre (0) to the edge (1): a bigger Size leaves more of the middle alone", *ec.SIZE_RANGE, ec.DEFAULTS["ec_size"])
        add("ec_shape", "Shape", "0 follows an ellipse (a flash's falloff); 1 follows the picture's rectangle, an even band round all four sides", 0.0, 1.0, 0.0)
        row = QHBoxLayout()
        row.addStretch(1)
        self._auto = QPushButton("Auto match the colour")
        self._auto.setToolTip("Set Tint and Warmth so the outer band of the picture matches the colour of its middle (press again to refine). Light stays as you set it")
        self._auto.clicked.connect(self.auto_requested)
        row.addWidget(self._auto)
        body.addLayout(row)

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
        self.set_values(ec.DEFAULTS)

    def set_values(self, values) -> None:
        """Sync the sliders without emitting anything - used by reset() and after a history revert."""
        for key, row in self._rows.items():
            row.blockSignals(True)
            row.set_value(float(values.get(key, ec.DEFAULTS[key])))
            row.blockSignals(False)

    def apply_suggestion(self, values: dict) -> None:
        """Put Auto's answer on the sliders and apply it."""
        for key in ("ec_tint", "ec_warmth", "ec_light"):
            if key in values:
                self._rows[key].blockSignals(True)
                self._rows[key].set_value(float(values[key]))
                self._rows[key].blockSignals(False)
        self._on_value_changed()

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
