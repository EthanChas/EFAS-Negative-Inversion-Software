from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QWidget

from ...features.finishing.logic import BORDER_COLORS, BORDER_MAX, DEFAULT_BORDER_COLOR, DEFAULT_VIGNETTE_SIZE
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200


class FinishingPanel(CollapsiblePanel):
    """Finishing, in the Watermark tab: a vignette, and a border or film-carrier frame round the picture (features/finishing/logic.py). They are
    looks of the print, applied over the finished crop, so they are not in the histogram."""

    changed = pyqtSignal(float, float, float, str, bool)
    preview_requested = pyqtSignal(float, float, float, str, bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Finishing",
            help_text=(
                "Vignette darkens the corners (positive) or lightens them (negative); Size is how far out from the centre the picture is left alone. "
                "Border adds a frame round the picture, a share of its shorter side, in white, black, grey or warm paper. Film carrier look draws "
                "the black, slightly ragged frame an unmasked negative carrier prints round the picture. These are applied last, over the finished "
                "crop, so they are not part of the histogram. Double-click a slider to reset it."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)
        self._vignette = SliderRow("Vignette", min_value=-1.0, max_value=1.0, reset_value=0.0)
        self._size = SliderRow("Size", min_value=0.0, max_value=1.0, reset_value=DEFAULT_VIGNETTE_SIZE)
        self._border = SliderRow("Border", min_value=0.0, max_value=BORDER_MAX, reset_value=0.0, decimals=3, step=0.005)
        self._vignette.setToolTip("Positive darkens the corners, negative lightens them")
        self._size.setToolTip("How much of the picture, from the centre outwards, the vignette leaves alone")
        self._border.setToolTip("The frame's width, as a share of the picture's shorter side")
        for row in (self._vignette, self._size, self._border):
            row.value_changed.connect(self._on_value_changed)
            body.addWidget(row)
        color_row = QHBoxLayout()
        color_row.setSpacing(THEME.space_sm)
        label = QLabel("Color")
        label.setFixedWidth(80)
        color_row.addWidget(label)
        self._color = QComboBox()
        for key in BORDER_COLORS:
            self._color.addItem(key.title(), key)
        self._color.currentIndexChanged.connect(self._on_value_changed)
        color_row.addWidget(self._color, 1)
        body.addLayout(color_row)
        self._carrier = QCheckBox("Film carrier look")
        self._carrier.setToolTip("A black, slightly ragged frame, like an unmasked negative carrier. It replaces the border colour.")
        self._carrier.toggled.connect(self._on_value_changed)
        body.addWidget(self._carrier)

        self._pending: tuple | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._preview_timer.timeout.connect(self._flush_pending_preview)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._settle_timer.timeout.connect(lambda: self.changed.emit(*self.values()))

    def values(self) -> tuple[float, float, float, str, bool]:
        return (self._vignette.value(), self._size.value(), self._border.value(), self._color.currentData() or DEFAULT_BORDER_COLOR, self._carrier.isChecked())

    def set_values(self, vignette: float, size: float, border: float, color: str, carrier: bool) -> None:
        """Sync the controls without emitting anything - after a new file or a history revert."""
        self._settle_timer.stop()
        self._pending = None
        self._vignette.set_value(vignette)
        self._size.set_value(size)
        self._border.set_value(border)
        self._color.blockSignals(True)
        self._color.setCurrentIndex(max(0, self._color.findData(color)))
        self._color.blockSignals(False)
        self._carrier.blockSignals(True)
        self._carrier.setChecked(bool(carrier))
        self._carrier.blockSignals(False)

    def reset(self) -> None:
        self.set_values(0.0, DEFAULT_VIGNETTE_SIZE, 0.0, DEFAULT_BORDER_COLOR, False)

    def _on_value_changed(self, *_args) -> None:
        values = self.values()
        if self._preview_timer.isActive():
            self._pending = values
        else:
            self.preview_requested.emit(*values)
            self._preview_timer.start()
        self._settle_timer.start()

    def _flush_pending_preview(self) -> None:
        if self._pending is not None:
            values, self._pending = self._pending, None
            self.preview_requested.emit(*values)
            self._preview_timer.start()
