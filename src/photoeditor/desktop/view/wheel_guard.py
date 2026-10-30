"""The mouse wheel does nothing to a slider, a number box or a drop-down until it has been clicked.

Scrolling a long panel with the wheel used to change every slider the pointer passed over on the way. Now a control that has not been clicked ignores the wheel and hands it to what is
behind it (the panel scrolls); once it has been clicked it takes the wheel as before. A slider lets go of that again when the pointer leaves it, so the next time the panel is scrolled
past it nothing is changed. Number boxes keep their focus (a number may be being typed), and scroll bars are left alone: the wheel always moves a scroll bar.

A control is not given the focus except by a click (never by tabbing or by the window handing it to its first control when it opens), so it cannot be waiting with the focus for a wheel to pass. A
drop-down lets go of the focus when the pointer leaves it, as a slider does, so one that was used a while ago is guarded again. A custom control that takes the wheel itself marks
itself with the property "wheelGuard".

One filter on the application does it for every control, including those in dialogs, so no control has to be made to remember."""

from PyQt6.QtGui import QWheelEvent
from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QScrollBar, QWidget


def guarded(widget) -> QWidget | None:
    """The control the wheel would act on when it lands on `widget`: a slider, a number box or a drop-down (a number box's or an editable drop-down's own text field counts as the box). None for anything else."""
    if isinstance(widget, QLineEdit) and isinstance(widget.parentWidget(), (QAbstractSpinBox, QComboBox)):
        widget = widget.parentWidget()
    if isinstance(widget, QScrollBar):
        return None
    if isinstance(widget, (QAbstractSlider, QAbstractSpinBox, QComboBox)) or (isinstance(widget, QWidget) and widget.property("wheelGuard")):
        return widget
    return None


def lets_go_on_leave(widget) -> bool:
    """Whether the control gives up its focus when the pointer leaves it: a slider (not while it is being dragged), a drop-down (not while its list is open) or a custom wheel control. A
    number box keeps it, since a number may be being typed."""
    if isinstance(widget, QScrollBar) or isinstance(widget, QAbstractSpinBox):
        return False
    if isinstance(widget, QAbstractSlider):
        return not widget.isSliderDown()
    if isinstance(widget, QComboBox):
        return not widget.view().isVisible()
    return bool(widget.property("wheelGuard"))


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
            control = guarded(obj)
            if control is obj and obj.hasFocus() and lets_go_on_leave(obj):
                obj.clearFocus()
        elif kind in (QEvent.Type.Polish, QEvent.Type.Show):
            control = guarded(obj)
            if control is obj and not isinstance(obj, QScrollBar) and obj.focusPolicy() != Qt.FocusPolicy.ClickFocus:
                obj.setFocusPolicy(Qt.FocusPolicy.ClickFocus)       # focus by a click only: never by tabbing, and never handed over by the window
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
        for widget in app.allWidgets():      # (controls made before the guard was put on)
            if guarded(widget) is widget and not isinstance(widget, QScrollBar):
                widget.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
    return _guard
