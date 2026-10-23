from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QLabel, QPushButton, QWidget

from ...features.grainsharp import logic as gs
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200
_LABEL_WIDTH = 100


class GrainSharpeningPanel(CollapsiblePanel):
    """Grain Sharpening, under Detail: makes the film's grain crisper (features/grainsharp/logic.py). The values travel as one dict, with the same two-tier preview / full-recompute
    split as the other modules. "Match My Grain" sets Size to the width the Grain Report measures in the open photo."""

    changed = pyqtSignal(object)
    preview_requested = pyqtSignal(object)
    match_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Grain Sharpening",
            help_text=(
                "Makes the film's own grain crisper. A camera scan often records grain soft, because the lens, the sensor and the demosaicing blur a texture only a pixel or two wide. This raises the "
                "contrast of the texture at the size of the grain, and nothing larger, so the picture's own detail is left to Sharpening. It adds no grain: where the scan shows a flat grey "
                "there is nothing to sharpen. Amount is how much crisper (0 is off). Size is the grain's width in scan pixels (Match My Grain sets it from the Grain Report's measurement; "
                "1 to 2 for most camera scans). Midtones: 0 treats every tone alike, 1 leaves the deepest shadows and the highlights as they were. Lightness only; colour is kept. "
                "The grain is below a pixel on the small editing preview, so judge it at 100% zoom: the export is made the same way. Double-click a slider to reset it."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)
        self._rows: dict[str, SliderRow] = {}

        def add(key: str, label: str, tip: str, low: float, high: float, reset: float, decimals: int = 2) -> None:
            row = SliderRow(label, min_value=low, max_value=high, reset_value=reset, decimals=decimals, step=0.01, label_width=_LABEL_WIDTH)
            row.setToolTip(tip)
            row.value_changed.connect(self._on_value_changed)
            self._rows[key] = row
            body.addWidget(row)

        add("gs_amount", "Amount", "How much crisper the grain is made (0 = off)", 0.0, 1.0, 0.0)
        add("gs_size", "Size (px)", "The grain's width in scan pixels", *gs.SIZE_RANGE, gs.DEFAULTS["gs_size"])
        add("gs_midtones", "Midtones", "0 = every tone alike, 1 = only the midtones", 0.0, 1.0, gs.DEFAULTS["gs_midtones"])
        self._match = QPushButton("Match My Grain")
        self._match.setToolTip("Measure the grain in the open photo (as the Grain Report does) and set Size to its width")
        self._match.clicked.connect(self.match_requested)
        body.addWidget(self._match)
        self._note = QLabel("Judge it at 100% zoom: on the small preview the grain is under a pixel.")
        self._note.setProperty("role", "hint")
        self._note.setWordWrap(True)
        body.addWidget(self._note)

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

    def set_note(self, text: str) -> None:
        self._note.setText(text)

    def apply_size(self, size: float) -> None:
        """Set Size from outside (Match My Grain) and apply it as a change."""
        row = self._rows["gs_size"]
        row.set_value(float(size))
        self._on_value_changed()

    def reset(self) -> None:
        """Back to neutral without emitting anything - used when a new file is opened, since the controller has already reset its own state."""
        self._settle_timer.stop()
        self._pending_preview = None
        self.set_values(gs.DEFAULTS)

    def set_values(self, values) -> None:
        """Sync the sliders without emitting anything - used by reset() and after a history revert."""
        for key, row in self._rows.items():
            row.blockSignals(True)
            row.set_value(float(values.get(key, gs.DEFAULTS[key])))
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
