"""Debug mode: a runtime UI-annotation overlay for prototyping layout/sizing/
text tweaks by hand, then handing the resulting log back as a change spec -
not a live layout editor. Qt's layout managers reassert every managed
widget's geometry on the next relayout, so a move or resize made here can't
persist against them; a drag instead shows a live preview outline and logs
the *intended* delta for a human (or Claude) to turn into a real code
change. A double-click text edit is applied for real, since renaming a
label doesn't fight the layout the way moving or resizing it would.
"""

from datetime import datetime

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PyQt6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLineEdit, QPushButton, QScrollBar, QSplitterHandle,
    QTextEdit, QVBoxLayout, QWidget,
)

# Structural Qt chrome, not "content" - these need their own native drag
# behavior to keep working even while Debug mode is on (a splitter that
# stops resizing because Debug ate its drag is a regression, not a feature).
_NATIVE_DRAG_TYPES = (QSplitterHandle, QScrollBar)

_HANDLE_SIZE = 8
_EDGE_MARGIN = 10
_HIGHLIGHT_COLOR = "#39ff6a"
_MOVE_THRESHOLD = 2  # px of drag before a press counts as a move/resize, not a click

_CURSOR_BY_EDGE = {
    "n": Qt.CursorShape.SizeVerCursor,
    "s": Qt.CursorShape.SizeVerCursor,
    "e": Qt.CursorShape.SizeHorCursor,
    "w": Qt.CursorShape.SizeHorCursor,
    "ne": Qt.CursorShape.SizeBDiagCursor,
    "sw": Qt.CursorShape.SizeBDiagCursor,
    "nw": Qt.CursorShape.SizeFDiagCursor,
    "se": Qt.CursorShape.SizeFDiagCursor,
}


def describe_widget(widget: QWidget) -> str:
    """A human-readable identity for the log: class name, objectName if the
    widget has one, and a snippet of its text if it has that too - enough
    to recognize which widget an entry is about without a live picker."""
    label = type(widget).__name__
    name = widget.objectName()
    if name:
        label += f"#{name}"
    text_getter = getattr(widget, "text", None)
    if callable(text_getter):
        try:
            value = text_getter()
        except Exception:
            value = ""
        if value:
            snippet = value if len(value) <= 24 else value[:21] + "..."
            label += f' "{snippet}"'
    return label


def edge_at(local_pos: QPoint, size, margin: int = _EDGE_MARGIN) -> str | None:
    """Which edge/corner (n/s/e/w/ne/nw/se/sw) `local_pos` is near, or None
    for the interior - the same margin-based test WindowFrame uses for its
    own window-edge resize grip, just scoped to one widget's rect."""
    x, y, w, h = local_pos.x(), local_pos.y(), size.width(), size.height()
    near_left, near_right = x <= margin, x >= w - margin
    near_top, near_bottom = y <= margin, y >= h - margin
    if near_top and near_left:
        return "nw"
    if near_top and near_right:
        return "ne"
    if near_bottom and near_left:
        return "sw"
    if near_bottom and near_right:
        return "se"
    if near_top:
        return "n"
    if near_bottom:
        return "s"
    if near_left:
        return "w"
    if near_right:
        return "e"
    return None


def _apply_edge_delta(rect: QRect, edge: str, delta: QPoint) -> None:
    if "n" in edge:
        rect.setTop(rect.top() + delta.y())
    if "s" in edge:
        rect.setBottom(rect.bottom() + delta.y())
    if "w" in edge:
        rect.setLeft(rect.left() + delta.x())
    if "e" in edge:
        rect.setRight(rect.right() + delta.x())


class _SelectionOverlay(QWidget):
    """Purely decorative - a dashed-look outline plus 8 square handles drawn
    over whatever widget is currently hovered or being dragged. Never
    receives mouse events itself; DebugController does all the hit-testing,
    using real widgets' own events instead of this overlay's geometry."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        color = QColor(_HIGHLIGHT_COLOR)

        painter.setPen(color)
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        w, h = self.width(), self.height()
        for hx, hy in ((0, 0), (w // 2, 0), (w, 0), (0, h // 2), (w, h // 2), (0, h), (w // 2, h), (w, h)):
            painter.drawRect(hx - _HANDLE_SIZE // 2, hy - _HANDLE_SIZE // 2, _HANDLE_SIZE, _HANDLE_SIZE)
        painter.end()


class DebugLogWindow(QDialog):
    """A small, non-modal running log of every move/resize/rename made while
    Debug mode is on. Copy All puts the whole thing on the clipboard to
    hand back as a change spec."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Debug Log")
        self.setModal(False)
        self.resize(480, 320)

        layout = QVBoxLayout(self)
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFontFamily("Consolas")
        layout.addWidget(self._text, 1)

        buttons = QHBoxLayout()
        copy_btn = QPushButton("Copy All")
        copy_btn.clicked.connect(self._copy_all)
        buttons.addWidget(copy_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._text.clear)
        buttons.addWidget(clear_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def append(self, line: str) -> None:
        self._text.append(line)

    def _copy_all(self) -> None:
        QApplication.clipboard().setText(self._text.toPlainText())


class DebugController(QObject):
    """Installed app-wide via installEventFilter (see AppWindow). While
    enabled, it intercepts mouse input everywhere except the log window
    itself:
    - drag a widget's body: previews a move, logs the requested (dx, dy)
    - drag from a widget's edge/corner: previews a resize, logs the
      requested old-size -> new-size
    - double-click a widget with text (a label, a button): renames it for
      real and logs the old/new text
    Neither a move nor a resize is actually kept - the active layout would
    just put the widget back on its next pass - the log is the point."""

    def __init__(self, window: QWidget, parent: QObject | None = None):
        super().__init__(parent)
        self._window = window
        self._enabled = False
        self.log_window = DebugLogWindow(window)
        self._overlay = _SelectionOverlay(window)

        self._drag_widget: QWidget | None = None
        self._drag_mode: str | None = None  # "move" or an edge string
        self._press_global: QPoint | None = None
        self._press_geom: QRect | None = None

        self._edit_box: QLineEdit | None = None
        self._edit_target: QWidget | None = None

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if enabled:
            self.log_window.show()
            self.log_window.raise_()
            self._log(
                "Debug mode on - drag a widget's body to preview a move, "
                "drag from its edge/corner to preview a resize, "
                "double-click a label or button to rename it."
            )
        else:
            self._cancel_drag()
            self._cancel_edit()
            self._log("Debug mode off.")

    def is_enabled(self) -> bool:
        return self._enabled

    # ---- QObject event filter protocol (installed on QApplication) ----
    def eventFilter(self, watched, event) -> bool:
        if not self._enabled or not isinstance(watched, QWidget):
            return False
        if self._belongs_to_log_window(watched):
            return False
        if isinstance(watched, _NATIVE_DRAG_TYPES):
            return False

        event_type = event.type()
        if event_type == QEvent.Type.MouseButtonDblClick:
            return self._on_double_click(watched, event)
        if event_type == QEvent.Type.MouseButtonPress:
            return self._on_press(watched, event)
        if event_type == QEvent.Type.MouseMove:
            return self._on_move(watched, event)
        if event_type == QEvent.Type.MouseButtonRelease:
            return self._on_release(watched, event)
        if event_type == QEvent.Type.Enter:
            self._show_highlight(watched)
        elif event_type == QEvent.Type.Leave and self._drag_widget is None:
            self._overlay.hide()
        return False

    def _belongs_to_log_window(self, watched: QWidget) -> bool:
        widget = watched
        while isinstance(widget, QWidget):
            if widget is self.log_window:
                return True
            widget = widget.parentWidget()
        return False

    # ---- highlight on hover ----
    def _show_highlight(self, widget: QWidget) -> None:
        if widget is self._overlay or widget is self._window:
            return
        rect = self._geometry_in_root(widget)
        if rect is None:
            return
        self._overlay.setGeometry(rect)
        self._overlay.raise_()
        self._overlay.show()

    def _geometry_in_root(self, widget: QWidget) -> QRect | None:
        if not widget.isVisible():
            return None
        top_left = widget.mapTo(self._window, QPoint(0, 0))
        return QRect(top_left, widget.size())

    # ---- press / move / release: move or resize preview ----
    def _on_press(self, widget: QWidget, event: QMouseEvent) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        self._drag_widget = widget
        self._press_global = event.globalPosition().toPoint()
        self._press_geom = self._geometry_in_root(widget)
        edge = edge_at(event.position().toPoint(), widget.size())
        self._drag_mode = edge or "move"
        return True

    def _on_move(self, watched: QWidget, event: QMouseEvent) -> bool:
        if self._drag_widget is None or self._press_geom is None:
            return False
        delta = event.globalPosition().toPoint() - self._press_global
        rect = QRect(self._press_geom)
        if self._drag_mode == "move":
            rect.translate(delta)
        else:
            _apply_edge_delta(rect, self._drag_mode, delta)
        self._overlay.setGeometry(rect)
        self._overlay.raise_()
        self._overlay.show()
        self._window.setCursor(_CURSOR_BY_EDGE.get(self._drag_mode, Qt.CursorShape.SizeAllCursor))
        return True

    def _on_release(self, watched: QWidget, event: QMouseEvent) -> bool:
        if self._drag_widget is None:
            return False
        widget = self._drag_widget
        delta = event.globalPosition().toPoint() - self._press_global
        if abs(delta.x()) > _MOVE_THRESHOLD or abs(delta.y()) > _MOVE_THRESHOLD:
            if self._drag_mode == "move":
                self._log(f"MOVE {describe_widget(widget)} by ({delta.x():+d}, {delta.y():+d})px")
            else:
                rect = QRect(self._press_geom)
                _apply_edge_delta(rect, self._drag_mode, delta)
                self._log(
                    f"RESIZE {describe_widget(widget)} [{self._drag_mode}] "
                    f"from {self._press_geom.width()}x{self._press_geom.height()} "
                    f"to {rect.width()}x{rect.height()}"
                )
        self._cancel_drag()
        return True

    def _cancel_drag(self) -> None:
        self._drag_widget = None
        self._drag_mode = None
        self._press_global = None
        self._press_geom = None
        self._window.unsetCursor()
        self._overlay.hide()

    # ---- double-click text edit (applied live) ----
    def _on_double_click(self, widget: QWidget, event: QMouseEvent) -> bool:
        # The second press of the double-click landed and set drag state
        # just before this event arrives - this is a rename, not a drag.
        self._cancel_drag()

        text_getter = getattr(widget, "text", None)
        text_setter = getattr(widget, "setText", None)
        if not callable(text_getter) or not callable(text_setter):
            return False

        self._cancel_edit()
        current = text_getter()
        editor = QLineEdit(self._window)
        editor.setText(current)
        rect = self._geometry_in_root(widget)
        if rect is not None:
            editor.setGeometry(rect)
        editor.show()
        editor.raise_()
        editor.selectAll()
        editor.setFocus()

        self._edit_box = editor
        self._edit_target = widget
        editor.returnPressed.connect(lambda: self._commit_edit(widget, current))
        editor.editingFinished.connect(lambda: self._commit_edit(widget, current))
        return True

    def _commit_edit(self, widget: QWidget, previous: str) -> None:
        if self._edit_box is None or self._edit_target is not widget:
            return
        new_text = self._edit_box.text()
        self._edit_box.deleteLater()
        self._edit_box = None
        self._edit_target = None
        if new_text != previous:
            description = describe_widget(widget)  # before the rename, or it'd echo new_text
            widget.setText(new_text)
            self._log(f'TEXT {description} changed from "{previous}" to "{new_text}"')

    def _cancel_edit(self) -> None:
        if self._edit_box is not None:
            self._edit_box.deleteLater()
            self._edit_box = None
            self._edit_target = None

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_window.append(f"[{timestamp}] {message}")
