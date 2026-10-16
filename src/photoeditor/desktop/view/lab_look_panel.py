from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ...features.lablook import logic as ll
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200
_LABEL_WIDTH = 120


class LabLookToolPanel(CollapsiblePanel):
    """Lab Look, under Print Response: Fade, Glow and a warm or cool balance for the shadows, midtones and highlights separately (features/lablook/logic.py) - the
    character a lab's scanner adds. Same two-tier preview / full-recompute split as the other tone modules, carrying all eight values in one signal pair."""

    changed = pyqtSignal(object)
    preview_requested = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Lab Look",
            help_text=(
                "The character a lab's scanner adds to a print. Fade works on the shadows: + compresses them (smoother, less detail, a lifted matte black with no pure black), - expands them (a deeper black, more shadow contrast). Glow works on the highlights: + compresses them (smoother, softer, less detail, the midtones rise a little to make room), - expands them (a starker look with more highlight detail). The balance sliders warm (+) or cool (-) the shadows, midtones and highlights on their own, and shift them toward magenta (+) or green (-): a lab look is rarely one cast over everything, often it is cooler in the shadows and warmer in the midtones. Double-click a slider to reset it."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)
        self._rows: dict[str, SliderRow] = {}

        def add(key: str, label: str, tip: str, low: float, high: float) -> None:
            row = SliderRow(label, min_value=low, max_value=high, reset_value=0.0, decimals=2, step=0.01, label_width=_LABEL_WIDTH)
            row.setToolTip(tip)
            row.value_changed.connect(self._on_value_changed)
            self._rows[key] = row
            body.addWidget(row)

        add("lab_fade", "Fade", "+ compresses the shadows: smoother, less detail, a lifted matte black with no pure black; - expands them: a deeper black and more shadow contrast", *ll.FADE_RANGE)
        add("lab_glow", "Glow", "+ compresses the highlights: smoother, softer, less detail, with the midtones rising a little to make room; - expands them: a starker look with more highlight detail. The black and the top stay where they are", *ll.GLOW_RANGE)
        title = QLabel("BALANCE BY TONE")
        title.setProperty("role", "subtitle")
        body.addWidget(title)
        for range_name, suffix in (("shadows", "Shadows"), ("mids", "Midtones"), ("highs", "Highlights")):
            add(f"lab_by_{range_name}", f"Warmth: {suffix}", f"Warmer (+) or cooler (-), in the {suffix.lower()} only", *ll.BALANCE_RANGE)
        for range_name, suffix in (("shadows", "Shadows"), ("mids", "Midtones"), ("highs", "Highlights")):
            add(f"lab_gm_{range_name}", f"Magenta: {suffix}", f"Toward magenta (+) or green (-), in the {suffix.lower()} only", *ll.BALANCE_RANGE)

        self._pending_preview: tuple | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._preview_timer.timeout.connect(self._flush_pending_preview)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._settle_timer.timeout.connect(lambda: self.changed.emit(self._current()))

    def _current(self) -> tuple[float, ...]:
        return tuple(self._rows[key].value() for key in ll.KEYS)

    def reset(self) -> None:
        """Back to neutral without emitting anything - used when a new file is opened, since the controller has already reset its own state."""
        self._settle_timer.stop()
        self._pending_preview = None
        self.set_values(tuple(0.0 for _ in ll.KEYS))

    def set_values(self, values) -> None:
        """Sync the sliders without emitting anything - used by reset() and after a history revert."""
        for key, value in zip(ll.KEYS, values):
            self._rows[key].set_value(value)

    def _on_value_changed(self, _value: float) -> None:
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
