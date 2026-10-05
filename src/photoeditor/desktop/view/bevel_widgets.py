import math

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QPainter, QPaintEvent, QPen, QPolygon
from PyQt6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from ...theme.tokens import THEME


class BevelPanel(QWidget):
    """A hand-painted 3D bevel panel - raised or sunken. QSS `border:` on a
    bare QFrame/QWidget proved unreliable in this style of app (background-
    color renders, the border never does), so anything needing a real Win98
    bevel that isn't a QPushButton/QGroupBox (which do support it natively)
    goes through this instead. Add content via `.layout()`."""

    def __init__(
        self,
        *,
        sunken: bool = True,
        bg: str | None = None,
        thickness: int = THEME.border_width,
        margin: int = 0,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._sunken = sunken
        self._bg = QColor(bg or THEME.bg_app)
        self._thickness = thickness

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            margin + thickness, margin + thickness, margin + thickness, margin + thickness
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        rect = self.rect()
        painter.fillRect(rect, self._bg)

        light = QColor(THEME.bevel_light)
        dark = QColor(THEME.border_color)
        top_left = dark if self._sunken else light
        bottom_right = light if self._sunken else dark

        w, h = rect.width(), rect.height()
        for i in range(self._thickness):
            painter.setPen(top_left)
            painter.drawLine(i, i, w - 1 - i, i)
            painter.drawLine(i, i, i, h - 1 - i)
            painter.setPen(bottom_right)
            painter.drawLine(w - 1 - i, i, w - 1 - i, h - 1 - i)
            painter.drawLine(i, h - 1 - i, w - 1 - i, h - 1 - i)
        painter.end()


def thin_sunken_panel(h_margin: int = THEME.space_sm, v_margin: int = THEME.space_sm) -> BevelPanel:
    """A thin sunken field, reused anywhere that needs a simple indented frame."""
    panel = BevelPanel(sunken=True, thickness=1)
    panel.layout().setContentsMargins(h_margin, v_margin, h_margin, v_margin)
    return panel


class VLine(QWidget):
    """A thin vertical divider line - hand-painted like everything else here."""

    def __init__(self, thickness: int = 1, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedWidth(thickness)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(THEME.border_color))


class HLine(QWidget):
    """A thin horizontal divider line - hand-painted like everything else here."""

    def __init__(self, thickness: int = 1, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(thickness)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(THEME.border_color))


class CaptionButton(QPushButton):
    """A tiny header-style button that draws its own glyph with QPainter
    rather than leaning on QPushButton's own text layout - the global QSS
    button padding (sized for normal buttons) would consume this button's
    entire content area, clipping any real button text invisible. Supports
    "min"/"max"/"close" (the title bar's own window controls), "help" (a
    bold "?"), "collapse" (a triangle that points down when expanded, right
    when collapsed - see set_expanded), "add" (a plus) and "refresh" (a
    circular arrow)."""

    def __init__(self, kind: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._kind = kind
        self._expanded = True  # only meaningful for kind == "collapse"
        self.setFixedSize(THEME.title_button_size, THEME.title_button_size - 2)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(QColor(THEME.text_primary), 1))

        w, h = self.width(), self.height()
        offset = 1 if self.isDown() else 0
        cx, cy = w // 2 + offset, h // 2 + offset

        if self._kind == "min":
            painter.drawLine(cx - 3, cy + 3, cx + 3, cy + 3)
        elif self._kind == "max":
            painter.drawRect(cx - 3, cy - 4, 7, 7)
        elif self._kind == "close":
            painter.drawLine(cx - 3, cy - 3, cx + 4, cy + 4)
            painter.drawLine(cx - 3, cy + 4, cx + 4, cy - 3)
        elif self._kind == "help":
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            rect = self.rect().translated(offset, offset)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "?")
        elif self._kind == "collapse":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(THEME.text_primary))
            if self._expanded:
                triangle = QPolygon([
                    QPoint(cx - 4, cy - 2), QPoint(cx + 4, cy - 2), QPoint(cx, cy + 3),
                ])
            else:
                triangle = QPolygon([
                    QPoint(cx - 2, cy - 4), QPoint(cx - 2, cy + 4), QPoint(cx + 3, cy),
                ])
            painter.drawPolygon(triangle)
        elif self._kind == "add":
            painter.drawLine(cx - 4, cy, cx + 4, cy)
            painter.drawLine(cx, cy - 4, cx, cy + 4)
        elif self._kind == "menu":  # three lines: a presets menu
            for dy in (-3, 0, 3):
                painter.drawLine(cx - 4, cy + dy, cx + 4, cy + dy)
        elif self._kind == "refresh":
            painter.setBrush(Qt.BrushStyle.NoBrush)
            r = 4
            painter.drawArc(QRect(cx - r, cy - r, 2 * r, 2 * r), 45 * 16, 270 * 16)
            angle = math.radians(45)
            tip_x, tip_y = cx + r * math.cos(angle), cy - r * math.sin(angle)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(THEME.text_primary))
            arrow = QPolygon([
                QPoint(round(tip_x), round(tip_y)),
                QPoint(round(tip_x - 3), round(tip_y - 2)),
                QPoint(round(tip_x + 1), round(tip_y + 3)),
            ])
            painter.drawPolygon(arrow)
        painter.end()
