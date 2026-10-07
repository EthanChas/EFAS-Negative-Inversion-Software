from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

from ...features.geometry.guides import GUIDE_LABELS, ORIENTATION_COUNT, CropGuide
from ...features.geometry.logic import DISTORTION_LIMIT, FINE_ROTATION_LIMIT
from ...theme.tokens import THEME
from ..settings_store import qsettings
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200
AUTO_MARGIN_LIMIT = 10.0
AUTO_ROTATE_LIMIT = 3.0
_GUIDE_KEY = "crop/guide"

_RATIOS = (
    ("Free", None),
    ("Original", "original"),
    ("1:1", 1.0),
    ("3:2", 3 / 2),
    ("4:3", 4 / 3),
    ("5:4", 5 / 4),
    ("6:7", 7 / 6),
    ("7:5", 7 / 5),
    ("65:24", 65 / 24),
    ("16:9", 16 / 9),
    ("16:10", 16 / 10),
    ("8.5:11", 11 / 8.5),
)


class CropToolPanel(CollapsiblePanel):
    """A sibling of NegativeToolPanel, stacked below it in the same
    Negative tab dropdown - rotate/flip/crop (features/geometry/logic.py),
    grouped separately from detection/inversion since they're an
    independent concern (straightening and framing a scan vs. correcting
    its color), the same way Exposure and Tone Curve are two separate
    panels under WB Correction rather than one."""

    rotate_left_requested = pyqtSignal()
    rotate_right_requested = pyqtSignal()
    flip_h_toggled = pyqtSignal(bool)
    flip_v_toggled = pyqtSignal(bool)
    crop_mode_toggled = pyqtSignal(bool)
    crop_cleared = pyqtSignal()
    auto_crop_requested = pyqtSignal()
    gradient_crop_requested = pyqtSignal()
    straighten_tool_toggled = pyqtSignal(bool)
    auto_adjust_changed = pyqtSignal(float, float)
    guide_changed = pyqtSignal(str, int)
    ratio_changed = pyqtSignal(object)
    fine_rotation_changed = pyqtSignal(float)
    fine_rotation_preview = pyqtSignal(float)
    distortion_changed = pyqtSignal(float)
    distortion_preview = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Crop & Rotate",
            help_text=(
                "Rotate with the buttons or the [ and ] keys. Flip "
                "horizontally or vertically. Crop: click Crop, drag a "
                "rectangle on the image (drag its handles to adjust), "
                "toggle Crop off when done - Clear Crop removes it. "
                "Rotating/flipping carries an existing crop along with it, "
                "rather than clearing it. Auto Crop & Straighten finds the picture "
                "inside the scan for you.\n\n"
                "Straighten: tilt the picture by up to 45 degrees either way "
                "(positive turns it clockwise) - it's enlarged just enough to "
                "avoid blank corners. Double-click the slider to reset it.\n\n"
                "Distortion Correction: radial lens distortion - positive corrects barrel, "
                "negative corrects pincushion; use the film rebate as a straight reference. "
                "Double-click the slider to reset it.\n\n"
                "Ratio holds the crop to a shape (it turns to landscape or "
                "portrait with your drag); Original keeps the frame's own shape. "
                "Guide picks the composition overlay drawn inside the crop."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)

        rotate_row = QHBoxLayout()
        rotate_row.setSpacing(THEME.space_sm)
        rotate_left_btn = QPushButton("Rotate Left [")
        rotate_left_btn.clicked.connect(self.rotate_left_requested)
        rotate_row.addWidget(rotate_left_btn)
        rotate_right_btn = QPushButton("Rotate Right ]")
        rotate_right_btn.clicked.connect(self.rotate_right_requested)
        rotate_row.addWidget(rotate_right_btn)
        body.addLayout(rotate_row)

        flip_row = QHBoxLayout()
        flip_row.setSpacing(THEME.space_sm)
        self._flip_h_btn = QPushButton("Flip Horizontal")
        self._flip_h_btn.setCheckable(True)
        self._flip_h_btn.toggled.connect(self.flip_h_toggled)
        flip_row.addWidget(self._flip_h_btn)
        self._flip_v_btn = QPushButton("Flip Vertical")
        self._flip_v_btn.setCheckable(True)
        self._flip_v_btn.toggled.connect(self.flip_v_toggled)
        flip_row.addWidget(self._flip_v_btn)
        body.addLayout(flip_row)

        auto_btn = QPushButton("Auto Crop && Straighten")
        auto_btn.setToolTip(
            "Find the picture inside the scan (the film border, sprocket holes and holder around it), level it if it sits crooked, and crop to it. "
            "Works best after the negative is inverted."
        )
        auto_btn.clicked.connect(self.auto_crop_requested)
        body.addWidget(auto_btn)
        gradient_btn = QPushButton("Gradient Border Crop && Rotate")
        gradient_btn.setToolTip(
            "Finds the picture by its edge instead of by its colour: the border is a solid colour with a margin, and where the picture starts there "
            "is a gradient - a line of gradual change along the whole side. It follows that line on each side (and its tilt) and crops just inside "
            "it. Better than Auto Crop where the picture fades into the border, such as a dark sky against a dark rebate."
        )
        gradient_btn.clicked.connect(self.gradient_crop_requested)
        body.addWidget(gradient_btn)
        adjust_tip = "Nudge the result of the Auto Crop or Gradient Border Crop you just ran. Double-click a slider to put it back to 0."
        self._auto_margin = SliderRow("Crop", min_value=-AUTO_MARGIN_LIMIT, max_value=AUTO_MARGIN_LIMIT, reset_value=0.0, decimals=1, step=0.1)
        self._auto_margin.setToolTip(adjust_tip + "\nPositive crops in more from every side, negative lets more of the picture in (percent of the crop).")
        self._auto_rotate = SliderRow("Rotate", min_value=-AUTO_ROTATE_LIMIT, max_value=AUTO_ROTATE_LIMIT, reset_value=0.0, decimals=1, step=0.1)
        self._auto_rotate.setToolTip(adjust_tip + "\nTurns the picture a little more or less than the auto crop straightened it (degrees, clockwise positive).")
        self._auto_tips = (self._auto_margin.toolTip(), self._auto_rotate.toolTip())
        for row in (self._auto_margin, self._auto_rotate):
            row.value_changed.connect(lambda _v: self._auto_adjust_timer.start())
            body.addWidget(row)
        self._auto_adjust_timer = QTimer(self)
        self._auto_adjust_timer.setSingleShot(True)
        self._auto_adjust_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._auto_adjust_timer.timeout.connect(lambda: self.auto_adjust_changed.emit(self._auto_margin.value(), self._auto_rotate.value()))
        self.set_auto_adjust_enabled(False)

        crop_row = QHBoxLayout()
        crop_row.setSpacing(THEME.space_sm)
        self._crop_btn = QPushButton("Crop")
        self._crop_btn.setCheckable(True)
        self._crop_btn.toggled.connect(self.crop_mode_toggled)
        crop_row.addWidget(self._crop_btn)
        clear_crop_btn = QPushButton("Clear Crop")
        clear_crop_btn.clicked.connect(self.crop_cleared)
        crop_row.addWidget(clear_crop_btn)
        body.addLayout(crop_row)

        ratio_row = QHBoxLayout()
        ratio_row.setSpacing(THEME.space_sm)
        ratio_label = QLabel("Ratio")
        ratio_label.setFixedWidth(80)
        ratio_row.addWidget(ratio_label)
        self._ratio_combo = QComboBox()
        for label, value in _RATIOS:
            self._ratio_combo.addItem(label, value)
        self._ratio_combo.setToolTip("Hold the crop rectangle to an aspect ratio.")
        self._ratio_combo.currentIndexChanged.connect(lambda _i: self.ratio_changed.emit(self._ratio_combo.currentData()))
        ratio_row.addWidget(self._ratio_combo, 1)
        body.addLayout(ratio_row)

        guide_row = QHBoxLayout()
        guide_row.setSpacing(THEME.space_sm)
        guide_label = QLabel("Guide")
        guide_label.setFixedWidth(80)
        guide_row.addWidget(guide_label)
        self._guide_combo = QComboBox()
        for guide, label in GUIDE_LABELS.items():
            self._guide_combo.addItem(label, guide.value)
        self._guide_combo.setToolTip("Composition guide shown inside the crop rectangle.")
        self._guide_combo.currentIndexChanged.connect(self._on_guide_changed)
        guide_row.addWidget(self._guide_combo, 1)
        self._guide_orient_btn = QPushButton("\u21bb")
        self._guide_orient_btn.setFixedWidth(28)
        self._guide_orient_btn.setToolTip("Turn the guide (spiral and triangles have several orientations).")
        self._guide_orient_btn.clicked.connect(self._on_guide_orient)
        guide_row.addWidget(self._guide_orient_btn)
        body.addLayout(guide_row)
        self._guide_orientation = 0
        saved = str(qsettings().value(_GUIDE_KEY, CropGuide.THIRDS.value) or CropGuide.THIRDS.value)
        self._guide_combo.blockSignals(True)
        self._guide_combo.setCurrentIndex(max(0, self._guide_combo.findData(saved)))
        self._guide_combo.blockSignals(False)
        self._refresh_guide_button()

        straighten = QLabel("STRAIGHTEN")
        straighten.setProperty("role", "subtitle")
        body.addWidget(straighten)
        self._straighten_btn = QPushButton("Straighten Tool")
        self._straighten_btn.setCheckable(True)
        self._straighten_btn.setToolTip(
            "Click two points along something that should be level (a horizon, the film's edge) or upright (a wall, a door frame): the "
            "picture is turned to make that line level or plumb. Esc cancels the first point."
        )
        self._straighten_btn.toggled.connect(self.straighten_tool_toggled)
        body.addWidget(self._straighten_btn)
        self._fine = SliderRow(
            "Angle", min_value=-FINE_ROTATION_LIMIT, max_value=FINE_ROTATION_LIMIT, reset_value=0.0, decimals=1, step=0.1
        )
        self._fine.value_changed.connect(self._on_fine_changed)
        body.addWidget(self._fine)
        self._pending_fine: float | None = None
        self._fine_preview_timer = QTimer(self)
        self._fine_preview_timer.setSingleShot(True)
        self._fine_preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._fine_preview_timer.timeout.connect(self._flush_fine_preview)
        self._fine_settle_timer = QTimer(self)
        self._fine_settle_timer.setSingleShot(True)
        self._fine_settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._fine_settle_timer.timeout.connect(lambda: self.fine_rotation_changed.emit(self._fine.value()))

        distortion = QLabel("DISTORTION CORRECTION")
        distortion.setProperty("role", "subtitle")
        body.addWidget(distortion)
        self._distortion = SliderRow(
            "Distortion", min_value=-DISTORTION_LIMIT, max_value=DISTORTION_LIMIT, reset_value=0.0, decimals=3, step=0.001
        )
        self._distortion.setToolTip(
            "Radial lens distortion. Positive corrects barrel, negative pincushion. "
            "Use the film rebate as a straight reference.\nDouble-click to reset"
        )
        self._distortion.value_changed.connect(self._on_distortion_changed)
        body.addWidget(self._distortion)
        self._pending_distortion: float | None = None
        self._distortion_preview_timer = QTimer(self)
        self._distortion_preview_timer.setSingleShot(True)
        self._distortion_preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._distortion_preview_timer.timeout.connect(self._flush_distortion_preview)
        self._distortion_settle_timer = QTimer(self)
        self._distortion_settle_timer.setSingleShot(True)
        self._distortion_settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._distortion_settle_timer.timeout.connect(lambda: self.distortion_changed.emit(self._distortion.value()))

    def set_auto_adjust_enabled(self, enabled: bool) -> None:
        """The two adjusters work on the last auto crop: off (and back at 0) until one has been run, and again once the crop or rotation is changed
        some other way. Never emits."""
        self._auto_adjust_timer.stop()
        for row in (self._auto_margin, self._auto_rotate):
            row.set_value(0.0)
            row.setEnabled(enabled)
        for row, tip in zip((self._auto_margin, self._auto_rotate), self._auto_tips):
            row.setToolTip(tip if enabled else "Run Auto Crop or Gradient Border Crop first, then nudge its result here.")

    def _on_distortion_changed(self, value: float) -> None:
        if self._distortion_preview_timer.isActive():
            self._pending_distortion = value
        else:
            self.distortion_preview.emit(value)
            self._distortion_preview_timer.start()
        self._distortion_settle_timer.start()

    def _flush_distortion_preview(self) -> None:
        if self._pending_distortion is not None:
            value, self._pending_distortion = self._pending_distortion, None
            self.distortion_preview.emit(value)
            self._distortion_preview_timer.start()

    def set_distortion(self, k1: float) -> None:
        """Sync the slider without emitting anything."""
        self._distortion.set_value(k1)

    def current_guide(self) -> tuple[str, int]:
        return self._guide_combo.currentData(), self._guide_orientation

    def _refresh_guide_button(self) -> None:
        guide = CropGuide(self._guide_combo.currentData())
        self._guide_orient_btn.setEnabled(guide in ORIENTATION_COUNT)

    def _on_guide_changed(self, _index: int) -> None:
        self._guide_orientation = 0
        self._refresh_guide_button()
        qsettings().setValue(_GUIDE_KEY, self._guide_combo.currentData())
        self.guide_changed.emit(*self.current_guide())

    def _on_guide_orient(self) -> None:
        guide = CropGuide(self._guide_combo.currentData())
        count = ORIENTATION_COUNT.get(guide, 1)
        self._guide_orientation = (self._guide_orientation + 1) % count
        self.guide_changed.emit(*self.current_guide())

    def _on_fine_changed(self, value: float) -> None:
        if self._fine_preview_timer.isActive():
            self._pending_fine = value
        else:
            self.fine_rotation_preview.emit(value)
            self._fine_preview_timer.start()
        self._fine_settle_timer.start()

    def _flush_fine_preview(self) -> None:
        if self._pending_fine is not None:
            value, self._pending_fine = self._pending_fine, None
            self.fine_rotation_preview.emit(value)
            self._fine_preview_timer.start()

    def set_fine_rotation(self, degrees: float) -> None:
        """Sync the slider without emitting anything."""
        self._fine.set_value(degrees)

    def straighten_active(self) -> bool:
        return self._straighten_btn.isChecked()

    def set_straighten_active(self, active: bool) -> None:
        """Sync the Straighten Tool button without emitting anything (the tool finished, or another tool took over)."""
        self._straighten_btn.blockSignals(True)
        self._straighten_btn.setChecked(active)
        self._straighten_btn.blockSignals(False)

    def is_crop_active(self) -> bool:
        return self._crop_btn.isChecked()

    def set_crop_mode(self, enabled: bool) -> None:
        """Sync the Crop button without emitting anything - a crop just
        got applied/cleared and exited crop mode on its own."""
        self._crop_btn.blockSignals(True)
        self._crop_btn.setChecked(enabled)
        self._crop_btn.blockSignals(False)

    def reset(self) -> None:
        """Back to no flips, crop mode off, without emitting anything -
        used when a new file is opened, since the controller has already
        reset its own state as part of that load."""
        self._flip_h_btn.blockSignals(True)
        self._flip_h_btn.setChecked(False)
        self._flip_h_btn.blockSignals(False)
        self._flip_v_btn.blockSignals(True)
        self._flip_v_btn.setChecked(False)
        self._flip_v_btn.blockSignals(False)
        self.set_crop_mode(False)
        self.set_straighten_active(False)
        self._fine_settle_timer.stop()
        self._pending_fine = None
        self.set_fine_rotation(0.0)
        self._distortion_settle_timer.stop()
        self._pending_distortion = None
        self.set_distortion(0.0)
        self.set_auto_adjust_enabled(False)

    def set_flips(self, flip_h: bool, flip_v: bool) -> None:
        """Sync the flip buttons without emitting anything - used after a history revert."""
        self._flip_h_btn.blockSignals(True)
        self._flip_h_btn.setChecked(flip_h)
        self._flip_h_btn.blockSignals(False)
        self._flip_v_btn.blockSignals(True)
        self._flip_v_btn.setChecked(flip_v)
        self._flip_v_btn.blockSignals(False)
