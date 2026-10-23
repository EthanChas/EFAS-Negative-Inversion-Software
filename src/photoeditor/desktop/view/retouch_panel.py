from PyQt6.QtCore import QPointF, QRectF, QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PyQt6.QtWidgets import QColorDialog, QComboBox, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

from ...features.masks import model as M
from ...features.retouchdt import logic as R
from ...theme.tokens import THEME
from . import panel_icons
from .blend_box import SHAPE_ICONS, tool_button
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200
_LABEL_WIDTH = 90
_ALGO_ICONS = {R.CLONE: "mask-clone", R.HEAL: "mask-heal", R.BLUR: "mask-blur", R.FILL: "mask-fill"}
_ALGO_TIPS = {
    R.CLONE: "Clone: copy the picture from the shape's source over the shape. Ctrl+click changes the picked shape between clone and heal.",
    R.HEAL: "Heal: like clone, but the source's detail is fitted to the colours round the shape. Ctrl+click changes the picked shape between heal and clone.",
    R.BLUR: "Blur: blur what is inside the shape. Ctrl+click changes the picked shape between blur and fill.",
    R.FILL: "Fill: paint the shape with a colour, or erase it. Ctrl+click changes the picked shape between fill and blur.",
}
_SHAPES = (M.PATH, M.ELLIPSE, M.CIRCLE, M.BRUSH)     # darktable's order of the buttons
_BOXES = R.MAX_SCALES + 2                              # the picture, 15 detail scales, the residual


def _srgb(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


class ScaleBar(QWidget):
    """darktable's wavelet decompose bar: a box for the picture itself (0), for each wavelet scale (finest first) and for the residual. Click a box to work on that scale; drag along the
    lower edge to set how many scales the picture is split into; drag along the upper edge to set the scale from which the layers are merged into one; scroll to step through the scales.
    A dot marks a scale that has shapes."""

    scale_selected = pyqtSignal(int)
    num_scales_changed = pyqtSignal(int)
    merge_changed = pyqtSignal(int)

    _MARGIN = 11

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(56)
        self.setMinimumWidth(180)
        self.setMouseTracking(True)
        self.num_scales, self.curr_scale, self.merge_from = 0, 0, 0
        self.shapes: dict[int, int] = {}
        self._drag: str | None = None
        self.setToolTip("Click a box to work on that wavelet scale: 0 is the picture itself, then the scales from fine detail to coarse, then the residual (R).\n"
                        "Drag along the lower edge to set how many scales, along the upper edge to merge the scales from there on. Scroll to step through.")

    def sizeHint(self) -> QSize:
        return QSize(240, 56)

    def set_state(self, num_scales: int, curr_scale: int, merge_from: int, shapes: dict) -> None:
        self.num_scales, self.curr_scale, self.merge_from, self.shapes = num_scales, curr_scale, merge_from, dict(shapes)
        self.update()

    def _geometry(self):
        left, right = 4.0, self.width() - 4.0
        return left, (right - left) / _BOXES

    def _box_at(self, x: float) -> int:
        left, w = self._geometry()
        return int(max(0, min(_BOXES - 1, (x - left) // w)))

    def _paint_box(self, p: QPainter, i: int, rect: QRectF) -> None:
        n = self.num_scales
        residual = n + 1
        if i == 0:
            colour = QColor(THEME.text_secondary)
        elif i <= n:
            t = (i - 1) / max(1, R.MAX_SCALES - 1)
            colour = QColor.fromHsvF(0.58 - 0.3 * t, 0.45, 0.8)
        elif i == residual:
            colour = QColor(THEME.accent_primary)
        else:
            colour = QColor(THEME.bg_input)
        p.fillRect(rect, colour)
        if i == self.curr_scale:
            p.setPen(QPen(QColor(THEME.text_primary), 2.0))
            p.drawRect(rect.adjusted(1, 1, -1, -1))
        text = "0" if i == 0 else ("R" if i == residual else (str(i) if i <= n else ""))
        if text:
            p.setPen(QColor("#101010"))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        if self.shapes.get(i):
            p.setBrush(QColor(255, 204, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(rect.center().x(), rect.bottom() - 7), 2.5, 2.5)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        f = QFont(self.font())
        f.setPixelSize(9)
        p.setFont(f)
        left, w = self._geometry()
        top, bottom = self._MARGIN, self.height() - self._MARGIN
        for i in range(_BOXES):
            self._paint_box(p, i, QRectF(left + i * w + 1, top, w - 2, bottom - top))
        n = self.num_scales
        if n > 0 and self.merge_from > 0:     # the layers from here on are acted on as one
            p.fillRect(QRectF(left + self.merge_from * w + 1, 2, (n - self.merge_from + 1) * w - 2, self._MARGIN - 4), QColor(THEME.status_warning))
        p.setPen(QPen(QColor(THEME.text_primary), 1.5))
        x = left + (n + 1) * w
        p.drawLine(QPointF(x, bottom + 1), QPointF(x, self.height() - 2))      # where the scales end: the residual is the box before this edge
        p.end()

    def _band(self, y: float) -> str:
        return "merge" if y < self._MARGIN else ("scales" if y > self.height() - self._MARGIN else "pick")

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._drag = self._band(event.position().y())
        self._apply(event.position().x())

    def mouseMoveEvent(self, event) -> None:
        if self._drag in ("merge", "scales"):
            self._apply(event.position().x())

    def mouseReleaseEvent(self, event) -> None:
        self._drag = None

    def _apply(self, x: float) -> None:
        i = self._box_at(x)
        if self._drag == "pick":
            if i <= self.num_scales + 1:
                self.scale_selected.emit(i)
        elif self._drag == "scales":
            self.num_scales_changed.emit(min(i, R.MAX_SCALES))
        elif self._drag == "merge":
            self.merge_changed.emit(min(i, self.num_scales))

    def wheelEvent(self, event) -> None:
        step = 1 if event.angleDelta().y() > 0 else -1
        new = max(0, min(self.num_scales + 1, self.curr_scale + step))
        if new != self.curr_scale:
            self.scale_selected.emit(new)
        event.accept()


class RetouchPanel(CollapsiblePanel):
    """Retouch, ported from darktable: clone, heal, blur and fill on shapes drawn on the picture, each on a wavelet scale (frequency separation).

    Choose what the next shape will do (the four buttons), then draw it with a shape button (Ctrl+click a button to keep drawing). Click a shape on the picture to pick it: the panel then shows
    its settings, and the blur and fill settings change that shape. The bar chooses the wavelet scale the shapes are drawn on and acted on; the scale can be looked at (with levels, since a detail
    layer is mostly grey), the shapes' mask can be shown, and the picture can be seen without Retouch."""

    draw_requested = pyqtSignal(str, bool)          # shape kind, keep drawing
    edit_toggled = pyqtSignal(bool)
    algorithm_chosen = pyqtSignal(str, bool)        # the algorithm, Ctrl held (change the picked shape too)
    changed = pyqtSignal(dict, str, bool, int)      # settings changes, what to call it in the history, a drag still going on, the picked shape (0 none)
    view_changed = pyqtSignal(str)
    paste_requested = pyqtSignal(int, int)          # from scale, to scale
    opacity_changed = pyqtSignal(int, float, bool)  # picked shape, opacity, a drag still going on

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Retouch",
            help_text=(
                "Retouch, ported from darktable: remove spots and blemishes, or work on skin, with shapes drawn on the picture.\n\n"
                "1. Choose what the shape will do: clone (copy from a source), heal (copy, then match the colours round it), blur, or fill (a colour, or erase).\n"
                "2. Draw it with a shape button (path, ellipse, circle, brush; Ctrl+click a button to keep drawing). For clone and heal drag the dashed copy of the shape to where it "
                "should copy from. Shift+click before placing sets the source of the next shapes (kept the same distance from each), Ctrl+Shift+click one source for all.\n"
                "3. Scroll over a shape to change its size, Shift+scroll its feather, Ctrl+scroll its opacity. Click a shape to pick it: Blur and Fill then change that shape.\n\n"
                "The scale bar splits the picture into wavelet scales: 0 is the picture as it is, 1 to N are layers of detail from fine to coarse, R is what is left (the broad colour and light). "
                "Shapes act on the scale they were drawn on - heal a blemish's colour on R and its texture on 1 or 2. Drag along the bar's lower edge to set how many scales; drag along "
                "its upper edge to merge the scales from there on into one layer. The scales are counted in the pixels of the picture being made, so the small preview shows a wider area per "
                "scale than the export: check at 100%.\n\n"
                "The eye-and-layers button shows the scale you are working on (with levels to make it visible), the mask button shows where the shapes act, and the last button shows the picture "
                "without Retouch."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)
        self._building = False
        self._picked = 0
        self._settings = R.Settings()
        self._shown_algo = R.HEAL

        head = QHBoxLayout()
        head.setSpacing(THEME.space_sm)
        head.addWidget(QLabel("Shapes"))
        self._count = QLabel("0")
        head.addWidget(self._count)
        head.addStretch(1)
        self._edit = tool_button("mask-edit", "Show the shapes of this scale on the picture, to move and reshape them", checkable=True)
        self._edit.toggled.connect(self.edit_toggled.emit)
        head.addWidget(self._edit)
        self._draw: dict[str, QToolButton] = {}
        for kind in _SHAPES:
            b = tool_button(SHAPE_ICONS[kind], f"Draw a {kind} (Ctrl+click keeps drawing)")
            b.clicked.connect(lambda _=False, k=kind: self.draw_requested.emit(k, bool(_ctrl_held())))
            head.addWidget(b)
            self._draw[kind] = b
        body.addLayout(head)

        algo = QHBoxLayout()
        algo.setSpacing(THEME.space_sm)
        algo.addWidget(QLabel("Algorithm"))
        algo.addStretch(1)
        self._algo: dict[str, QToolButton] = {}
        for a in R.ALGORITHMS:
            b = tool_button(_ALGO_ICONS[a], _ALGO_TIPS[a], checkable=True)
            b.clicked.connect(lambda _=False, name=a: self.algorithm_chosen.emit(name, bool(_ctrl_held())))
            algo.addWidget(b)
            self._algo[a] = b
        algo.addSpacing(THEME.space_md)
        self._show_mask = tool_button("mask-eye", "Show where the shapes of this scale act", checkable=True)
        self._show_mask.toggled.connect(lambda on: self._view_toggled("mask", on))
        self._suppress = tool_button("mask-eye-off", "Show the picture without Retouch", checkable=True)
        self._suppress.toggled.connect(lambda on: self._view_toggled("suppress", on))
        algo.addWidget(self._show_mask)
        algo.addWidget(self._suppress)
        body.addLayout(algo)

        self._picked_label = QLabel("Picked: none")
        self._picked_label.setProperty("role", "hint")
        body.addWidget(self._picked_label)

        self._bar = ScaleBar()
        self._bar.scale_selected.connect(lambda i: self.changed.emit({"curr_scale": i}, "", False, 0))
        self._bar.num_scales_changed.connect(lambda n: self.changed.emit({"num_scales": n}, f"Retouch: {n} wavelet scales", False, 0))
        self._bar.merge_changed.connect(lambda m: self.changed.emit({"merge_from_scale": m}, f"Retouch: merge from scale {m}", False, 0))
        body.addWidget(self._bar)
        self._scale_labels = QLabel("")
        self._scale_labels.setProperty("role", "hint")
        body.addWidget(self._scale_labels)

        tools = QHBoxLayout()
        tools.setSpacing(THEME.space_sm)
        self._cut = QPushButton("Cut shapes")
        self._cut.setToolTip("Pick up the shapes of this scale, to put on another scale with Paste")
        self._cut.clicked.connect(self._cut_scale)
        self._paste = QPushButton("Paste shapes")
        self._paste.setToolTip("Move the shapes cut from a scale onto this scale")
        self._paste.setEnabled(False)
        self._paste.clicked.connect(self._paste_scale)
        self._view_scale = tool_button("mask-source", "Show the wavelet scale being worked on (0 is the picture)", checkable=True)
        self._view_scale.toggled.connect(lambda on: self._view_toggled("scale", on))
        tools.addWidget(self._cut)
        tools.addWidget(self._paste)
        tools.addStretch(1)
        tools.addWidget(self._view_scale)
        body.addLayout(tools)
        self._cut_from = -1

        self._levels_box = QWidget()
        lv = QVBoxLayout(self._levels_box)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(THEME.space_sm)
        self._levels: list[SliderRow] = []
        for name in ("Black", "Middle", "White"):
            row = SliderRow(name, min_value=R.PREVIEW_LVL_MIN, max_value=R.PREVIEW_LVL_MAX, reset_value=0.0 if name == "Middle" else (R.PREVIEW_LVL_MIN if name == "Black" else R.PREVIEW_LVL_MAX),
                            decimals=2, step=0.01, label_width=_LABEL_WIDTH)
            row.value_changed.connect(self._levels_moved)
            lv.addWidget(row)
            self._levels.append(row)
        self._auto = QPushButton("Auto levels")
        self._auto.setToolTip("Fit the levels to the scale shown")
        self._auto.clicked.connect(lambda: self.changed.emit({"preview_auto": True}, "", False, 0))
        lv.addWidget(self._auto)
        body.addWidget(self._levels_box)

        self._blur_box = QWidget()
        bl = QVBoxLayout(self._blur_box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(THEME.space_sm)
        row = QHBoxLayout()
        row.addWidget(QLabel("Blur type"))
        self._blur_type = QComboBox()
        self._blur_type.addItem("Gaussian", R.GAUSSIAN)
        self._blur_type.addItem("Bilateral", R.BILATERAL)
        self._blur_type.setToolTip("Gaussian blurs everything; bilateral smooths the lightness but keeps edges")
        self._blur_type.activated.connect(self._blur_changed)
        row.addWidget(self._blur_type, 1)
        bl.addLayout(row)
        self._blur_radius = SliderRow("Blur radius", min_value=0.1, max_value=200.0, reset_value=10.0, decimals=1, step=0.5, label_width=_LABEL_WIDTH)
        self._blur_radius.setToolTip("Radius of the blur, in pixels of the scan")
        self._blur_radius.value_changed.connect(self._blur_dragged)
        bl.addWidget(self._blur_radius)
        body.addWidget(self._blur_box)

        self._fill_box = QWidget()
        fl = QVBoxLayout(self._fill_box)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(THEME.space_sm)
        row = QHBoxLayout()
        row.addWidget(QLabel("Fill mode"))
        self._fill_mode = QComboBox()
        self._fill_mode.addItem("Erase", R.ERASE)
        self._fill_mode.addItem("Color", R.COLOR)
        self._fill_mode.activated.connect(self._fill_changed)
        row.addWidget(self._fill_mode, 1)
        self._colour = QPushButton("Pick colour")
        self._colour.clicked.connect(self._pick_colour)
        row.addWidget(self._colour)
        fl.addLayout(row)
        self._fill_brightness = SliderRow("Brightness", min_value=-1.0, max_value=1.0, reset_value=0.0, decimals=2, step=0.01, label_width=_LABEL_WIDTH)
        self._fill_brightness.value_changed.connect(self._fill_dragged)
        fl.addWidget(self._fill_brightness)
        body.addWidget(self._fill_box)

        self._opacity = SliderRow("Shape opacity", min_value=0.05, max_value=1.0, reset_value=1.0, decimals=2, step=0.05, label_width=_LABEL_WIDTH)
        self._opacity.setToolTip("How much of the picked shape's result is let in (Ctrl+scroll over the shape does the same)")
        self._opacity.value_changed.connect(lambda v: None if self._building else self.opacity_changed.emit(self._picked, v, True))
        self._opacity.setVisible(False)
        body.addWidget(self._opacity)
        self._opacity_timer = QTimer(self)
        self._opacity_timer.setSingleShot(True)
        self._opacity_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._opacity_timer.timeout.connect(lambda: self.opacity_changed.emit(self._picked, self._opacity.value(), False))
        self._opacity.value_changed.connect(lambda _v: self._opacity_timer.start())

        self._note = QLabel("")
        self._note.setProperty("role", "hint")
        self._note.setWordWrap(True)
        body.addWidget(self._note)

        self._pending: tuple | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._preview_timer.timeout.connect(self._flush_preview)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._settle_timer.timeout.connect(self._settle)
        self._settle_args: tuple | None = None
        self._show_parts()

    # ------------------------------------------------------------ showing the photo's Retouch
    def set_settings(self, s: R.Settings, picked: R.FormSetting | None = None, opacity: float | None = None) -> None:
        """Show these settings (the photo changed, or an undo) and the settings of the picked shape, if any."""
        self._settings = s
        self._building = True
        try:
            algo = picked.algorithm if picked is not None else s.algorithm
            for a, b in self._algo.items():
                b.setChecked(a == algo)
            self._count.setText(str(len(s.forms)))
            shapes: dict[int, int] = {}
            for f in s.forms:
                shapes[f.scale] = shapes.get(f.scale, 0) + 1
            self._bar.set_state(s.num_scales, s.curr_scale, s.merge_from_scale, shapes)
            merge = f", merge from {s.merge_from_scale}" if s.merge_from_scale else ""
            self._scale_labels.setText(f"Scale {'R (residual)' if s.curr_scale == s.num_scales + 1 else s.curr_scale} of {s.num_scales}{merge}")
            for row, v in zip(self._levels, s.preview_levels):
                row.set_value(v)
            self._levels_box.setVisible(self._view_scale.isChecked())
            self._auto.setText("Auto levels (on)" if s.preview_auto else "Auto levels")
            blur = picked if picked is not None and picked.algorithm == R.BLUR else None
            fill = picked if picked is not None and picked.algorithm == R.FILL else None
            self._blur_type.setCurrentIndex(max(0, self._blur_type.findData((blur.blur_type if blur else s.blur_type))))
            self._blur_radius.set_value(blur.blur_radius if blur else s.blur_radius)
            self._fill_mode.setCurrentIndex(max(0, self._fill_mode.findData((fill.fill_mode if fill else s.fill_mode))))
            self._fill_brightness.set_value(fill.fill_brightness if fill else s.fill_brightness)
            self._shown_algo = algo
            self._set_colour_swatch(fill.fill_color if fill else s.fill_color)
            self._picked = picked.formid if picked is not None else 0
            self._picked_label.setText("Picked: none" if picked is None else f"Picked: shape {picked.formid} ({picked.algorithm}, scale {'R' if picked.scale == s.num_scales + 1 else picked.scale})")
            self._opacity.setVisible(picked is not None)
            if picked is not None and opacity is not None:
                self._opacity.set_value(opacity)
        finally:
            self._building = False
        self._show_parts()

    def set_tool_state(self, editing: bool) -> None:
        self._edit.blockSignals(True)
        self._edit.setChecked(editing)
        self._edit.blockSignals(False)

    def set_note(self, text: str) -> None:
        self._note.setText(text)

    def set_view(self, view: str) -> None:
        """Show which of the view buttons is on (no signal)."""
        for b, name in ((self._show_mask, "mask"), (self._suppress, "suppress"), (self._view_scale, "scale")):
            b.blockSignals(True)
            b.setChecked(view == name)
            b.blockSignals(False)
        self._levels_box.setVisible(view == "scale")

    def view(self) -> str:
        for b, name in ((self._view_scale, "scale"), (self._show_mask, "mask"), (self._suppress, "suppress")):
            if b.isChecked():
                return name
        return ""

    def _show_parts(self) -> None:
        algo = self._shown_algo
        self._blur_box.setVisible(algo == R.BLUR)
        self._fill_box.setVisible(algo == R.FILL)
        self._colour.setVisible(self._fill_mode.currentData() == R.COLOR)

    def _set_colour_swatch(self, linear) -> None:
        c = QColor.fromRgbF(*(_srgb(v) for v in list(linear)[:3]))
        self._colour.setStyleSheet(f"background-color: {c.name()}; color: {'#000' if c.lightness() > 128 else '#fff'};")

    # ------------------------------------------------------------ the person's choices
    def _view_toggled(self, name: str, on: bool) -> None:
        if on:
            for b, other in ((self._show_mask, "mask"), (self._suppress, "suppress"), (self._view_scale, "scale")):
                if other != name:
                    b.blockSignals(True)
                    b.setChecked(False)
                    b.blockSignals(False)
        self._levels_box.setVisible(name == "scale" and on)
        self.view_changed.emit(name if on else "")

    def _cut_scale(self) -> None:
        self._cut_from = self._settings.curr_scale
        self._paste.setEnabled(any(f.scale == self._cut_from for f in self._settings.forms))
        self.set_note(f"Shapes of scale {self._cut_from} picked up: go to another scale and press Paste shapes.")

    def _paste_scale(self) -> None:
        if self._cut_from >= 0 and self._cut_from != self._settings.curr_scale:
            self.paste_requested.emit(self._cut_from, self._settings.curr_scale)
            self._cut_from = -1
            self._paste.setEnabled(False)
            self.set_note("")

    def _levels_moved(self, _v=None) -> None:
        if self._building:
            return
        black, middle, white = (r.value() for r in self._levels)
        self._queue({"preview_levels": [black, middle, white], "preview_auto": False}, "")

    def _blur_changed(self, _i=None) -> None:
        if not self._building:
            self.changed.emit({"blur_type": self._blur_type.currentData()}, "Retouch: blur type", False, self._picked)

    def _blur_dragged(self, v: float) -> None:
        if not self._building:
            self._queue({"blur_radius": v}, "Retouch: blur radius")

    def _fill_changed(self, _i=None) -> None:
        self._show_parts()
        if not self._building:
            self.changed.emit({"fill_mode": self._fill_mode.currentData()}, "Retouch: fill mode", False, self._picked)

    def _fill_dragged(self, v: float) -> None:
        if not self._building:
            self._queue({"fill_brightness": v}, "Retouch: fill brightness")

    def _pick_colour(self) -> None:
        start = QColor.fromRgbF(*(_srgb(v) for v in self._settings.fill_color[:3]))
        c = QColorDialog.getColor(start, self, "Fill colour")
        if c.isValid():
            self.changed.emit({"fill_color": [_linear(c.redF()), _linear(c.greenF()), _linear(c.blueF())]}, "Retouch: fill colour", False, self._picked)

    def _queue(self, changes: dict, description: str) -> None:
        """A slider moved: the picture follows at a steady rate, and the final value is one step in the history."""
        args = (changes, description, self._picked)
        self._settle_args = args
        if self._preview_timer.isActive():
            self._pending = args
        else:
            self.changed.emit(changes, description, True, self._picked)
            self._preview_timer.start()
        self._settle_timer.start()

    def _flush_preview(self) -> None:
        if self._pending is not None:
            changes, description, picked = self._pending
            self._pending = None
            self.changed.emit(changes, description, True, picked)
            self._preview_timer.start()

    def _settle(self) -> None:
        if self._settle_args is not None:
            changes, description, picked = self._settle_args
            self._settle_args = None
            self._pending = None
            self.changed.emit(changes, description, False, picked)


def _ctrl_held() -> bool:
    from PyQt6.QtWidgets import QApplication
    return bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)
