"""Two small controls after NegPy's: a segmented choice (one row of buttons, one lit) for a few either-or choices, and ‹ › arrows that step a dropdown to its neighbour choice (wrapping
past the ends) without opening it."""

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QAbstractButton, QButtonGroup, QComboBox, QHBoxLayout, QLayout, QPushButton, QToolButton, QWidget


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
    """A row of buttons of which one is lit: the choices of a small either-or setting laid out side by side. It answers like the QComboBox it replaces (currentIndex, currentData,
    setCurrentIndex, findData, count, itemText, itemData, currentIndexChanged), and blockSignals() holds back currentIndexChanged."""

    currentIndexChanged = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: list[QPushButton] = []
        self._data: list = []
        self._index = -1

    def addItem(self, text: str, data=None, color: str | None = None, tip: str = "") -> None:
        button = QPushButton(text)
        button.setCheckable(True)
        button.setProperty("compact", True)
        button.setProperty("segment", True)
        if color:
            button.setIcon(_dot(color))
        if tip:
            button.setToolTip(tip)
        self._group.addButton(button, len(self._buttons))
        self.layout().addWidget(button, 1)
        self._buttons.append(button)
        self._data.append(data)
        button.clicked.connect(lambda _c=False, i=len(self._buttons) - 1: self.setCurrentIndex(i))
        if self._index < 0:
            self._set(0)

    def _set(self, index: int) -> None:
        self._index = index
        for i, button in enumerate(self._buttons):
            button.setChecked(i == index)

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


def _stepper_button(text: str, tip: str) -> QToolButton:
    button = QToolButton()
    button.setText(text)
    button.setToolTip(tip)
    button.setAutoRaise(True)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setFixedWidth(18)
    return button


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


def add_steppers(combo: QComboBox) -> bool:
    """Put ‹ and › either side of a dropdown: they step to the previous or next choice and wrap past the ends. False when the dropdown is not in a layout, is editable or has fewer
    than three choices (two choices are one click away already)."""
    if combo.isEditable() or combo.count() < 3 or combo.property("stepper") or combo.parentWidget() is None:
        return False
    holder = _layout_holding(combo, combo.parentWidget().layout())
    if holder is None:
        return False
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(0)
    previous = _stepper_button("‹", "Previous choice")
    following = _stepper_button("›", "Next choice")
    hidden = combo.isHidden()
    holder.replaceWidget(combo, box)
    row.addWidget(previous)
    row.addWidget(combo, 1)
    row.addWidget(following)
    combo.setVisible(not hidden)
    box.setVisible(not hidden)
    _Follow(combo, box)
    combo.setProperty("stepper", True)

    def step(delta: int) -> None:
        n = combo.count()
        if n:
            combo.setCurrentIndex((max(combo.currentIndex(), 0) + delta) % n)

    previous.clicked.connect(lambda _c=False: step(-1))
    following.clicked.connect(lambda _c=False: step(1))
    return True


def add_steppers_in(panel: QWidget) -> int:
    """add_steppers for every dropdown inside a panel (those added later are not seen: call it once the panel is built)."""
    return sum(1 for combo in panel.findChildren(QComboBox) if add_steppers(combo))
