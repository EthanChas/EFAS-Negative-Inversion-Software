from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget

from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33  # ~30fps cap for the cheap image-only preview, same as Exposure
_SETTLE_DEBOUNCE_MS = 200


class ContrastToolPanel(CollapsiblePanel):
    """Contrast under WB Correction, between Exposure and Tone Curve - a
    smooth S-curve (features/contrast/logic.py): positive deepens darks and
    brightens lights around an unmoved midpoint, negative flattens. Same
    two-tier preview/full-recompute split as the other WB Correction tools."""

    changed = pyqtSignal(float)
    preview_requested = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Contrast",
            help_text=(
                "Positive values add contrast (darks darker, lights lighter, midtones stay put); negative "
                "values flatten the image. For finer control of individual tones use Tone Curve. "
                "Double-click the slider to reset it to 0."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)

        self._slider = SliderRow("Contrast")
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
        """Back to 0 without emitting anything - used when a new file is
        opened, since the controller has already reset (or restored) its own
        contrast as part of that load."""
        self._settle_timer.stop()
        self._pending_preview = None
        self.set_value(0.0)

    def set_value(self, value: float) -> None:
        """Sync the slider without emitting anything - used by reset() and
        after a history revert."""
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
