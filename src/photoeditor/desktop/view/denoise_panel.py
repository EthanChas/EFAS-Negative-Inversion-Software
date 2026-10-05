from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget

from ...features.denoise.logic import CHROMA_DENOISE_MAX
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200


class ChromaDenoiseToolPanel(CollapsiblePanel):
    """Chroma Denoise in the Correction tab - edge-aware smoothing of color
    noise only (features/denoise/logic.py, ported from NegPy), leaving the
    luminance detail alone. Same two-tier preview/full-recompute split as
    the other tools."""

    changed = pyqtSignal(float)
    preview_requested = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Chroma Denoise",
            help_text=(
                "Smooths the blotchy color speckle of film grain and high ISO without softening detail: "
                "only the color channels are filtered, edge-aware, so a saturated object's color doesn't "
                "bleed into its surroundings. 0 is off. Double-click the slider to reset it."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)

        self._slider = SliderRow("Amount", min_value=0.0, max_value=CHROMA_DENOISE_MAX, reset_value=0.0)
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
