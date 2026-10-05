from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...features.negative.logic import FILM_TYPE_LABELS, FILM_TYPES, ProcessMode
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_MODE_LABELS = {
    ProcessMode.C41: "C41 (color negative)",
    ProcessMode.BW: "B&W negative",
    ProcessMode.E6: "E6 / already a positive",
}
_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200


class NegativeToolPanel(CollapsiblePanel):
    """The Negative tab's main section: say what film the scan is, invert a
    negative to a positive, and trim its red/green/blue by hand.

    Film type is detected automatically (a heuristic ported from NegPy's
    detect_process_mode - it can misread an already color-corrected photo),
    or picked by hand: color negative (C41), black & white negative, or slide
    film (E6). Negatives are inverted, a slide isn't, and a B&W negative is
    also treated as monochrome. The red/green/blue trim then fine-tunes the
    inverted result per channel. Detection and inversion read only the
    current crop region, if one is set (see Renderer.render).

    Crop/rotate/flip live in the sibling CropToolPanel, stacked below this
    one in the same Negative tab dropdown."""

    detect_requested = pyqtSignal()
    inverted_toggled = pyqtSignal(bool)
    film_type_changed = pyqtSignal(str)
    rgb_changed = pyqtSignal(float, float, float)  # settled
    rgb_preview_requested = pyqtSignal(float, float, float)  # while dragging
    base_pick_toggled = pyqtSignal(bool)  # the film-base eyedropper armed / disarmed
    base_cleared = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Negative",
            help_text=(
                "Film type: Auto-detect reads the scan; or choose Color negative (C41), Black & white "
                "negative or Slide film (E6) yourself. Negatives are inverted to a positive, a slide is "
                "left as it is, and a B&W negative is treated as monochrome. Detect re-reads the scan "
                "(only the cropped area, if there is a crop) and shows what it found without changing "
                "anything. Invert to Positive flips the inversion by hand. Red/Green/Blue trim the "
                "inverted result per color - drag right to add that color, left to remove it; "
                "double-click a slider to reset it.\n\n"
                "Film base: pick the unexposed film border (the rebate) once and every photo in this folder is "
                "calibrated to it, so a whole roll comes out with consistent color instead of each frame guessing "
                "its own. Pick shows the raw scan - click the clear film at the edge. Clear goes back to estimating."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)

        type_row = QHBoxLayout()
        type_row.setSpacing(THEME.space_sm)
        type_label = QLabel("Film type")
        type_label.setFixedWidth(80)
        type_row.addWidget(type_label)
        self._type_combo = QComboBox()
        for film_type in FILM_TYPES:
            self._type_combo.addItem(FILM_TYPE_LABELS[film_type], film_type)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_row.addWidget(self._type_combo, 1)
        body.addLayout(type_row)

        self._detect_btn = QPushButton("Detect")
        self._detect_btn.clicked.connect(self.detect_requested)
        body.addWidget(self._detect_btn)

        self._result_label = QLabel("Not detected yet.")
        self._result_label.setProperty("role", "hint")
        self._result_label.setWordWrap(True)
        body.addWidget(self._result_label)

        self._invert_btn = QPushButton("Invert to Positive")
        self._invert_btn.setCheckable(True)
        self._invert_btn.toggled.connect(self.inverted_toggled)
        body.addWidget(self._invert_btn)

        base_title = QLabel("FILM BASE")
        base_title.setProperty("role", "subtitle")
        body.addWidget(base_title)
        base_row = QHBoxLayout()
        base_row.setSpacing(THEME.space_sm)
        self._base_btn = QPushButton("Pick from Rebate")
        self._base_btn.setCheckable(True)
        self._base_btn.setToolTip("Click the unexposed film border (the clear rebate) on the raw scan. Applies to every photo in this folder.")
        self._base_btn.toggled.connect(self.base_pick_toggled)
        base_row.addWidget(self._base_btn, 1)
        self._base_swatch = QLabel()
        self._base_swatch.setFixedSize(22, 22)
        base_row.addWidget(self._base_swatch)
        self._base_clear = QPushButton("Clear")
        self._base_clear.clicked.connect(self.base_cleared)
        base_row.addWidget(self._base_clear)
        body.addLayout(base_row)
        self._base_label = QLabel("")
        self._base_label.setProperty("role", "hint")
        self._base_label.setWordWrap(True)
        body.addWidget(self._base_label)
        self.set_film_base(None)

        trim = QLabel("COLOR TRIM")
        trim.setProperty("role", "subtitle")
        body.addWidget(trim)
        rows = QVBoxLayout()
        rows.setSpacing(THEME.space_sm)
        self._red = SliderRow("Red")
        self._green = SliderRow("Green")
        self._blue = SliderRow("Blue")
        for row in (self._red, self._green, self._blue):
            row.value_changed.connect(self._on_rgb_changed)
            rows.addWidget(row)
        body.addLayout(rows)

        self._pending_preview: tuple[float, float, float] | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._preview_timer.timeout.connect(self._flush_pending_preview)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._settle_timer.timeout.connect(self._on_settled)

    # ---- film type / invert ----
    def show_detection(self, mode: ProcessMode) -> None:
        self._result_label.setText(f"Detected: {_MODE_LABELS[mode]}")

    def _on_type_changed(self, _index: int) -> None:
        self.film_type_changed.emit(self._type_combo.currentData())

    def set_film_type(self, film_type: str) -> None:
        """Sync the combo without emitting anything."""
        self._type_combo.blockSignals(True)
        self._type_combo.setCurrentIndex(max(0, self._type_combo.findData(film_type)))
        self._type_combo.blockSignals(False)

    def set_inverted(self, inverted: bool) -> None:
        """Sync the Invert button without emitting anything - used by
        reset() and after a history revert."""
        self._invert_btn.blockSignals(True)
        self._invert_btn.setChecked(inverted)
        self._invert_btn.blockSignals(False)

    # ---- film base ----
    def set_film_base(self, rgb: tuple[int, int, int] | None) -> None:
        """Show whether this roll has a measured film base - a swatch of its color, and a line saying so."""
        self._base_clear.setEnabled(rgb is not None)
        if rgb is None:
            self._base_swatch.setStyleSheet(f"background: transparent; border: 1px solid {THEME.border_color};")
            self._base_label.setText("Estimated from each photo. Pick the clear film border to calibrate the whole roll.")
        else:
            self._base_swatch.setStyleSheet(f"background: rgb({rgb[0]},{rgb[1]},{rgb[2]}); border: 1px solid {THEME.border_color};")
            self._base_label.setText(f"Measured on this roll: R {rgb[0]}  G {rgb[1]}  B {rgb[2]}. Every photo in the folder uses it.")

    def set_pick_active(self, active: bool) -> None:
        """Sync the Pick button without emitting anything."""
        self._base_btn.blockSignals(True)
        self._base_btn.setChecked(active)
        self._base_btn.blockSignals(False)

    # ---- color trim ----
    def _current(self) -> tuple[float, float, float]:
        return (self._red.value(), self._green.value(), self._blue.value())

    def set_rgb(self, r: float, g: float, b: float) -> None:
        self._red.set_value(r)
        self._green.set_value(g)
        self._blue.set_value(b)

    def _on_rgb_changed(self, _value: float) -> None:
        values = self._current()
        if self._preview_timer.isActive():
            self._pending_preview = values
        else:
            self.rgb_preview_requested.emit(*values)
            self._preview_timer.start()
        self._settle_timer.start()

    def _flush_pending_preview(self) -> None:
        if self._pending_preview is not None:
            values, self._pending_preview = self._pending_preview, None
            self.rgb_preview_requested.emit(*values)
            self._preview_timer.start()

    def _on_settled(self) -> None:
        self.rgb_changed.emit(*self._current())

    def reset(self) -> None:
        """Back to defaults without emitting anything - used when a new file
        is opened, since the controller has already reset (or restored) its
        own state as part of that load."""
        self._settle_timer.stop()
        self._pending_preview = None
        self.set_inverted(False)
        self.set_film_type("auto")
        self.set_rgb(0.0, 0.0, 0.0)
        self._result_label.setText("Not detected yet.")
