"""Two small controls after NegPy's: a segmented choice (one row of buttons, one lit) for a few either-or choices, and ‹ › arrows that step a dropdown to its neighbour choice (wrapping
past the ends) without opening it."""

from PyQt6.QtCore import QEasingCurve, QEvent, QObject, QRectF, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLayout, QPushButton, QToolButton, QWidget

from ...theme.tokens import THEME
from .module_style import STYLE


def _dot(color: str, size: int = 10) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(0, 0, size, size)
    painter.end()
    return QIcon(pixmap)


class SegmentedControl(QWidget):
    """One track holding a few either-or choices, with a single highlight that slides from the old choice to the new one (NegPy's segmented choice). It answers like the QComboBox it replaces
    (currentIndex, currentData, setCurrentIndex, findData, count, itemText, itemData, currentIndexChanged), and blockSignals() holds back currentIndexChanged."""

    currentIndexChanged = pyqtSignal(int)
    SLIDE_MS = 170

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(0)
        self._buttons: list[QPushButton] = []
        self._data: list = []
        self._index = -1
        self._from = QRectF()        # the highlight's place when the slide began and where it ends: the highlight is drawn between the two
        self._to = QRectF()
        self._t = 1.0
        self._slide = QVariantAnimation(self)
        self._slide.setDuration(self.SLIDE_MS)
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide.setStartValue(0.0)
        self._slide.setEndValue(1.0)
        self._slide.valueChanged.connect(self._on_slide)
        self.setObjectName("segmented")
        self._restyle()
        STYLE.changed.connect(self._restyle)

    def _restyle(self) -> None:
        """The segments are flat text over the track: only the track and the highlight are drawn, by this widget."""
        self.setStyleSheet(f"#segmented QPushButton {{ background: transparent; border: none; padding: 3px 8px; color: {THEME.text_secondary}; }}"
                           f"#segmented QPushButton:checked {{ color: {THEME.on_accent}; font-weight: bold; }}"
                           f"#segmented QPushButton:hover:!checked {{ color: {THEME.text_primary}; }}")

    def addItem(self, text: str, data=None, color: str | None = None, tip: str = "") -> None:
        button = QPushButton(text)
        button.setCheckable(True)
        button.setFlat(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if color:
            button.setIcon(_dot(color))
        if tip:
            button.setToolTip(tip)
        self.layout().addWidget(button, 1)
        self._buttons.append(button)
        self._data.append(data)
        button.clicked.connect(lambda _c=False, i=len(self._buttons) - 1: self.setCurrentIndex(i))
        if self._index < 0:
            self._set(0, animate=False)

    def _set(self, index: int, animate: bool = True) -> None:
        self._index = index
        for i, button in enumerate(self._buttons):
            button.setChecked(i == index)
        self._move_highlight(animate)

    def _target(self) -> QRectF:
        if not 0 <= self._index < len(self._buttons):
            return QRectF()
        return QRectF(self._buttons[self._index].geometry())

    def _current(self) -> QRectF:
        """Where the highlight is drawn now: between where it started and where it is going."""
        a, b, t = self._from, self._to, self._t
        if a.isEmpty() or t >= 1.0:
            return b
        return QRectF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t, a.width() + (b.width() - a.width()) * t, a.height() + (b.height() - a.height()) * t)

    def _move_highlight(self, animate: bool) -> None:
        self._slide.stop()
        self._from = self._current() if not self._to.isEmpty() else self._target()
        self._to = self._target()
        self._t = 1.0
        if animate and self.isVisible() and not self._from.isEmpty() and self._from != self._to:
            self._t = 0.0
            self._slide.start()
        self.update()

    def _on_slide(self, value) -> None:
        self._t = float(value)
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._slide.stop()
        self._t = 1.0
        self._to = self._target()
        self._from = self._to
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, lambda: self._move_highlight(False))      # (the segments have their places once the row is shown)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = min(track.height() / 2.0, 12.0)
        painter.setPen(QPen(QColor(THEME.border_color), 1))
        painter.setBrush(QColor(THEME.bg_input))
        painter.drawRoundedRect(track, radius, radius)
        thumb = self._current()
        if not thumb.isEmpty():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(THEME.accent_primary))
            painter.drawRoundedRect(thumb, max(radius - 2, 2), max(radius - 2, 2))

    def setCurrentIndex(self, index: int) -> None:
        if not 0 <= index < len(self._buttons):
            return
        changed = index != self._index
        self._set(index)
        if changed:
            self.currentIndexChanged.emit(index)

    def currentIndex(self) -> int:
        return self._index

    def currentData(self):
        return self._data[self._index] if 0 <= self._index < len(self._data) else None

    def findData(self, data) -> int:
        return self._data.index(data) if data in self._data else -1

    def count(self) -> int:
        return len(self._buttons)

    def itemText(self, index: int) -> str:
        return self._buttons[index].text()

    def itemData(self, index: int):
        return self._data[index]


class _ArrowButton(QToolButton):
    """A small bordered button with a chevron drawn in its exact middle (a text arrow sits high and small in a font): `direction` -1 points left, +1 right."""

    def __init__(self, direction: int, tip: str):
        super().__init__()
        self._direction = direction
        self.setToolTip(tip)
        self.setAutoRaise(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(26, 24)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)       # (the button's box, from the frame's stylesheet)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        colour = QColor(THEME.accent_hover if self.underMouse() else THEME.text_primary)
        painter.setPen(QPen(colour, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        cx, cy, half, reach = self.width() / 2.0, self.height() / 2.0, 5.0, 3.0
        d = self._direction
        path = QPainterPath()
        path.moveTo(cx - d * reach, cy - half)
        path.lineTo(cx + d * reach, cy)
        path.lineTo(cx - d * reach, cy + half)
        painter.drawPath(path)


def _stepper_button(direction: int, tip: str) -> QToolButton:
    return _ArrowButton(direction, tip)


def inset_edge() -> str:
    """The edge of the field inside a dropdown's dark frame, as NegPy draws a field's: a faint white wash (its border_primary, 6% white) on the dark input colour, worked out as a plain
    colour so it holds on every theme."""
    base = QColor(THEME.bg_input)
    return QColor(*(round(c * 0.94 + 255 * 0.06) for c in (base.red(), base.green(), base.blue()))).name()


def _restyle_steppers(box: QWidget) -> None:
    """The dropdown (and its two arrows, when it has them) sit in one rounded, dark, bordered frame; each arrow is a small raised button of its own and the dropdown inside is a field set
    into the frame with a faint edge of its own (NegPy's field edge)."""
    edge = inset_edge()
    box.setStyleSheet(
        f"#stepcombo {{ background: {THEME.bg_input}; border: 1px solid {THEME.border_color}; border-radius: 7px; }}"
        f"#stepcombo QComboBox {{ background: {THEME.bg_input}; border: 1px solid {edge}; border-radius: 4px; padding-left: 6px; }}"
        f"#stepcombo QComboBox:hover {{ border-color: {THEME.bevel_light}; }}"
        f"#stepcombo QComboBox:focus {{ border: 1px solid {THEME.accent_primary}; }}"
        f"#stepcombo QToolButton {{ background: {THEME.bg_button}; border: 1px solid {THEME.border_color}; border-radius: 5px; color: {THEME.text_primary}; font-weight: bold; padding: 0px; }}"
        f"#stepcombo QToolButton:hover {{ background: {THEME.bg_hover}; border-color: {THEME.accent_primary}; }}"
        f"#stepcombo QToolButton:pressed {{ background: {THEME.bg_pressed}; }}")


def _layout_holding(widget: QWidget, layout: QLayout | None) -> QLayout | None:
    """The layout (at any depth below `layout`) that holds `widget` directly."""
    if layout is None:
        return None
    if layout.indexOf(widget) >= 0:
        return layout
    for i in range(layout.count()):
        child = layout.itemAt(i).layout()
        if child is not None:
            found = _layout_holding(widget, child)
            if found is not None:
                return found
    return None


class _Follow(QObject):
    """Shows and hides the box round a dropdown with the dropdown (a panel hides the choices that do not belong to the mode it is in)."""

    def __init__(self, combo: QComboBox, box: QWidget):
        super().__init__(box)
        self._box = box
        combo.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.HideToParent:
            self._box.setVisible(False)
        elif event.type() == QEvent.Type.ShowToParent:
            self._box.setVisible(True)
        return False


def _framed(combo: QComboBox, arrows: bool) -> bool:
    """Set a dropdown in the dark frame, with ‹ and › either side of it when `arrows`. False when it is not in a layout."""
    if combo.parentWidget() is None:
        return False
    holder = _layout_holding(combo, combo.parentWidget().layout())
    if holder is None:
        return False
    box = QWidget()
    box.setObjectName("stepcombo")
    box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    row = QHBoxLayout(box)
    row.setContentsMargins(3, 3, 3, 3)
    row.setSpacing(3)
    _restyle_steppers(box)
    STYLE.changed.connect(lambda box=box: _restyle_steppers(box))
    hidden = combo.isHidden()
    holder.replaceWidget(combo, box)
    previous = following = None
    if arrows:
        previous = _stepper_button(-1, "Previous choice")
        following = _stepper_button(1, "Next choice")
        row.addWidget(previous)
    row.addWidget(combo, 1)
    if arrows:
        row.addWidget(following)
    combo.setVisible(not hidden)
    box.setVisible(not hidden)
    _Follow(combo, box)
    combo.setProperty("framed", True)
    if not arrows:
        return True
    combo.setProperty("stepper", True)

    def step(delta: int) -> None:
        n = combo.count()
        if n:
            combo.setCurrentIndex((max(combo.currentIndex(), 0) + delta) % n)

    previous.clicked.connect(lambda _c=False: step(-1))
    following.clicked.connect(lambda _c=False: step(1))
    return True


def add_steppers(combo: QComboBox) -> bool:
    """Put ‹ and › either side of a dropdown: they step to the previous or next choice and wrap past the ends. False when the dropdown is not in a layout, is editable or has fewer
    than three choices (two choices are one click away already)."""
    if combo.isEditable() or combo.count() < 3 or combo.property("framed"):
        return False
    return _framed(combo, True)


def add_frame(combo: QComboBox) -> bool:
    """A dropdown with no arrows (one with fewer than three choices, or whose choices come later) in the same dark frame as the rest, so every dropdown reads alike."""
    if combo.isEditable() or combo.property("framed"):
        return False
    return _framed(combo, False)


def add_steppers_in(panel: QWidget) -> int:
    """add_steppers for every dropdown inside a panel, and the dark frame round the rest (those added later are not seen: call it once the panel is built). Returns how many got arrows."""
    arrows = 0
    for combo in panel.findChildren(QComboBox):
        if add_steppers(combo):
            arrows += 1
        else:
            add_frame(combo)
    return arrows
