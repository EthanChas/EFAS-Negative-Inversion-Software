from PyQt6.QtCore import QPointF, QRectF, QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QApplication, QColorDialog, QComboBox, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

from ...features.masks import model as M
from ...features.retouchdt import logic as R
from ...theme.tokens import THEME
from .blend_box import SHAPE_ICONS, tool_button
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200
_LABEL_WIDTH = 90
_ALGO_ICONS = {R.CLONE: "mask-clone", R.HEAL: "mask-heal", R.BLUR: "mask-blur", R.FILL: "mask-fill"}
_ALGO_TIPS = {
    R.BLUR: "activate blur tool\nctrl+click to change tool for current form\nshift+click to set the tool as default",
    R.FILL: "activate fill tool\nctrl+click to change tool for current form\nshift+click to set the tool as default",
    R.CLONE: "activate cloning tool\nctrl+click to change tool for current form\nshift+click to set the tool as default",
    R.HEAL: "activate healing tool\nctrl+click to change tool for current form\nshift+click to set the tool as default",
}
_SHAPES = (M.BRUSH, M.PATH, M.ELLIPSE, M.CIRCLE)     # darktable's order of the buttons
_SHAPE_TIPS = {M.BRUSH: "add brush", M.PATH: "add path", M.ELLIPSE: "add ellipse", M.CIRCLE: "add circle"}
_BOXES = R.MAX_SCALES + 2                              # the picture, 15 detail scales, the residual (darktable's RETOUCH_NO_SCALES)
_INSET_RATIO = 0.2                                     # darktable's RT_WDBAR_INSET

# the bar's colours (darktable's rt_wdbar_draw)
_BORDER, _ORIGINAL, _INACTIVE, _ACTIVE, _MERGE, _RESIDUAL, _SHAPES_COLOUR = (QColor.fromRgbF(*c) for c in (
    (0.066, 0.066, 0.066), (0.1, 0.1, 0.1), (0.15, 0.15, 0.15), (0.35, 0.35, 0.35), (0.5, 0.5, 0.5), (0.8, 0.8, 0.8), (0.75, 0.5, 0.0)))


def _srgb(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _ctrl_held() -> bool:
    return bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)


def _shift_held() -> bool:
    return bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "subtitle")
    return label


class ScaleBar(QWidget):
    """darktable's wavelet decompose bar. A box for the picture itself (0), for each wavelet scale (finest first, 1 to 15) and for the residual (the lighter box after the last scale).
    Click a box to work on that scale (the dot marks the one you are on). The top arrow sets where the layers start to be merged into one; the bottom arrow sets how many scales there are:
    drag it, or click the strip it is in. Scroll to step: over the top strip the merge scale, over the bottom strip the number of scales, elsewhere the scale you work on.
    The line along the top of a box says the scale is still visible at this size of picture; the orange line along the bottom says it has shapes on it."""

    scale_selected = pyqtSignal(int)
    num_scales_changed = pyqtSignal(int)
    merge_changed = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setMinimumWidth(180)
        self.setMouseTracking(True)
        self.num_scales, self.curr_scale, self.merge_from = 0, 0, 0
        self.first_visible = 0
        self.shapes: dict[int, int] = {}
        self._mouse = (-1.0, -1.0)
        self._hover = -1
        self._lower = self._upper = self._lower_cursor = self._upper_cursor = False
        self._drag = ""
        self.setToolTip("top slider adjusts where the merge scales start\nbottom slider adjusts the number of scales\ndot indicates the current scale\n"
                        "top line indicates that the scale is visible at current zoom level\nbottom line indicates that the scale has shapes on it")

    def sizeHint(self) -> QSize:
        return QSize(240, 40)

    def set_state(self, num_scales: int, curr_scale: int, merge_from: int, shapes: dict, first_visible: int = 0) -> None:
        self.num_scales, self.curr_scale, self.merge_from, self.shapes, self.first_visible = num_scales, curr_scale, merge_from, dict(shapes), first_visible
        self.update()

    # ------------------------------------------------------------ geometry
    def _inset(self) -> int:
        return round(_INSET_RATIO * self.height())

    def _box_w(self) -> float:
        return (self.width() - 2.0 * self._inset()) / _BOXES

    def _sh(self) -> float:
        return 3.0 + self._inset()

    # ------------------------------------------------------------ painting
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), _INACTIVE)
        inset, sh, bw = self._inset(), self._sh(), self._box_w()
        bh = self.height() - 2.0 * sh
        n, merge = self.num_scales, self.merge_from
        first = self.first_visible if self.first_visible > 0 else R.MAX_SCALES
        for i in range(_BOXES):
            if i == 0:
                colour = _ORIGINAL
            elif i == n + 1:
                colour = _RESIDUAL
            elif merge > 0 and merge <= i <= n:
                colour = _MERGE
            elif i <= n:
                colour = _ACTIVE
            else:
                colour = _INACTIVE
            box = QRectF(bw * i + inset, sh, bw, bh)
            p.fillRect(box, colour)
            if first <= i <= n:                                        # this scale has detail at this size of picture
                p.fillRect(QRectF(bw * i + inset, 1.0, bw, 2.0), _MERGE)
            if self.shapes.get(i):                                     # and this one has shapes
                p.fillRect(QRectF(bw * i + inset + 0.5, self.height() - sh, bw - 1.0, 2.0), _SHAPES_COLOUR)
            p.setPen(QPen(_BORDER, 1.0))
            p.drawRect(box)
        # the dot of the scale being worked on
        if 0 <= self.curr_scale < _BOXES:
            p.setBrush(_ACTIVE if (merge > 0 and merge <= self.curr_scale <= n) else _MERGE)
            p.setPen(Qt.PenStyle.NoPen)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.drawEllipse(QPointF(bw * (0.5 + self.curr_scale) + inset, 0.5 * bh + sh), 0.5 * inset, 0.5 * inset)
        # the box under the mouse
        if self._hover >= 0:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_INACTIVE if self._hover == n + 1 else _RESIDUAL, 1.0))
            p.drawRect(QRectF(bw * self._hover + inset + 1, sh + 1, bw - 2, bh - 2))
        # the two arrows: number of scales below (pointing up), where merging starts above (pointing down)
        self._arrow(p, bw * (0.5 + n) + inset, bh + sh + 2.0, up=True, hot=self._lower_cursor or self._drag == "scales")
        self._arrow(p, bw * (0.5 + merge) + inset, sh - 2.0, up=False, hot=self._upper_cursor or self._drag == "merge")
        p.end()

    def _arrow(self, p: QPainter, cx: float, tip_y: float, up: bool, hot: bool) -> None:
        half = float(self._inset())
        height = 1.4 * half
        base_y = tip_y + height if up else tip_y - height
        tri = QPolygonF([QPointF(cx, tip_y), QPointF(cx - half, base_y), QPointF(cx + half, base_y)])
        colour = QColor.fromRgbF(0.67, 0.67, 0.67) if hot else QColor.fromRgbF(0.54, 0.54, 0.54)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(colour, 1.2))
        p.setBrush(colour if hot else Qt.BrushStyle.NoBrush)
        p.drawPolygon(tri)

    # ------------------------------------------------------------ the mouse
    def _track(self, pos) -> None:
        inset, bw, sh = self._inset(), self._box_w(), self._sh()
        x = max(0.0, min(self.width() - 2.0 * inset - 1.0, pos.x() - inset))
        self._mouse = (x, pos.y())
        self._hover = int(x / bw)
        self._lower = self._upper = self._lower_cursor = self._upper_cursor = False
        if pos.y() <= sh:
            self._upper = True
            middle = bw * (0.5 + self.merge_from)
            self._upper_cursor = middle - inset <= x <= middle + inset
            if not self._drag:
                self._hover = -1
        elif pos.y() >= self.height() - sh:
            self._lower = True
            middle = bw * (0.5 + self.num_scales)
            self._lower_cursor = middle - inset <= x <= middle + inset
            if not self._drag:
                self._hover = -1
        if self._drag == "scales" and self._hover >= 0:
            self.num_scales_changed.emit(min(self._hover, R.MAX_SCALES))
        elif self._drag == "merge" and self._hover >= 0:
            self.merge_changed.emit(min(self._hover, self.num_scales))
        self.update()

    def mouseMoveEvent(self, event) -> None:
        self._track(event.position())

    def leaveEvent(self, event) -> None:
        self._mouse, self._hover = (-1.0, -1.0), -1
        self._lower = self._upper = self._lower_cursor = self._upper_cursor = False
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._track(event.position())
        bw = self._box_w()
        if self._lower:
            if self._lower_cursor:
                self._drag = "scales"
            else:
                self.num_scales_changed.emit(min(int(self._mouse[0] / bw), R.MAX_SCALES))
        elif self._upper:
            if self._upper_cursor:
                self._drag = "merge"
            else:
                self.merge_changed.emit(min(int(self._mouse[0] / bw), self.num_scales))
        elif self._hover >= 0:
            self.scale_selected.emit(self._hover)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = ""
            self.update()

    def wheelEvent(self, event) -> None:
        step = 1 if event.angleDelta().y() > 0 else -1
        if self._lower:
            self.num_scales_changed.emit(max(0, min(R.MAX_SCALES, self.num_scales + step)))
        elif self._upper:
            self.merge_changed.emit(max(0, min(self.num_scales, self.merge_from + step)))
        else:
            self.scale_selected.emit(max(0, min(R.MAX_SCALES + 1, self.curr_scale + step)))
        event.accept()


class LevelsSlider(QWidget):
    """darktable's "preview levels" slider: a black-to-grey gradient with three markers, the black point, the middle and the white point, between -3 and 3. Drag a marker; double-click resets."""

    value_changed = pyqtSignal(list)
    _MIN_GAP = 0.05

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(28)
        self.setMinimumWidth(120)
        self.values = [R.PREVIEW_LVL_MIN, 0.0, R.PREVIEW_LVL_MAX]
        self._grab = -1
        self.setToolTip("adjust preview levels (double-click to reset)")

    def set_values(self, values) -> None:
        self.values = [float(v) for v in values]
        self.update()

    def _x(self, v: float) -> float:
        return 8.0 + (v - R.PREVIEW_LVL_MIN) / (R.PREVIEW_LVL_MAX - R.PREVIEW_LVL_MIN) * (self.width() - 16.0)

    def _value(self, x: float) -> float:
        return R.PREVIEW_LVL_MIN + (x - 8.0) / max(1.0, self.width() - 16.0) * (R.PREVIEW_LVL_MAX - R.PREVIEW_LVL_MIN)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        bar = QRectF(8, 4, self.width() - 16, 10)
        g = QLinearGradient(bar.left(), 0, bar.right(), 0)
        g.setColorAt(0.0, QColor(0, 0, 0))
        g.setColorAt(1.0, QColor(128, 128, 128))
        p.fillRect(bar, g)
        p.setPen(QPen(_BORDER, 1.0))
        p.drawRect(bar)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for i, v in enumerate(self.values):
            x = self._x(v)
            tri = QPolygonF([QPointF(x, bar.bottom() + 1), QPointF(x - 6, bar.bottom() + 11), QPointF(x + 6, bar.bottom() + 11)])
            p.setPen(QPen(QColor(THEME.text_primary), 1.2))
            p.setBrush(QColor(THEME.text_primary) if i == 1 else Qt.BrushStyle.NoBrush)
            p.drawPolygon(tri)
        p.end()

    def mousePressEvent(self, event) -> None:
        x = event.position().x()
        self._grab = min(range(3), key=lambda i: abs(self._x(self.values[i]) - x))
        self._move(x)

    def mouseMoveEvent(self, event) -> None:
        if self._grab >= 0:
            self._move(event.position().x())

    def mouseReleaseEvent(self, event) -> None:
        self._grab = -1

    def mouseDoubleClickEvent(self, event) -> None:
        self.values = [R.PREVIEW_LVL_MIN, 0.0, R.PREVIEW_LVL_MAX]
        self.update()
        self.value_changed.emit(list(self.values))

    def _move(self, x: float) -> None:
        v, i, gap = self._value(x), self._grab, self._MIN_GAP
        lo = R.PREVIEW_LVL_MIN if i == 0 else self.values[i - 1] + gap
        hi = R.PREVIEW_LVL_MAX if i == 2 else self.values[i + 1] - gap
        self.values[i] = max(lo, min(hi, v))
        self.update()
        self.value_changed.emit(list(self.values))


class RetouchPanel(CollapsiblePanel):
    """Retouch, ported from darktable, laid out as darktable lays it out: *retouch tools* (the shape buttons and the four algorithms), *wavelet decompose* (the scale bar, its labels and
    buttons), *preview single scale* (the levels for looking at a scale), and *shapes* (the picked shape's blur or fill settings and its opacity).

    Choose what the next shape will do, then draw it with a shape button (Ctrl+click a button to keep drawing). Click a shape to pick it: the settings below then change that shape."""

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
                "RETOUCH TOOLS: choose what the shape will do - blur, fill (a colour, or erase), clone (copy from a source) or heal (copy, then match the colours round it) - then press a shape "
                "button (brush, path, ellipse, circle; Ctrl+click keeps drawing) and click on the picture. For clone and heal drag the dashed copy of the shape to where it should copy from; "
                "Shift+click before placing sets the source of the next shapes (kept the same distance from each), Ctrl+Shift+click one source for all. Ctrl+click an algorithm to change the "
                "picked shape (clone and heal swap, blur and fill swap). The eye shows the shapes of this scale on the picture to move and reshape (scroll: size, Shift+scroll: feather, "
                "Ctrl+scroll: opacity).\n\n"
                "WAVELET DECOMPOSE: the bar splits the picture into scales. Box 0 is the picture as it is, 1 to N are layers of detail from fine to coarse, and the lighter box after them is the "
                "residual (the broad colour and light left over). A shape acts on the scale you are on when you draw it - heal a blemish's colour on the residual and its texture on scale 1 or 2. "
                "Click a box to work on that scale (the dot). Drag the bottom arrow to set how many scales there are; drag the top arrow to merge the scales from there on into one layer. "
                "The line along the top of a box says the scale is visible at this size of picture; the orange line along the bottom says it has shapes. The buttons: display the wavelet "
                "scale you are on; paste/cut shapes between scales; display where the shapes act; switch the shapes off for a moment. Scales are counted in the pixels of the picture being "
                "made, so the small editing preview shows a wider area per scale than the export: check at 100%.\n\n"
                "PREVIEW SINGLE SCALE: a detail layer is mostly grey, so it is shown through levels (black point, middle, white point); the button beside them fits them to the layer.\n\n"
                "SHAPES: the blur type and radius, or the fill mode, colour and brightness, of the picked shape, and its opacity."
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
        self._cut_from = -1

        # ---- retouch tools
        body.addWidget(_section("retouch tools"))
        shapes = QHBoxLayout()
        shapes.setSpacing(THEME.space_sm)
        shapes.addWidget(QLabel("shapes:"))
        self._count = QLabel("0")
        shapes.addWidget(self._count)
        shapes.addStretch(1)
        self._edit = tool_button("mask-eye", "show and edit shapes on the current scale", checkable=True)
        self._edit.toggled.connect(self.edit_toggled.emit)
        shapes.addWidget(self._edit)
        self._draw: dict[str, QToolButton] = {}
        for kind in _SHAPES:
            b = tool_button(SHAPE_ICONS[kind], f"{_SHAPE_TIPS[kind]}\nctrl+click to add multiple")
            b.clicked.connect(lambda _=False, k=kind: self.draw_requested.emit(k, _ctrl_held()))
            shapes.addWidget(b)
            self._draw[kind] = b
        body.addLayout(shapes)

        algo = QHBoxLayout()
        algo.setSpacing(THEME.space_sm)
        algo.addWidget(QLabel("algorithms:"))
        algo.addStretch(1)
        self._algo: dict[str, QToolButton] = {}
        for a in (R.BLUR, R.FILL, R.CLONE, R.HEAL):
            b = tool_button(_ALGO_ICONS[a], _ALGO_TIPS[a], checkable=True)
            b.clicked.connect(lambda _=False, name=a: self._algorithm_clicked(name))
            algo.addWidget(b)
            self._algo[a] = b
        body.addLayout(algo)

        # ---- wavelet decompose
        body.addWidget(_section("wavelet decompose"))
        labels = QHBoxLayout()
        labels.setSpacing(THEME.space_md)
        self._lbl_scales, self._lbl_current, self._lbl_merge = QLabel(), QLabel(), QLabel()
        for text, label in (("scales:", self._lbl_scales), ("current:", self._lbl_current), ("merge from:", self._lbl_merge)):
            labels.addWidget(QLabel(text))
            labels.addWidget(label)
        labels.addStretch(1)
        body.addLayout(labels)

        self._bar = ScaleBar()
        self._bar.scale_selected.connect(lambda i: self.changed.emit({"curr_scale": i}, "", False, 0))
        self._bar.num_scales_changed.connect(self._num_scales)
        self._bar.merge_changed.connect(self._merge_from)
        body.addWidget(self._bar)

        tools = QHBoxLayout()
        tools.setSpacing(THEME.space_sm)
        self._view_scale = tool_button("mask-layers", "display wavelet scale", checkable=True)
        self._view_scale.toggled.connect(lambda on: self._view_toggled("scale", on))
        self._paste = tool_button("mask-paste", "paste cut shapes to current scale", checkable=True)
        self._paste.setEnabled(False)
        self._paste.clicked.connect(self._paste_scale)
        self._cut = tool_button("mask-cut", "cut shapes from current scale", checkable=True)
        self._cut.clicked.connect(self._cut_scale)
        self._show_mask = tool_button("mask-eye", "display masks", checkable=True)
        self._show_mask.toggled.connect(lambda on: self._view_toggled("mask", on))
        self._suppress = tool_button("mask-eye-off", "temporarily switch off shapes", checkable=True)
        self._suppress.toggled.connect(lambda on: self._view_toggled("suppress", on))
        tools.addWidget(self._view_scale)
        tools.addStretch(1)
        tools.addWidget(self._paste)
        tools.addWidget(self._cut)
        tools.addStretch(1)
        tools.addWidget(self._show_mask)
        tools.addWidget(self._suppress)
        body.addLayout(tools)

        # ---- preview single scale
        self._levels_box = QWidget()
        lv = QVBoxLayout(self._levels_box)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(THEME.space_sm)
        lv.addWidget(_section("preview single scale"))
        row = QHBoxLayout()
        self._levels = LevelsSlider()
        self._levels.value_changed.connect(self._levels_moved)
        row.addWidget(self._levels, 1)
        self._auto = tool_button("mask-levels", "auto levels", checkable=True)
        self._auto.clicked.connect(lambda: self.changed.emit({"preview_auto": True}, "", False, 0))
        row.addWidget(self._auto)
        lv.addLayout(row)
        body.addWidget(self._levels_box)

        # ---- shapes
        body.addWidget(_section("shapes"))
        self._picked_label = QLabel("shape selected: none")
        self._picked_label.setToolTip("click on a shape to select it,\nto unselect click on an empty space")
        body.addWidget(self._picked_label)

        self._blur_box = QWidget()
        bl = QVBoxLayout(self._blur_box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(THEME.space_sm)
        row = QHBoxLayout()
        row.addWidget(QLabel("blur type"))
        self._blur_type = QComboBox()
        self._blur_type.addItem("gaussian", R.GAUSSIAN)
        self._blur_type.addItem("bilateral", R.BILATERAL)
        self._blur_type.setToolTip("type for the blur algorithm")
        self._blur_type.activated.connect(self._blur_changed)
        row.addWidget(self._blur_type, 1)
        bl.addLayout(row)
        self._blur_radius = SliderRow("blur radius", min_value=0.1, max_value=200.0, reset_value=10.0, decimals=1, step=0.5, label_width=_LABEL_WIDTH)
        self._blur_radius.setToolTip("radius of the selected blur type, in px")
        self._blur_radius.value_changed.connect(self._blur_dragged)
        bl.addWidget(self._blur_radius)
        body.addWidget(self._blur_box)

        self._fill_box = QWidget()
        fl = QVBoxLayout(self._fill_box)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(THEME.space_sm)
        row = QHBoxLayout()
        row.addWidget(QLabel("fill mode"))
        self._fill_mode = QComboBox()
        self._fill_mode.addItem("erase", R.ERASE)
        self._fill_mode.addItem("color", R.COLOR)
        self._fill_mode.setToolTip("erase the detail or fills with chosen color")
        self._fill_mode.activated.connect(self._fill_changed)
        row.addWidget(self._fill_mode, 1)
        fl.addLayout(row)
        self._colour_row = QWidget()
        cr = QHBoxLayout(self._colour_row)
        cr.setContentsMargins(0, 0, 0, 0)
        cr.addWidget(QLabel("fill color:"))
        self._colour = QPushButton("")
        self._colour.setToolTip("select fill color")
        self._colour.clicked.connect(self._pick_colour)
        cr.addWidget(self._colour, 1)
        fl.addWidget(self._colour_row)
        self._fill_brightness = SliderRow("brightness", min_value=-1.0, max_value=1.0, reset_value=0.0, decimals=2, step=0.01, label_width=_LABEL_WIDTH)
        self._fill_brightness.setToolTip("adjusts color brightness to fine-tune it. works with erase as well")
        self._fill_brightness.value_changed.connect(self._fill_dragged)
        fl.addWidget(self._fill_brightness)
        body.addWidget(self._fill_box)

        self._opacity = SliderRow("mask opacity", min_value=0.05, max_value=1.0, reset_value=1.0, decimals=2, step=0.05, label_width=_LABEL_WIDTH)
        self._opacity.setToolTip("set the opacity on the selected shape (ctrl+scroll over the shape does the same)")
        self._opacity.value_changed.connect(lambda v: None if self._building else self.opacity_changed.emit(self._picked, v, True))
        self._opacity.setVisible(False)
        body.addWidget(self._opacity)
        self._opacity_timer = QTimer(self)
        self._opacity_timer.setSingleShot(True)
        self._opacity_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._opacity_timer.timeout.connect(lambda: self.opacity_changed.emit(self._picked, self._opacity.value(), False))
        self._opacity.value_changed.connect(lambda _v: None if self._building else self._opacity_timer.start())

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
        self._levels_box.setVisible(False)
        self._show_parts()

    # ------------------------------------------------------------ showing the photo's Retouch
    def set_settings(self, s: R.Settings, picked: R.FormSetting | None = None, opacity: float | None = None, first_visible: int = 0) -> None:
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
            self._bar.set_state(s.num_scales, s.curr_scale, s.merge_from_scale, shapes, first_visible)
            self._lbl_scales.setText(str(s.num_scales))
            self._lbl_current.setText(str(s.curr_scale))
            self._lbl_merge.setText(str(s.merge_from_scale))
            self._levels.set_values(s.preview_levels)
            self._auto.setChecked(s.preview_auto)
            blur = picked if picked is not None and picked.algorithm == R.BLUR else None
            fill = picked if picked is not None and picked.algorithm == R.FILL else None
            self._blur_type.setCurrentIndex(max(0, self._blur_type.findData(blur.blur_type if blur else s.blur_type)))
            self._blur_radius.set_value(blur.blur_radius if blur else s.blur_radius)
            self._fill_mode.setCurrentIndex(max(0, self._fill_mode.findData(fill.fill_mode if fill else s.fill_mode)))
            self._fill_brightness.set_value(fill.fill_brightness if fill else s.fill_brightness)
            self._shown_algo = algo
            self._set_colour_swatch(fill.fill_color if fill else s.fill_color)
            self._picked = picked.formid if picked is not None else 0
            self._picked_label.setText("shape selected: none" if picked is None else f"shape selected: #{picked.formid} ({picked.algorithm}, scale {'R' if picked.scale == s.num_scales + 1 else picked.scale})")
            self._opacity.setVisible(picked is not None)
            if picked is not None and opacity is not None:
                self._opacity.set_value(opacity)
            can_paste = self._cut_from >= 0 and any(f.scale == self._cut_from for f in s.forms)
            self._paste.setEnabled(can_paste)
            self._cut.setEnabled(any(f.scale == s.curr_scale for f in s.forms) or self._cut_from >= 0)
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
        self._colour_row.setVisible(self._fill_mode.currentData() == R.COLOR)

    def _set_colour_swatch(self, linear) -> None:
        c = QColor.fromRgbF(*(_srgb(v) for v in list(linear)[:3]))
        self._colour.setStyleSheet(f"background-color: {c.name()};")

    # ------------------------------------------------------------ the person's choices
    def _algorithm_clicked(self, name: str) -> None:
        if not self._building:
            self.algorithm_chosen.emit(name, _ctrl_held())
            if _shift_held():
                self.set_note(f"default tool changed to {name}")

    def _num_scales(self, n: int) -> None:
        if n != self._settings.num_scales:
            self.changed.emit({"num_scales": n}, f"Retouch: {n} wavelet scales", False, 0)

    def _merge_from(self, m: int) -> None:
        if m != self._settings.merge_from_scale:
            self.changed.emit({"merge_from_scale": m}, f"Retouch: merge from scale {m}", False, 0)

    def _view_toggled(self, name: str, on: bool) -> None:
        if on:
            for b, other in ((self._show_mask, "mask"), (self._suppress, "suppress"), (self._view_scale, "scale")):
                if other != name:
                    b.blockSignals(True)
                    b.setChecked(False)
                    b.blockSignals(False)
        self._levels_box.setVisible(name == "scale" and on)
        if name == "scale" and on and self._settings.num_scales == 0:
            self.set_note("Drag the bottom arrow of the bar to split the picture into wavelet scales; then click a box to look at that scale.")
        elif not on:
            self.set_note("")
        self.view_changed.emit(name if on else "")

    def _cut_scale(self) -> None:
        if self._cut_from >= 0:
            self._cut_from = -1
            self._cut.setChecked(False)
            self._paste.setEnabled(False)
            self.set_note("")
            return
        self._cut_from = self._settings.curr_scale
        self._cut.setChecked(True)
        self._paste.setEnabled(any(f.scale == self._cut_from for f in self._settings.forms))
        self.set_note(f"Shapes of scale {self._cut_from} picked up: click another scale, then paste.")

    def _paste_scale(self) -> None:
        if self._cut_from >= 0 and self._cut_from != self._settings.curr_scale:
            self.paste_requested.emit(self._cut_from, self._settings.curr_scale)
        self._cut_from = -1
        self._cut.setChecked(False)
        self._paste.setChecked(False)
        self._paste.setEnabled(False)
        self.set_note("")

    def _levels_moved(self, values: list) -> None:
        if not self._building:
            self._queue({"preview_levels": list(values), "preview_auto": False}, "")

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
        c = QColorDialog.getColor(start, self, "select fill color")
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
