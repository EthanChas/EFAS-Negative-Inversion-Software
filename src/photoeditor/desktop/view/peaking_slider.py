from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen, QWheelEvent
from PyQt6.QtWidgets import QWidget

from ...features.focuspeaking.logic import COLORS, NAMES
from ...theme.tokens import THEME

_PAD = 16          # from the box's edge to the first / last stop
_TRACK_Y = 13      # of the box, top to the track
_HEIGHT = 40
_WIDTH = 214


class PeakingSlider(QWidget):
    """The focus-peaking level slider that floats over the image: four stops - blue, green, yellow, red. The stop picked is the weakest level
    that is marked; the ones above it are marked too (red alone is the very sharpest). The stops below it are dimmed. Click or drag along
    the track, or use the wheel."""

    level_changed = pyqtSignal(int)  # 0 blue ... 3 red

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._level = 0
        self.setFixedSize(_WIDTH, _HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Focus peaking level: marks the picked color and everything sharper. Blue shows the most, red only the very sharpest.")
        self.hide()

    def level(self) -> int:
        return self._level

    def set_level(self, level: int, emit: bool = False) -> None:
        level = max(0, min(len(COLORS) - 1, int(level)))
        if level != self._level:
            self._level = level
            self.update()
            if emit:
                self.level_changed.emit(level)

    def _stop_x(self, index: int) -> float:
        return _PAD + (self.width() - 2 * _PAD) * index / (len(COLORS) - 1)

    def _level_at(self, x: float) -> int:
        return min(range(len(COLORS)), key=lambda i: abs(self._stop_x(i) - x))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.set_level(self._level_at(event.position().x()), emit=True)
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.set_level(self._level_at(event.position().x()), emit=True)
            event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:
        step = 1 if event.angleDelta().y() > 0 else -1
        self.set_level(self._level + step, emit=True)
        event.accept()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(0, 0, 0, 200))
        painter.setPen(QPen(QColor(THEME.border_color), 1))
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 4, 4)
        left, right = self._stop_x(0), self._stop_x(len(COLORS) - 1)
        painter.setPen(QPen(QColor(255, 255, 255, 60), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(left, _TRACK_Y), QPointF(right, _TRACK_Y))
        reach = self._stop_x(self._level)  # the part of the track that is marked: from the picked stop up
        painter.setPen(QPen(QColor(*COLORS[self._level]), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(reach, _TRACK_Y), QPointF(right, _TRACK_Y))
        for i, color in enumerate(COLORS):
            x = self._stop_x(i)
            on = i >= self._level
            radius = 6.0 if i == self._level else 4.0
            painter.setPen(QPen(QColor(255, 255, 255), 2) if i == self._level else Qt.PenStyle.NoPen)
            painter.setBrush(QColor(*color) if on else QColor(110, 110, 110))
            painter.drawEllipse(QPointF(x, _TRACK_Y), radius, radius)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(*COLORS[self._level]))
        name = NAMES[self._level] + ("" if self._level == len(COLORS) - 1 else " and sharper")
        painter.drawText(QRectF(0, 22, self.width(), 16), Qt.AlignmentFlag.AlignCenter, f"Peaking: {name}")
        painter.end()
