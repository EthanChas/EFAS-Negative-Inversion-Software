"""The Settings > Themes page's pictures: a small mock-up of the program in each theme, and the round accent colour swatches."""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from ...theme import runtime
from ...theme.tokens import ThemeConfig


class ThemeCard(QAbstractButton):
    """A clickable mock-up window painted from a theme's own colours (not the one in force), so each card shows what choosing it will look like."""

    def __init__(self, theme: ThemeConfig, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._theme = theme
        self._title = title
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(236, 168)

    def set_theme(self, theme: ThemeConfig) -> None:
        self._theme = theme
        self.update()

    def paintEvent(self, _event) -> None:
        t = self._theme
        modern = t.style == "modern"
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, modern)
        outer = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        selected = self.isChecked()
        p.setPen(QPen(QColor(t.accent_primary if selected else t.border_color), 3 if selected else 1))
        p.setBrush(QColor(t.bg_app))
        p.drawRoundedRect(outer, 8 if modern else 0, 8 if modern else 0)

        bar = QRectF(outer.left() + 1, outer.top() + 1, outer.width() - 2, 22)
        if modern:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t.bg_app))
            p.drawRect(bar)
        else:
            gradient = QLinearGradient(bar.topLeft(), bar.topRight())
            gradient.setColorAt(0, QColor(t.accent_primary))
            gradient.setColorAt(1, QColor(t.accent_hover))
            p.fillRect(bar, gradient)
        font = QFont(self.font())
        font.setPointSize(8)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(t.text_primary if modern else t.on_accent))
        p.drawText(bar.adjusted(10, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "EFAS Negative Inversion Software")

        panel = QRectF(outer.left() + 10, bar.bottom() + 8, outer.width() - 20, outer.height() - 70)
        p.setPen(QPen(QColor(t.border_color), 1))
        p.setBrush(QColor(t.bg_panel if modern else t.bg_app))
        p.drawRoundedRect(panel, 8 if modern else 0, 8 if modern else 0)
        if not modern:  # the bevel
            p.setPen(QColor(t.bevel_light))
            p.drawLine(panel.topLeft(), panel.topRight())
            p.drawLine(panel.topLeft(), panel.bottomLeft())

        p.setPen(QColor(t.text_primary))
        font.setBold(modern)
        p.setFont(font)
        p.drawText(QPointF(panel.left() + 10, panel.top() + 17), "Exposure")
        y = panel.top() + 32
        track = QRectF(panel.left() + 10, y, panel.width() - 20, 4 if modern else 6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.track))
        p.drawRoundedRect(track, 2 if modern else 0, 2 if modern else 0)
        covered = QRectF(track.left(), track.top(), track.width() * 0.62, track.height())
        if modern:
            p.setBrush(QColor(t.accent_primary))
            p.drawRoundedRect(covered, 2, 2)
            p.setPen(QPen(QColor(t.accent_primary), 3))
            p.setBrush(QColor(t.text_primary))
            p.drawEllipse(QPointF(covered.right(), track.center().y()), 6, 6)
        else:
            p.setPen(QColor(t.border_color))
            p.setBrush(QColor(t.bg_app))
            p.drawRect(QRectF(covered.right() - 4, track.top() - 4, 8, 14))

        button = QRectF(panel.left() + 10, panel.bottom() - 30, 70, 20)
        p.setPen(QPen(QColor(t.border_color), 1))
        p.setBrush(QColor(t.bg_button))
        p.drawRoundedRect(button, 6 if modern else 0, 6 if modern else 0)
        p.setPen(QColor(t.text_primary))
        p.drawText(button, Qt.AlignmentFlag.AlignCenter, "Reset")
        accent = QRectF(button.right() + 8, button.top(), 70, 20)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.accent_primary))
        p.drawRoundedRect(accent, 6 if modern else 0, 6 if modern else 0)
        p.setPen(QColor(t.on_accent))
        p.drawText(accent, Qt.AlignmentFlag.AlignCenter, "Save")

        label_font = QFont(self.font())
        label_font.setPointSize(10)
        label_font.setBold(True)
        p.setFont(label_font)
        p.setPen(QColor(t.text_primary))
        p.drawText(QRectF(outer.left() + 12, outer.bottom() - 28, outer.width() - 24, 24), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._title)
        if selected:
            p.setPen(QColor(t.accent_primary))
            p.drawText(QRectF(outer.left() + 12, outer.bottom() - 28, outer.width() - 24, 24), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "Selected")
        p.end()


class AccentSwatch(QAbstractButton):
    """A round colour button; the chosen one gets a ring."""

    def __init__(self, name: str, colour: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.name, self._colour = name, colour
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setToolTip(name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(34, 34)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._colour))
        p.drawEllipse(QRectF(self.rect()).adjusted(6, 6, -6, -6))
        if self.isChecked():
            p.setPen(QPen(QColor(self._colour), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(self.rect()).adjusted(2, 2, -2, -2))
        elif not self.isEnabled():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 110))
            p.drawEllipse(QRectF(self.rect()).adjusted(6, 6, -6, -6))
        p.end()


def card_theme(name: str, values: dict) -> ThemeConfig:
    """The theme a card for `name` should show, with the user's accent and text size."""
    return runtime.build_theme({**values, "theme": name})
