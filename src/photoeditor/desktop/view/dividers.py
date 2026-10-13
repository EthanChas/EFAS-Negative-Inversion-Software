"""Thin dividing lines between the sections inside a module, so a long module reads as groups instead of one run of controls."""
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ...theme.tokens import THEME
from .module_style import STYLE

ROLE = "divider"


class SectionDivider(QFrame):
    """A one-pixel line across the module, in the theme's border colour, with a little room above and below it."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", ROLE)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFixedHeight(1)
        self.apply_theme()
        STYLE.changed.connect(self.apply_theme)

    def apply_theme(self) -> None:
        self.setStyleSheet(f"background: {THEME.text_muted}; border: none; margin: 0px;")


def add_divider(layout: QVBoxLayout) -> SectionDivider:
    """Put a divider at the end of a module's layout (with a gap of the theme's small spacing each side)."""
    gap = THEME.space_sm
    layout.addSpacing(gap)
    divider = SectionDivider()
    layout.addWidget(divider)
    layout.addSpacing(gap)
    return divider


def _is_divider(item) -> bool:
    widget = item.widget()
    return widget is not None and widget.property("role") == ROLE


def insert_before_headings(layout: QVBoxLayout) -> int:
    """Walk a module's layout and put a divider in front of every section heading (a QLabel with role "subtitle") that has something above it. Returns how many were
    added. A heading already preceded by a divider (spacers between them do not count) is left alone, so calling it twice changes nothing."""
    added = 0
    i = 0
    while i < layout.count():
        widget = layout.itemAt(i).widget()
        if isinstance(widget, QLabel) and widget.property("role") == "subtitle":
            j = i - 1
            while j >= 0 and layout.itemAt(j).spacerItem() is not None:
                j -= 1
            if j >= 0 and not _is_divider(layout.itemAt(j)):
                gap = THEME.space_sm
                layout.insertSpacing(i, gap)
                layout.insertWidget(i + 1, SectionDivider())
                layout.insertSpacing(i + 2, gap)
                i += 3
                added += 1
        i += 1
    return added
