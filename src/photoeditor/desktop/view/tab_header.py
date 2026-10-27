"""A heading for each tool tab, after NegPy's tabs: the tab's icon and name in capitals over a line saying what the tab is for, and a smaller heading over each group of modules in it (TONE:
LIGHT, CURVES...), so the long run of modules reads as a few named parts instead of one list."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...theme.tokens import THEME
from . import panel_icons
from .dividers import SectionDivider

ROLE = "tab-heading"


class TabHeader(QWidget):
    """The icon and name of a tab (in capitals) and one line saying what the tab is for."""

    def __init__(self, tab_id: str, title: str, hint: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", ROLE)
        self.tab_id = tab_id
        column = QVBoxLayout(self)
        column.setContentsMargins(THEME.space_sm, THEME.space_sm, THEME.space_sm, 0)
        column.setSpacing(2)
        row = QHBoxLayout()
        row.setSpacing(THEME.space_md)
        icon = QLabel()
        icon.setPixmap(panel_icons.for_tab(tab_id, 18, THEME.text_primary))
        icon.setFixedWidth(20)
        row.addWidget(icon)
        self.title_label = QLabel(title.upper())
        font = QFont(self.title_label.font())
        font.setBold(True)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        self.title_label.setFont(font)
        self.title_label.setStyleSheet(f"color: {THEME.text_primary};")
        row.addWidget(self.title_label, 1)
        column.addLayout(row)
        self.hint_label = QLabel(hint)
        self.hint_label.setProperty("role", "hint")
        self.hint_label.setWordWrap(True)
        column.addWidget(self.hint_label)
        column.addSpacing(THEME.space_sm)
        column.addWidget(SectionDivider())


class GroupHeader(QWidget):
    """A small heading over a group of the modules in a tab, with a line along it."""

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", ROLE)
        row = QHBoxLayout(self)
        row.setContentsMargins(THEME.space_sm, THEME.space_md, THEME.space_sm, 0)
        row.setSpacing(THEME.space_md)
        self.label = QLabel(title.upper())
        font = QFont(self.label.font())
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
        self.label.setFont(font)
        self.label.setStyleSheet(f"color: {THEME.text_secondary};")
        row.addWidget(self.label)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {THEME.border_color}; border: none;")
        row.addWidget(line, 1, Qt.AlignmentFlag.AlignVCenter)


def dress_tab(column: QVBoxLayout, tab_id: str, title: str, hint: str, groups: tuple[tuple[str, QWidget], ...] = ()) -> TabHeader:
    """Put a TabHeader at the top of a tab's column and a GroupHeader in front of each named module (`groups`: (heading, the first module of the group))."""
    for heading, first in groups:
        position = column.indexOf(first)
        if position >= 0:
            column.insertWidget(position, GroupHeader(heading))
    header = TabHeader(tab_id, title, hint)
    column.insertWidget(0, header)
    return header
