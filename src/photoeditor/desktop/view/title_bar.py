from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QLinearGradient, QMouseEvent, QPainter, QPaintEvent
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ...theme.tokens import THEME
from .bevel_widgets import CaptionButton
from .icons import photo_icon


class TitleBar(QWidget):
    """A hand-painted Windows 98 title bar - the native OS chrome can't be
    themed, so the window runs frameless and this replaces it entirely: the
    gradient bar, the draggable area, and minimize/maximize ("full screen")/
    close. The gradient fill is painted directly (paintEvent below) rather
    than via QSS `background:`, same reliability reasoning as bevel_widgets.py
    and window_frame.py."""

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setFixedHeight(THEME.title_bar_height)
        self.setAutoFillBackground(False)

        row = QHBoxLayout(self)
        row.setContentsMargins(THEME.space_sm, 2, 2, 2)
        row.setSpacing(THEME.space_sm)

        icon_label = QLabel()
        icon_label.setPixmap(photo_icon(THEME.title_bar_height - 8))
        row.addWidget(icon_label)

        self._label = QLabel(title)
        row.addWidget(self._label)
        row.addStretch(1)

        self._min_btn = CaptionButton("min")
        self._max_btn = CaptionButton("max")
        self._close_btn = CaptionButton("close")
        for b in (self._min_btn, self._max_btn, self._close_btn):
            row.addWidget(b)

        self._min_btn.clicked.connect(self._minimize)
        self._max_btn.clicked.connect(self._toggle_maximize)
        self._close_btn.clicked.connect(self._close)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        gradient = QLinearGradient(0, 0, self.width(), 0)
        gradient.setColorAt(0, QColor(THEME.accent_primary))
        gradient.setColorAt(1, QColor(THEME.accent_hover))
        painter.fillRect(self.rect(), gradient)
        painter.end()

    # ---- window controls ----
    def _minimize(self) -> None:
        self.window().showMinimized()

    def _toggle_maximize(self) -> None:
        window = self.window()
        if window.isMaximized():
            window.showNormal()
        else:
            window.showMaximized()

    def _close(self) -> None:
        self.window().close()

    # ---- drag to move ----
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximize()
            event.accept()
