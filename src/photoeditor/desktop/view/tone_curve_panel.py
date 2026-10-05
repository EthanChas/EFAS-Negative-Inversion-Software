from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from ...features.tonecurve.logic import DEFAULT_POINTS
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .curve_editor import CurveEditor

_PREVIEW_THROTTLE_MS = 33  # ~30fps cap for the cheap image-only preview, same as Exposure


class ToneCurveToolPanel(CollapsiblePanel):
    """The Tone Curve tab's dropdown content - a draggable curve graph (see
    CurveEditor) plus a Reset button, in the same raised-bevel panel chrome
    as Exposure, with its own collapse arrow for the vertical slide that's
    independent of the tool rail's own horizontal slide.

    Two signals, two speeds - the same reasoning as Exposure's: remapping a
    multi-megapixel preview through a LUT on every mouse-move tick of a drag
    would lag, but the cheap image-only version doesn't:
    - preview_requested(points): image only, throttled to ~30fps - keeps a
      drag feeling smooth. Wired to AppController.preview_tone_curve().
    - curve_changed(points): the full recompute (histogram/stats too) -
      fired once an edit is actually finished (mouse released, a point
      added or removed), via CurveEditor.interaction_finished - no debounce
      timer needed here since the editor already knows precisely when a
      drag ends, unlike a QSlider. Wired to AppController.set_tone_curve().

    A third control, the Eyedropper button, is unrelated to editing the
    curve - it's a read-only probe. Toggling it on asks AppWindow (via
    eyedropper_toggled) to put the main image into pick mode with a custom
    cursor; clicking the image then marks that pixel's brightness on this
    curve (see set_marker) and the mark stays until the button is toggled
    off again - no hover-tracking involved, unlike the white balance
    graph's marker."""

    curve_changed = pyqtSignal(list)
    preview_requested = pyqtSignal(list)
    eyedropper_toggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Tone Curve",
            help_text=(
                "Remaps brightness through a custom curve. Click an empty "
                "spot to add a point, drag a point to move it, double-click "
                "a point to remove it (the two end points can't be "
                "removed). Reset returns to a straight line."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)

        self._pending_preview_points: list[tuple[int, int]] | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._preview_timer.timeout.connect(self._flush_pending_preview)

        self._editor = CurveEditor()
        self._editor.points_changed.connect(self._request_preview)
        self._editor.interaction_finished.connect(self._on_settled)
        body.addWidget(self._editor)

        button_row = QHBoxLayout()
        button_row.setSpacing(THEME.space_sm)

        self._eyedropper_btn = QPushButton("Eyedropper")
        self._eyedropper_btn.setCheckable(True)
        self._eyedropper_btn.toggled.connect(self._on_eyedropper_toggled)
        button_row.addWidget(self._eyedropper_btn)

        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self._on_reset_clicked)
        button_row.addWidget(reset_btn)

        body.addLayout(button_row)

    def reset(self) -> None:
        """Back to the identity curve without emitting anything - used when
        a new file is opened, since the controller has already reset its
        own curve state as part of that load."""
        self.set_curve(list(DEFAULT_POINTS))

    def set_curve(self, points: list[tuple[int, int]]) -> None:
        """Sync the curve editor to points without emitting anything - used
        by reset() and after a history revert (AppController.reverted)."""
        self._preview_timer.stop()
        self._pending_preview_points = None
        self._editor.set_points(points)
        self._eyedropper_btn.setChecked(False)  # also clears the marker, via toggled

    def deactivate_eyedropper(self) -> None:
        self._eyedropper_btn.setChecked(False)

    def set_marker(self, value: float | None) -> None:
        """Marks where an eyedropper pick landed on the curve."""
        self._editor.set_marker(value)

    def _on_eyedropper_toggled(self, active: bool) -> None:
        if not active:
            self._editor.set_marker(None)
        self.eyedropper_toggled.emit(active)

    def _on_reset_clicked(self) -> None:
        self._editor.set_points(list(DEFAULT_POINTS))
        points = self._editor.points()
        self.preview_requested.emit(points)
        self.curve_changed.emit(points)

    def _request_preview(self, points: list[tuple[int, int]]) -> None:
        if self._preview_timer.isActive():
            self._pending_preview_points = points
            return
        self.preview_requested.emit(points)
        self._preview_timer.start()

    def _flush_pending_preview(self) -> None:
        if self._pending_preview_points is not None:
            points, self._pending_preview_points = self._pending_preview_points, None
            self.preview_requested.emit(points)
            self._preview_timer.start()

    def _on_settled(self) -> None:
        self.curve_changed.emit(self._editor.points())
