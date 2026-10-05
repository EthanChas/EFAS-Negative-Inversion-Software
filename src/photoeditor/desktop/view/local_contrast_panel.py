from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget

from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200


class LocalContrastToolPanel(CollapsiblePanel):
    """Local Contrast in the Correction tab - CLAHE on lightness (features/localcontrast/logic.py, after NegPy's): contrast is lifted
    tile by tile instead of across the whole picture, so texture pops without blowing the highlights or crushing the shadows. Same
    two-tier preview/full-recompute split as the other tools."""

    changed = pyqtSignal(float)
    preview_requested = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Local Contrast",
            help_text=(
                "Adds contrast locally (CLAHE, on lightness only): each part of the picture is stretched against its own surroundings, so "
                "texture in a hazy sky or a flat, low-contrast scan stands out without cranking the overall contrast and clipping the "
                "highlights or shadows. A little goes a long way - pushed far it looks \"HDR\". 0 is off. Double-click the slider to reset it."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)

        self._slider = SliderRow("Amount", min_value=0.0, max_value=1.0, reset_value=0.0)
        self._slider.value_changed.connect(self._on_value_changed)
        body.addWidget(self._slider)

        self._pending_preview: float | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._preview_timer.timeout.connect(self._flush_pending_preview)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._settle_timer.timeout.connect(self._on_settled)

    def reset(self) -> None:
        """Back to 0 without emitting anything - used when a new file is opened."""
        self._settle_timer.stop()
        self._pending_preview = None
        self.set_value(0.0)

    def set_value(self, value: float) -> None:
        self._slider.set_value(value)

    def _on_value_changed(self, value: float) -> None:
        if self._preview_timer.isActive():
            self._pending_preview = value
        else:
            self.preview_requested.emit(value)
            self._preview_timer.start()
        self._settle_timer.start()

    def _flush_pending_preview(self) -> None:
        if self._pending_preview is not None:
            value, self._pending_preview = self._pending_preview, None
            self.preview_requested.emit(value)
            self._preview_timer.start()

    def _on_settled(self) -> None:
        self.changed.emit(self._slider.value())
