from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...theme.tokens import THEME

# (section, [(keys, what it does)]) - the one list the cheat sheet is drawn from. A "/" inside keys separates alternatives.
SHORTCUTS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Culling a roll", [
        ("Left / Right", "Previous / next photo"),
        ("Home / End", "First / last photo of the roll"),
        ("K", "Mark keeper (then on to the next photo)"),
        ("R", "Mark rejected (then on to the next photo)"),
        ("U", "Clear the flag"),
        ("0 - 5", "Star rating (0 clears it)"),
    ]),
    ("Viewing", [
        ("Z", "Toggle fit to window / 100%"),
        ("\\  (hold)", "Show the original scan while held"),
        ("Tab", "Hide / show the side panels"),
        ("Ctrl+H", "High quality (full resolution) on / off"),
        ("Ctrl+Shift+F", "Focus peaking on / off"),
        ("?  /  F1", "This cheat sheet"),
    ]),
    ("Editing", [
        ("Ctrl+Z", "Undo"),
        ("Ctrl+Y / Ctrl+Shift+Z", "Redo"),
        ("[  /  ]", "Rotate left / right"),
        ("Ctrl+Shift+A", "Auto crop & straighten"),
        ("Ctrl+Shift+R", "Reset all edits on this photo"),
        ("Ctrl+Shift+C", "Copy this photo's settings"),
        ("Ctrl+Shift+V", "Paste settings"),
    ]),
    ("Workbench", [
        ("W / D", "Workbench / back to the editor"),
        ("Arrows", "Move through the grid"),
        ("Enter", "Open the photo in the editor"),
        ("0 - 5", "Rate the selection"),
        ("K / R / U", "Keep / reject / clear the flag"),
        ("Ctrl+wheel", "Thumbnail size"),
    ]),
    ("Files", [
        ("Ctrl+Shift+O", "Open a folder"),
        ("Ctrl+E", "Quick export"),
        ("Drag and drop", "Drop a folder or photos on the window"),
    ]),
]


class ShortcutsDialog(QDialog):
    """The keyboard cheat sheet: every shortcut in two columns. Non-modal, so it can stay open beside the photo while the keys are learned."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.setModal(False)
        outer = QVBoxLayout(self)
        outer.setSpacing(THEME.space_lg)
        columns = QHBoxLayout()
        columns.setSpacing(THEME.space_xl)
        half = (len(SHORTCUTS) + 1) // 2
        for chunk in (SHORTCUTS[:half], SHORTCUTS[half:]):
            col = QVBoxLayout()
            col.setSpacing(THEME.space_md)
            for title, rows in chunk:
                head = QLabel(title.upper())
                head.setStyleSheet(f"color: {THEME.text_secondary}; font-weight: bold;")
                col.addWidget(head)
                grid = QGridLayout()
                grid.setHorizontalSpacing(THEME.space_lg)
                grid.setVerticalSpacing(THEME.space_sm)
                for i, (keys, what) in enumerate(rows):
                    key_label = QLabel(keys)
                    key_label.setStyleSheet(f"color: {THEME.text_primary}; font-family: Consolas;")
                    key_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    grid.addWidget(key_label, i, 0)
                    grid.addWidget(QLabel(what), i, 1)
                grid.setColumnMinimumWidth(0, 150)
                grid.setColumnStretch(1, 1)
                col.addLayout(grid)
            col.addStretch(1)
            columns.addLayout(col, 1)
        outer.addLayout(columns)
        note = QLabel("Letter and number keys do nothing while you are typing in a field.")
        note.setStyleSheet(f"color: {THEME.text_hint};")
        outer.addWidget(note)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        outer.addLayout(row)
