from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33  # ~30fps cap for the cheap image-only preview, same as Exposure
_SETTLE_DEBOUNCE_MS = 200


class ShadowsHighlightsToolPanel(CollapsiblePanel):
    """A third sibling under WB Correction, below Tone Curve - lifts or
    darkens shadows and highlights independently of the rest of the tonal
    range (features/shadows_highlights/logic.py). Same two-tier preview/
    full-recompute split as Exposure/Tone Curve/Color, carrying both
    values in one signal pair the same way Color carries three."""

    changed = pyqtSignal(float, float)  # shadows, highlights
    preview_requested = pyqtSignal(float, float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Shadows & Highlights",
            help_text=(
                "Shadows: brightens (+) or darkens (-) the darkest tones. "
                "Highlights: brightens (+) or darkens (-) the brightest "
                "tones. Midtones are left close to untouched either way. "
                "Double-click a slider to reset it to 0."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)

        rows = QVBoxLayout()
        rows.setSpacing(THEME.space_sm)

        self._shadows = SliderRow("Shadows")
        self._shadows.value_changed.connect(self._on_value_changed)
        rows.addWidget(self._shadows)

        self._highlights = SliderRow("Highlights")
        self._highlights.value_changed.connect(self._on_value_changed)
        rows.addWidget(self._highlights)

        body.addLayout(rows)

        self._pending_preview: tuple[float, float] | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._preview_timer.timeout.connect(self._flush_pending_preview)

        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._settle_timer.timeout.connect(self._on_settled)

    def _current(self) -> tuple[float, float]:
        return (self._shadows.value(), self._highlights.value())

    def reset(self) -> None:
        """Back to all-zero without emitting anything - used when a new
        file is opened, since the controller has already reset its own
        shadows/highlights state as part of that load."""
        self._settle_timer.stop()
        self._pending_preview = None
        self.set_values(0.0, 0.0)

    def set_values(self, shadows: float, highlights: float) -> None:
        """Sync both sliders without emitting anything - used by reset()
        and after a history revert."""
        self._shadows.set_value(shadows)
        self._highlights.set_value(highlights)

    def _on_value_changed(self, _value: float) -> None:
        values = self._current()
        self._request_preview(values)
        self._settle_timer.start()

    def _request_preview(self, values: tuple[float, float]) -> None:
        if self._preview_timer.isActive():
            self._pending_preview = values
            return
        self.preview_requested.emit(*values)
        self._preview_timer.start()

    def _flush_pending_preview(self) -> None:
        if self._pending_preview is not None:
            values, self._pending_preview = self._pending_preview, None
            self.preview_requested.emit(*values)
            self._preview_timer.start()

    def _on_settled(self) -> None:
        self.changed.emit(*self._current())
