from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QColor, QCursor, QMouseEvent, QPainter, QPaintEvent
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ...theme.tokens import THEME

_RESIZE_MARGIN = 6

_CURSOR_BY_EDGES = {
    frozenset({Qt.Edge.LeftEdge}): Qt.CursorShape.SizeHorCursor,
    frozenset({Qt.Edge.RightEdge}): Qt.CursorShape.SizeHorCursor,
    frozenset({Qt.Edge.TopEdge}): Qt.CursorShape.SizeVerCursor,
    frozenset({Qt.Edge.BottomEdge}): Qt.CursorShape.SizeVerCursor,
    frozenset({Qt.Edge.TopEdge, Qt.Edge.LeftEdge}): Qt.CursorShape.SizeFDiagCursor,
    frozenset({Qt.Edge.BottomEdge, Qt.Edge.RightEdge}): Qt.CursorShape.SizeFDiagCursor,
    frozenset({Qt.Edge.TopEdge, Qt.Edge.RightEdge}): Qt.CursorShape.SizeBDiagCursor,
    frozenset({Qt.Edge.BottomEdge, Qt.Edge.LeftEdge}): Qt.CursorShape.SizeBDiagCursor,
}


class WindowFrame(QWidget):
    """The outer raised-bevel window border, standing in for the native OS
    frame on a frameless window - same approach as EthanDailyClocker's
    utility app. The bevel is hand-painted (QSS `border:` on a bare
    QWidget/QFrame proved unreliable here). Also owns edge/corner resize,
    since a frameless window has none of that for free. Add the title bar
    and content to `.layout()` in order - this is just a styled QVBoxLayout
    host."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("windowFrame")
        self.setMouseTracking(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            THEME.window_border_width, THEME.window_border_width,
            THEME.window_border_width, THEME.window_border_width,
        )
        layout.setSpacing(0)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        rect = self.rect()
        painter.fillRect(rect, QColor(THEME.bg_app))

        light = QColor(THEME.bevel_light)
        dark = QColor(THEME.border_color)
        outline = QColor(THEME.text_primary)
        w, h = rect.width(), rect.height()

        # A one-pixel dark outline, then a raised bevel for the rest of the
        # frame's thickness - the classic two-tier Win98 window border. Only
        # the title bar itself carries the accent color, not the outer frame.
        painter.setPen(outline)
        painter.drawRect(0, 0, w - 1, h - 1)

        for i in range(1, THEME.window_border_width):
            painter.setPen(light)
            painter.drawLine(i, i, w - 1 - i, i)
            painter.drawLine(i, i, i, h - 1 - i)
            painter.setPen(dark)
            painter.drawLine(w - 1 - i, i, w - 1 - i, h - 1 - i)
            painter.drawLine(i, h - 1 - i, w - 1 - i, h - 1 - i)
        painter.end()

    def _edges_at(self, x: int, y: int) -> frozenset:
        edges = set()
        if x <= _RESIZE_MARGIN:
            edges.add(Qt.Edge.LeftEdge)
        elif x >= self.width() - _RESIZE_MARGIN:
            edges.add(Qt.Edge.RightEdge)
        if y <= _RESIZE_MARGIN:
            edges.add(Qt.Edge.TopEdge)
        elif y >= self.height() - _RESIZE_MARGIN:
            edges.add(Qt.Edge.BottomEdge)
        return frozenset(edges)

    def sync_cursor(self) -> None:
        """Recompute the resize cursor from the true mouse position, rather
        than relying on this widget's own mouseMoveEvent - a child (menu
        bar, splitter, image view) covers most of the resize margin, so once
        it takes mouse events over from WindowFrame, WindowFrame never sees
        the move that should have reset the cursor back to normal. Called
        from an app-wide event filter instead (installed by AppWindow)."""
        if self.window().isMaximized():
            self.unsetCursor()
            return
        local = self.mapFromGlobal(QCursor.pos())
        if not self.rect().contains(local):
            self.unsetCursor()
            return
        edges = self._edges_at(local.x(), local.y())
        self.setCursor(QCursor(_CURSOR_BY_EDGES.get(edges, Qt.CursorShape.ArrowCursor)))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self.window().isMaximized():
            return
        pos = event.position().toPoint()
        edges = self._edges_at(pos.x(), pos.y())
        if not edges:
            return
        handle = self.window().windowHandle()
        if handle is not None:
            qt_edges = Qt.Edge(0)
            for e in edges:
                qt_edges |= e
            handle.startSystemResize(qt_edges)
            event.accept()


class CursorSyncFilter(QObject):
    """Installed on the QApplication (see AppWindow) so the resize cursor
    tracks the true mouse position on every move, anywhere in the window -
    see `WindowFrame.sync_cursor` for why this can't just live in
    WindowFrame's own mouseMoveEvent."""

    def __init__(self, frame: WindowFrame, parent: QObject | None = None):
        super().__init__(parent)
        self._frame = frame

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.MouseMove:
            self._frame.sync_cursor()
        return False
