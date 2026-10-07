from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QDoubleSpinBox, QHBoxLayout, QPushButton, QSlider, QWidget

from ...features.exposure.logic import EV_RANGE
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel

_SLIDER_STEPS = 100
_DEFAULT_EV = 0.0
_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200


class _ResettableSlider(QSlider):
    """A QSlider that snaps back to a default value on double-click -
    standard convention for "restore this control's neutral setting"."""

    def __init__(self, default_value: int, parent: QWidget | None = None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._default_value = default_value

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setValue(self._default_value)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class ExposureToolPanel(CollapsiblePanel):
    """The Exposure tab's dropdown content - the same raised-bevel, titled
    panel chrome the White Balance section has (a gray header bar with a
    collapse arrow and a "?" help button). This is a second, independent
    animation from the tool rail's own slide: the rail's "WB Correction"
    tab slides this whole panel in/out horizontally (SlideOutPanel, see
    tool_rail.py), while this panel's own arrow slides its body (the
    slider/spinbox) open/closed vertically within itself - the two never
    drive each other.

    A slider and a spinbox both drive the same EV value (drag or type it),
    kept in sync via a re-entrancy guard; double-clicking the slider resets
    it to 0.00 EV.

    Two signals, two speeds, because the full recompute (exposure math,
    two histograms, per-channel stats) is too slow to run on every tick a
    drag emits without visibly lagging, but the image math alone is cheap:
    - preview_requested(ev): image only, throttled to ~30fps - what keeps
      a drag feeling smooth. Wired to AppController.preview_exposure_ev().
    - exposure_changed(ev): the full recompute, debounced to fire once
      ~200ms after the value stops changing (a released slider, a typed
      spin value, or a pause mid-drag) - wired to
      AppController.set_exposure_ev(). Histogram/stats intentionally lag
      a beat behind the image during continuous dragging; they catch up
      as soon as it stops."""

    exposure_changed = pyqtSignal(float)
    preview_requested = pyqtSignal(float)
    proof_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Exposure",
            help_text=(
                "Adjusts overall image brightness, in EV stops (each stop "
                "doubles or halves brightness). Drag the slider or type an "
                "exact value; double-click the slider to reset to 0.00."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)

        self._updating = False
        self._current_ev = _DEFAULT_EV

        self._pending_preview_ev: float | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._preview_timer.timeout.connect(self._flush_pending_preview)

        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._settle_timer.timeout.connect(self._on_settled)

        self._slider = _ResettableSlider(int(_DEFAULT_EV * _SLIDER_STEPS))
        self._slider.setRange(int(-EV_RANGE * _SLIDER_STEPS), int(EV_RANGE * _SLIDER_STEPS))
        self._slider.setValue(int(_DEFAULT_EV * _SLIDER_STEPS))
        self._slider.valueChanged.connect(self._on_slider_changed)
        body.addWidget(self._slider)

        self._spin = QDoubleSpinBox()
        self._spin.setRange(-EV_RANGE, EV_RANGE)
        self._spin.setSingleStep(0.01)
        self._spin.setDecimals(2)
        self._spin.setSuffix(" EV")
        self._spin.setValue(_DEFAULT_EV)
        self._spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._spin.valueChanged.connect(self._on_spin_changed)
        body.addWidget(self._spin)

        proof_row = QHBoxLayout()
        proof_row.setSpacing(THEME.space_sm)
        self._strip_btn = QPushButton("Test Strip")
        self._strip_btn.setToolTip(
            "Print this photo 25 ways on the picture itself, like a darkroom test strip: each patch shows its own part of the picture at a different "
            "exposure (across) and contrast (down). Click a patch to keep it; [ and ] turn the ladder; Esc or the button again closes it. (Shift+T)"
        )
        self._strip_btn.clicked.connect(lambda: self.proof_requested.emit("strip"))
        self._ring_btn = QPushButton("Ring-Around")
        self._ring_btn.setToolTip(
            "Step the colour balance round this photo in a 5 x 5 mosaic on the picture: tint across, temperature down. The patch where a cast "
            "disappears shows which way to move. Click a patch to keep it; [ and ] turn the ladder; Esc closes it. (Shift+F)"
        )
        self._ring_btn.clicked.connect(lambda: self.proof_requested.emit("ring"))
        proof_row.addWidget(self._strip_btn)
        proof_row.addWidget(self._ring_btn)
        body.addLayout(proof_row)

    def reset(self) -> None:
        """Back to 0.00 EV without emitting anything - used when a new file
        is opened, since the controller has already reset its own exposure
        state as part of that load."""
        self.set_value(_DEFAULT_EV)

    def set_value(self, ev: float) -> None:
        """Sync the slider/spinbox to ev without emitting anything - used
        by reset() and after a history revert (AppController.reverted),
        since the controller has already updated its own state by then."""
        self._updating = True
        self._slider.setValue(round(ev * _SLIDER_STEPS))
        self._spin.setValue(ev)
        self._updating = False
        self._current_ev = ev
        self._settle_timer.stop()
        self._pending_preview_ev = None

    def _on_slider_changed(self, raw: int) -> None:
        if self._updating:
            return
        ev = raw / _SLIDER_STEPS
        self._updating = True
        self._spin.setValue(ev)
        self._updating = False
        self._on_value_changed(ev)

    def _on_spin_changed(self, ev: float) -> None:
        if self._updating:
            return
        self._updating = True
        self._slider.setValue(round(ev * _SLIDER_STEPS))
        self._updating = False
        self._on_value_changed(ev)

    def _on_value_changed(self, ev: float) -> None:
        self._current_ev = ev
        self._request_preview(ev)
        self._settle_timer.start()

    def _request_preview(self, ev: float) -> None:
        """Same leading-edge-immediate, trailing-edge-guaranteed throttle
        as before, just renamed to what it now actually drives: the cheap
        image-only preview, not the full recompute."""
        if self._preview_timer.isActive():
            self._pending_preview_ev = ev
            return
        self.preview_requested.emit(ev)
        self._preview_timer.start()

    def _flush_pending_preview(self) -> None:
        if self._pending_preview_ev is not None:
            ev, self._pending_preview_ev = self._pending_preview_ev, None
            self.preview_requested.emit(ev)
            self._preview_timer.start()

    def _on_settled(self) -> None:
        self.exposure_changed.emit(self._current_ev)
