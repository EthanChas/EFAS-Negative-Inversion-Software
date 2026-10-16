import numpy as np
from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSpinBox, QWidget

from ...features.tonecurve import logic as tc
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .curve_editor import CurveEditor

_PREVIEW_THROTTLE_MS = 33
# the tabs: (the curve it edits, its label, its colour)
_TABS = (("tone_curve_points", "RGB", None), ("tone_curve_red", "Red", "#e5534b"), ("tone_curve_green", "Green", "#3fb950"), ("tone_curve_blue", "Blue", "#4a8cf7"))
_PICKERS = (("black", "Black", "Click the part of the picture that should be black: each colour channel's black point is set from it"),
            ("grey", "Grey", "Click something that should be neutral grey: each channel is nudged so that spot has no colour, at the brightness it has"),
            ("white", "White", "Click the part of the picture that should be white: each channel's white point is set from it"))


class ToneCurveToolPanel(CollapsiblePanel):
    """The Tone Curve module: a draggable curve graph (see CurveEditor) for the picture's brightness as a whole (RGB) and one for each colour channel (Red, Green, Blue,
    applied after the RGB one), with In / Out boxes for the point being edited, Black / Grey / White point pickers, Auto, and Reset - all in the same raised-bevel panel
    chrome as Exposure, with its own collapse arrow for the vertical slide that's independent of the tool rail's own horizontal slide.

    Two signals, two speeds - the same reasoning as Exposure's: remapping a multi-megapixel preview through a LUT on every mouse-move tick of a drag would lag, but the
    cheap image-only version doesn't:
    - preview_requested(curves): image only, throttled to ~30fps - keeps a drag feeling smooth. Wired to AppController.preview_tone_curve().
    - curve_changed(curves): the full recompute (histogram/stats too) - fired once an edit is actually finished (mouse released, a point added or removed), via
      CurveEditor.interaction_finished. Wired to AppController.set_tone_curve().
    `curves` is a dict of all four curves by key (features/tonecurve/logic.py CURVE_KEYS).

    The Eyedropper button is a read-only probe: toggled on, it asks AppWindow (via eyedropper_toggled) to put the main image into pick mode, and a click marks that
    pixel's brightness on the curve. The point pickers use the same pick mode, but one click sets curves (apply_pick) and the picker puts itself away."""

    curve_changed = pyqtSignal(object)
    preview_requested = pyqtSignal(object)
    eyedropper_toggled = pyqtSignal(bool)
    picker_toggled = pyqtSignal(str, bool)   # "black", "grey" or "white", armed or not
    auto_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Tone Curve",
            help_text=(
                "Remaps brightness through a custom curve. RGB is the curve for the whole picture; Red, Green and Blue are a curve for each colour channel on its own, "
                "applied after it (lift the blue curve's shadows for a cool shadow tone, say). Click an empty spot to add a point, drag a point to move it, double-click a "
                "point to remove it (the two end points can't be removed). The In and Out boxes show the selected point and set it exactly. Black, Grey and White each "
                "wait for one click on the picture: Black and White set every channel's end point from that spot, Grey makes the spot neutral. Auto sets black and white "
                "points from the picture's own darkest and lightest tones. Reset returns the curve on show to a straight line."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)

        self._curves: dict[str, list[tuple[int, int]]] = {key: list(tc.DEFAULT_POINTS) for key in tc.CURVE_KEYS}
        self._tab = "tone_curve_points"
        self._pending_preview: dict | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._preview_timer.timeout.connect(self._flush_pending_preview)

        tabs = QHBoxLayout()
        tabs.setSpacing(THEME.space_sm)
        self._tab_buttons: dict[str, QPushButton] = {}
        for key, label, color in _TABS:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setToolTip("The curve for the whole picture" if color is None else f"The {label.lower()} channel's own curve, applied after the RGB curve")
            if color is not None:
                button.setStyleSheet(f"QPushButton:checked {{ border: 2px solid {color}; }}")
            button.clicked.connect(lambda _c=False, k=key: self._show(k))
            self._tab_buttons[key] = button
            tabs.addWidget(button, 1)
        body.addLayout(tabs)

        self._editor = CurveEditor()
        self._editor.points_changed.connect(self._on_points_changed)
        self._editor.interaction_finished.connect(self._on_settled)
        self._editor.selection_changed.connect(self._on_selection)
        body.addWidget(self._editor)

        fields = QHBoxLayout()
        fields.setSpacing(THEME.space_sm)
        self._in_box, self._out_box = QSpinBox(), QSpinBox()
        for box, label in ((self._in_box, "In"), (self._out_box, "Out")):
            box.setRange(0, 255)
            box.setEnabled(False)
            box.setFixedWidth(64)
            box.setToolTip(f"{label}: the selected point's {'input' if label == 'In' else 'output'}, 0 to 255")
            fields.addWidget(QLabel(label))
            fields.addWidget(box)
        self._in_box.editingFinished.connect(lambda: self._editor.set_selected_point(x=self._in_box.value()))
        self._out_box.editingFinished.connect(lambda: self._editor.set_selected_point(y=self._out_box.value()))
        fields.addStretch(1)
        body.addLayout(fields)

        title = QLabel("POINT PICKERS")
        title.setProperty("role", "subtitle")
        body.addWidget(title)
        pickers = QHBoxLayout()
        pickers.setSpacing(THEME.space_sm)
        self._picker_buttons: dict[str, QPushButton] = {}
        for kind, label, tip in _PICKERS:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setToolTip(tip)
            button.toggled.connect(lambda on, k=kind: self._on_picker_toggled(k, on))
            self._picker_buttons[kind] = button
            pickers.addWidget(button, 1)
        self._auto_btn = QPushButton("Auto")
        self._auto_btn.setToolTip("Set each channel's black and white points from the picture's own darkest and lightest tones")
        self._auto_btn.clicked.connect(self.auto_requested)
        pickers.addWidget(self._auto_btn, 1)
        body.addLayout(pickers)

        button_row = QHBoxLayout()
        button_row.setSpacing(THEME.space_sm)
        self._eyedropper_btn = QPushButton("Eyedropper")
        self._eyedropper_btn.setCheckable(True)
        self._eyedropper_btn.setToolTip("Click the picture to mark that pixel's brightness on the curve")
        self._eyedropper_btn.toggled.connect(self._on_eyedropper_toggled)
        button_row.addWidget(self._eyedropper_btn)
        reset_btn = QPushButton("Reset")
        reset_btn.setToolTip("Straighten the curve on show")
        reset_btn.clicked.connect(self._on_reset_clicked)
        button_row.addWidget(reset_btn)
        reset_all = QPushButton("Reset All")
        reset_all.setToolTip("Straighten all four curves")
        reset_all.clicked.connect(self._on_reset_all_clicked)
        button_row.addWidget(reset_all)
        body.addLayout(button_row)
        self._show("tone_curve_points")

    # ------------------------------------------------------------ the curve on show
    def _show(self, key: str) -> None:
        self._tab = key
        for k, button in self._tab_buttons.items():
            button.setChecked(k == key)
        color = next(c for k, _l, c in _TABS if k == key)
        self._editor.set_color(color or THEME.channel_luminance)
        self._editor.set_points(self._curves[key])
        self._refresh_ghosts()

    def _refresh_ghosts(self) -> None:
        """While the RGB curve is on show, the colour curves that are not straight lines are drawn faintly behind it."""
        if self._tab == "tone_curve_points":
            self._editor.set_ghosts([(self._curves[k], c) for k, _l, c in _TABS[1:] if not tc.is_identity(self._curves[k])])
        else:
            self._editor.set_ghosts([])

    def curves(self) -> dict:
        return {key: list(points) for key, points in self._curves.items()}

    def reset(self) -> None:
        """Back to straight lines without emitting anything - used when a new file is opened, since the controller has already reset its own curve state as part of
        that load."""
        self.set_curve({key: list(tc.DEFAULT_POINTS) for key in tc.CURVE_KEYS})

    def set_curve(self, curves) -> None:
        """Sync the editor to these curves without emitting anything - used by reset() and after a history revert (AppController.reverted). `curves` is a dict by key, or a
        list of points for the master curve alone."""
        self._preview_timer.stop()
        self._pending_preview = None
        if not isinstance(curves, dict):
            curves = {"tone_curve_points": curves}
        for key in tc.CURVE_KEYS:
            self._curves[key] = [tuple(p) for p in curves.get(key, tc.DEFAULT_POINTS)]
        self._editor.set_points(self._curves[self._tab])
        self._refresh_ghosts()
        self.deactivate_eyedropper()

    # ------------------------------------------------------------ the picture probe and the pickers
    def deactivate_eyedropper(self) -> None:
        """Put the eyedropper and any armed point picker away."""
        self._eyedropper_btn.setChecked(False)
        for button in self._picker_buttons.values():
            button.blockSignals(True)
            button.setChecked(False)
            button.blockSignals(False)

    def set_marker(self, value: float | None) -> None:
        """Marks where an eyedropper pick landed on the curve."""
        self._editor.set_marker(value)

    def _on_eyedropper_toggled(self, active: bool) -> None:
        if active:
            for button in self._picker_buttons.values():
                button.blockSignals(True)
                button.setChecked(False)
                button.blockSignals(False)
        if not active:
            self._editor.set_marker(None)
        self.eyedropper_toggled.emit(active)

    def _on_picker_toggled(self, kind: str, active: bool) -> None:
        if active:
            for other, button in self._picker_buttons.items():
                if other != kind:
                    button.blockSignals(True)
                    button.setChecked(False)
                    button.blockSignals(False)
            self._eyedropper_btn.blockSignals(True)
            self._eyedropper_btn.setChecked(False)
            self._eyedropper_btn.blockSignals(False)
            self._editor.set_marker(None)
        self.picker_toggled.emit(kind, active)

    def armed_picker(self) -> str | None:
        """The point picker waiting for its click on the picture, if one is."""
        return next((kind for kind, button in self._picker_buttons.items() if button.isChecked()), None)

    def apply_pick(self, kind: str, rgb) -> None:
        """A picker's click landed on a pixel showing this red, green, blue: set the colour channels' curves from it, then put the picker away."""
        channels = [self._curves[k] for k in tc.CHANNEL_KEYS]
        rgb = tuple(int(v) for v in rgb[:3])
        new = {"black": tc.pick_black, "white": tc.pick_white, "grey": tc.pick_grey}[kind](channels, rgb)
        self._set_channels(new)
        self.deactivate_eyedropper()

    def apply_auto(self, image: np.ndarray | None) -> None:
        """Auto: black and white points for each channel from the picture on show (its 0.5th and 99.5th percentile of each)."""
        if image is None or image.ndim != 3 or image.shape[2] < 3:
            return
        sample = image[::max(1, image.shape[0] // 400), ::max(1, image.shape[1] // 400), :3]
        if sample.dtype != np.uint8:
            sample = np.clip(sample.astype(np.float32) / (257.0 if sample.dtype == np.uint16 else 1.0), 0, 255)
        self._set_channels(tc.auto_levels([self._curves[k] for k in tc.CHANNEL_KEYS], sample))

    def _set_channels(self, new) -> None:
        for key, points in zip(tc.CHANNEL_KEYS, new):
            self._curves[key] = [tuple(p) for p in points]
        self._editor.set_points(self._curves[self._tab])
        self._refresh_ghosts()
        self._emit(final=True)

    # ------------------------------------------------------------ the In / Out boxes
    def _on_selection(self, index: int, x: int, y: int) -> None:
        on = index >= 0
        for box, value in ((self._in_box, x), (self._out_box, y)):
            box.blockSignals(True)
            box.setValue(value if on else 0)
            box.blockSignals(False)
            box.setEnabled(on)
        # the end points' inputs are fixed at 0 and 255
        if on:
            last = len(self._curves[self._tab]) - 1
            self._in_box.setEnabled(0 < index < last)

    # ------------------------------------------------------------ editing
    def _on_points_changed(self, points: list[tuple[int, int]]) -> None:
        self._curves[self._tab] = list(points)
        self._refresh_ghosts()
        self._emit(final=False)

    def _on_settled(self) -> None:
        self._curves[self._tab] = self._editor.points()
        self._emit(final=True)

    def _on_reset_clicked(self) -> None:
        self._editor.set_points(list(tc.DEFAULT_POINTS))
        self._curves[self._tab] = list(tc.DEFAULT_POINTS)
        self._refresh_ghosts()
        self._emit(final=True)

    def _on_reset_all_clicked(self) -> None:
        self._curves = {key: list(tc.DEFAULT_POINTS) for key in tc.CURVE_KEYS}
        self._editor.set_points(self._curves[self._tab])
        self._refresh_ghosts()
        self._emit(final=True)

    def _emit(self, final: bool) -> None:
        curves = self.curves()
        if final:
            self.preview_requested.emit(curves)
            self.curve_changed.emit(curves)
            return
        if self._preview_timer.isActive():
            self._pending_preview = curves
            return
        self.preview_requested.emit(curves)
        self._preview_timer.start()

    def _flush_pending_preview(self) -> None:
        if self._pending_preview is not None:
            curves, self._pending_preview = self._pending_preview, None
            self.preview_requested.emit(curves)
            self._preview_timer.start()
