"""The mouse wheel does nothing to a slider, a number box or a drop-down until it has been clicked.

Scrolling a long panel with the wheel used to change every slider the pointer passed over on the way. Now a control that has not been clicked ignores the wheel and hands it to what is
behind it (the panel scrolls); once it has been clicked it takes the wheel as before. A slider lets go of that again when the pointer leaves it, so the next time the panel is scrolled
past it nothing is changed. Number boxes keep their focus (a number may be being typed), and scroll bars are left alone: the wheel always moves a scroll bar.

One filter on the application does it for every control, including those in dialogs, so no control has to be made to remember."""

from PyQt6.QtGui import QWheelEvent
from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QScrollBar, QWidget


def guarded(widget) -> QWidget | None:
    """The control the wheel would act on when it lands on `widget`: a slider, a number box or a drop-down (a number box's or an editable drop-down's own text field counts as the box). None for anything else."""
    if isinstance(widget, QLineEdit) and isinstance(widget.parentWidget(), (QAbstractSpinBox, QComboBox)):
        widget = widget.parentWidget()
    if isinstance(widget, QScrollBar):
        return None
    return widget if isinstance(widget, (QAbstractSlider, QAbstractSpinBox, QComboBox)) else None


def scroll_viewport(widget) -> QWidget | None:
    """The viewport of the scrolling panel `widget` sits in, if it is in one."""
    parent = widget.parentWidget()
    while parent is not None:
        area = parent.parentWidget()
        if isinstance(area, QAbstractScrollArea) and area.viewport() is parent:
            return parent
        parent = parent.parentWidget()
    return None


class WheelGuard(QObject):
    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.Wheel:
            control = guarded(obj)
            if control is not None and not control.hasFocus():
                viewport = scroll_viewport(control)
                if viewport is None:
                    event.ignore()
                    return True   # handled as far as this control goes, and not accepted: the event goes on to the widget behind it
                # the panel behind it gets the wheel itself (the same turn, where the pointer is), and the control is told it was dealt with, so it is not scrolled twice
                pos = viewport.mapFromGlobal(event.globalPosition().toPoint())
                forwarded = QWheelEvent(pos.toPointF(), event.globalPosition(), event.pixelDelta(), event.angleDelta(), event.buttons(), event.modifiers(), event.phase(), event.inverted())
                QApplication.sendEvent(viewport, forwarded)
                event.accept()
                return True
        elif kind == QEvent.Type.Leave:
            if isinstance(obj, QAbstractSlider) and not isinstance(obj, QScrollBar) and obj.hasFocus() and not obj.isSliderDown():
                obj.clearFocus()
        return False


_guard: WheelGuard | None = None


def install() -> WheelGuard | None:
    """Put the guard on the running application (once, however many windows ask)."""
    global _guard
    app = QApplication.instance()
    if app is None:
        return None
    if _guard is None or _guard.parent() is not app:
        _guard = WheelGuard(app)
        app.installEventFilter(_guard)
    return _guard
