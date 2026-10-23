from PyQt6.QtCore import QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from ...features.masks import blend as B
from ...features.masks import model as M
from ...theme.tokens import THEME
from . import panel_icons
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200
_LABEL_WIDTH = 76
SHAPE_ICONS = {M.CIRCLE: "mask-circle", M.ELLIPSE: "mask-ellipse", M.PATH: "mask-path", M.BRUSH: "mask-brush", M.GRADIENT: "mask-gradient", M.GROUP: "mask-group"}
_HINTS = {
    M.CIRCLE: "Draw a circle: click where it goes. Scroll sets its size, Shift+scroll its feather, Ctrl+scroll its opacity. Ctrl+click keeps drawing circles.",
    M.ELLIPSE: "Draw an ellipse: click where it goes. Scroll sets its size, Shift+scroll its feather, Ctrl+Shift+scroll turns it, Ctrl+scroll sets its opacity. Ctrl+click keeps drawing.",
    M.PATH: "Draw a path: click to put smooth nodes, Shift+click (or Ctrl+click) for sharp ones, right-click (or Enter) to finish it. Shift+scroll sets its feather, Ctrl+scroll its opacity.",
    M.BRUSH: "Draw a brush stroke: press and drag; let go to finish. Scroll sets the size, Shift+scroll the hardness, Ctrl+scroll the density.",
    M.GRADIENT: "Draw a gradient: click and drag to set its line and direction. Scroll bends it, Shift+scroll sets how fast it ramps, Ctrl+scroll sets its opacity.",
}


def shape_icon(kind: str, size: int = 16) -> QIcon:
    return QIcon(panel_icons.pixmap(SHAPE_ICONS.get(kind), size, THEME.text_primary))


def tool_button(icon_name: str, tip: str, checkable: bool = False) -> QToolButton:
    b = QToolButton()
    b.setIcon(QIcon(panel_icons.pixmap(icon_name, 16, THEME.text_primary)))
    b.setIconSize(QSize(16, 16))
    b.setToolTip(tip)
    b.setCheckable(checkable)
    b.setAutoRaise(True)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return b


class BlendBox(QWidget):
    """The Mask box at the foot of a module (darktable's blending section): how the module's result is mixed back into the picture it was given - not at all (Off), at an Opacity
    everywhere (Uniformly) or only where a drawn mask is (Drawn mask), with the mask's Invert, and a Refine section (blur, feather, contrast, brightness). The shape buttons draw a new
    shape for this module; the eye shows the mask on the picture; the pencil edits the shapes where they lie on the picture."""

    changed = pyqtSignal(object)          # a Blend, when a choice is made or a slider settles
    preview_requested = pyqtSignal(object)  # a Blend, while a slider is being dragged
    draw_requested = pyqtSignal(str)      # a shape kind to draw for this module
    edit_toggled = pyqtSignal(bool)       # edit the module's mask on the picture
    show_toggled = pyqtSignal(bool)       # show the module's mask on the picture

    def __init__(self, key: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.key = key
        self._forms: list[tuple[int, str, str]] = []
        self._building = True
        root = QVBoxLayout(self)
        root.setContentsMargins(0, THEME.space_sm, 0, 0)
        root.setSpacing(THEME.space_sm)

        head = QHBoxLayout()
        head.setSpacing(THEME.space_sm)
        label = QLabel("Mask")
        label.setFixedWidth(_LABEL_WIDTH)
        label.setToolTip("Blend this module's result into the picture: everywhere, or only where a mask you draw is, as in darktable.")
        head.addWidget(label)
        self._mode = QComboBox()
        for mode in B.MODES:
            self._mode.addItem(B.MODE_LABELS[mode], mode)
        self._mode.setToolTip("Off: the module acts on everything.   Uniformly: everywhere, at the opacity below.   Drawn mask: only where the mask is.")
        self._mode.activated.connect(self._mode_picked)
        head.addWidget(self._mode, 1)
        root.addLayout(head)

        self._detail = QWidget()
        detail = QVBoxLayout(self._detail)
        detail.setContentsMargins(0, 0, 0, 0)
        detail.setSpacing(THEME.space_sm)
        self._opacity = SliderRow("Opacity", min_value=0.0, max_value=100.0, reset_value=100.0, decimals=0, step=1.0, label_width=_LABEL_WIDTH)
        self._opacity.setToolTip("How strongly the module shows through (the drawn mask is scaled by this)")
        self._opacity.value_changed.connect(self._slider_moved)
        detail.addWidget(self._opacity)

        self._drawn = QWidget()
        drawn = QVBoxLayout(self._drawn)
        drawn.setContentsMargins(0, 0, 0, 0)
        drawn.setSpacing(THEME.space_sm)
        pick = QHBoxLayout()
        pick.setSpacing(THEME.space_sm)
        which = QLabel("Shape")
        which.setFixedWidth(_LABEL_WIDTH)
        pick.addWidget(which)
        self._mask = QComboBox()
        self._mask.setToolTip("The shape or group of shapes this module is blended through. They are listed in the Masks section on the left.")
        self._mask.activated.connect(self._mask_picked)
        pick.addWidget(self._mask, 1)
        drawn.addLayout(pick)

        tools = QHBoxLayout()
        tools.setSpacing(2)
        self._shape_buttons: dict[str, QToolButton] = {}
        for kind in M.SHAPES:
            b = tool_button(SHAPE_ICONS[kind], _HINTS[kind])
            b.clicked.connect(lambda _c=False, k=kind: self.draw_requested.emit(k))
            self._shape_buttons[kind] = b
            tools.addWidget(b)
        tools.addStretch(1)
        self._edit = tool_button("mask-edit", "Show and edit this module's mask on the picture: drag a shape to move it, drag its nodes, scroll to resize.", checkable=True)
        self._edit.toggled.connect(self.edit_toggled)
        self._show = tool_button("mask-eye", "Show the mask on the picture (yellow where the module acts)", checkable=True)
        self._show.toggled.connect(self.show_toggled)
        tools.addWidget(self._edit)
        tools.addWidget(self._show)
        drawn.addLayout(tools)

        self._invert = QCheckBox("Invert the mask")
        self._invert.setToolTip("Swap inside and outside: the module acts everywhere except where the mask is (darktable's mask polarity)")
        self._invert.toggled.connect(self._changed_now)
        drawn.addWidget(self._invert)

        self._refine_toggle = QToolButton()
        self._refine_toggle.setText("Refine the mask")
        self._refine_toggle.setCheckable(True)
        self._refine_toggle.setAutoRaise(True)
        self._refine_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self._refine_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._refine_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        drawn.addWidget(self._refine_toggle)
        self._refine = QWidget()
        refine = QVBoxLayout(self._refine)
        refine.setContentsMargins(0, 0, 0, 0)
        refine.setSpacing(THEME.space_sm)
        self._sliders: dict[str, SliderRow] = {}
        for name, text, tip, low, high, step in (
            ("blur", "Blur", "Soften the mask's edge: a Gaussian blur, in pixels of the 1600 pixel preview (the export looks the same)", 0.0, 100.0, 0.5),
            ("feather", "Feather", "Pull the mask's edge to the picture's own edges with a guided filter of this radius", 0.0, 100.0, 0.5),
            ("contrast", "Contrast", "Steepen (or flatten) the mask's own values, the S-curve of darktable's mask contrast", -1.0, 1.0, 0.01),
            ("brightness", "Brightness", "Grow (or shrink) the mask: shift the mask's values up or down", -1.0, 1.0, 0.01),
        ):
            row = SliderRow(text, min_value=low, max_value=high, reset_value=0.0, decimals=2 if high <= 1.0 else 1, step=step, label_width=_LABEL_WIDTH)
            row.setToolTip(tip)
            row.value_changed.connect(self._slider_moved)
            self._sliders[name] = row
            refine.addWidget(row)
        self._refine.setVisible(False)
        self._refine_toggle.toggled.connect(self._refine_shown)
        drawn.addWidget(self._refine)
        detail.addWidget(self._drawn)
        root.addWidget(self._detail)

        self._pending: B.Blend | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._preview_timer.timeout.connect(self._flush_preview)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._settle_timer.timeout.connect(lambda: self.changed.emit(self.blend()))
        self._building = False
        self._show_parts()

    # ------------------------------------------------------------ reading and setting
    def blend(self) -> B.Blend:
        return B.Blend(self._mode.currentData() or B.OFF, int(self._mask.currentData() or 0), self._opacity.value(), self._invert.isChecked(), self._sliders["blur"].value(),
                       self._sliders["feather"].value(), self._sliders["brightness"].value(), self._sliders["contrast"].value())

    def set_forms(self, forms: list[tuple[int, str, str]]) -> None:
        """The shapes and groups there are to choose from: (id, name, kind). The choice stays on the same id when it is still there."""
        self._forms = list(forms)
        current = int(self._mask.currentData() or 0)
        self._mask.blockSignals(True)
        self._mask.clear()
        self._mask.addItem("(no mask chosen: everywhere)", 0)
        for form_id, name, kind in self._forms:
            self._mask.addItem(shape_icon(kind), name, form_id)
        self._mask.setCurrentIndex(max(0, self._mask.findData(current)))
        self._mask.blockSignals(False)

    def set_blend(self, blend: B.Blend) -> None:
        """Show this blend without announcing it (the photo changed, or an undo)."""
        self._settle_timer.stop()
        self._pending = None
        for w in (self._mode, self._mask, self._invert, self._opacity, *self._sliders.values()):
            w.blockSignals(True)
        self._mode.setCurrentIndex(max(0, self._mode.findData(blend.mode)))
        self._mask.setCurrentIndex(max(0, self._mask.findData(blend.mask_id)))
        self._invert.setChecked(blend.invert)
        self._opacity.set_value(blend.opacity)
        for name in self._sliders:
            self._sliders[name].set_value(getattr(blend, name))
        for w in (self._mode, self._mask, self._invert, self._opacity, *self._sliders.values()):
            w.blockSignals(False)
        self._show_parts()

    def set_editing(self, editing: bool, showing: bool) -> None:
        for button, on in ((self._edit, editing), (self._show, showing)):
            button.blockSignals(True)
            button.setChecked(on)
            button.blockSignals(False)
        self._show.setIcon(QIcon(panel_icons.pixmap("mask-eye" if showing else "mask-eye", 16, THEME.text_primary)))

    def _show_parts(self) -> None:
        mode = self._mode.currentData()
        self._detail.setVisible(mode in (B.UNIFORM, B.DRAWN))
        self._drawn.setVisible(mode == B.DRAWN)

    # ------------------------------------------------------------ the person's choices
    def _mode_picked(self, _index: int) -> None:
        self._show_parts()
        self._changed_now()

    def _mask_picked(self, _index: int) -> None:
        self._changed_now()

    def _refine_shown(self, on: bool) -> None:
        self._refine.setVisible(on)
        self._refine_toggle.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)

    def _changed_now(self, *_args) -> None:
        if self._building:
            return
        self._settle_timer.stop()
        self._pending = None
        self.changed.emit(self.blend())

    def _slider_moved(self, _value=None) -> None:
        blend = self.blend()
        if self._preview_timer.isActive():
            self._pending = blend
        else:
            self.preview_requested.emit(blend)
            self._preview_timer.start()
        self._settle_timer.start()

    def _flush_preview(self) -> None:
        if self._pending is not None:
            blend, self._pending = self._pending, None
            self.preview_requested.emit(blend)
            self._preview_timer.start()
