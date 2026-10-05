from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...features.keybinds import logic as binds
from ...theme.tokens import THEME


def _show(seq: str) -> str:
    return seq if seq else "(none)"


def build_sections(current: dict[str, str]) -> list[tuple[str, list[tuple[str, str]]]]:
    """The cheat sheet's rows - (section, [(keys, what it does)]) - from the keys as they are bound right now, plus the keys that never change.
    The six rating keys share one row."""
    order: list[str] = []
    rows: dict[str, list[tuple[str, str]]] = {}
    stars = [current.get(i, "") for i in binds.RATING_IDS]
    for action in binds.ACTIONS:
        if action.category not in rows:
            order.append(action.category)
            rows[action.category] = []
        if action.id in binds.RATING_IDS:
            if action.id == binds.RATING_IDS[0]:
                default = stars == [binds.DEFAULT_BINDINGS[i] for i in binds.RATING_IDS]
                rows[action.category].append(("0 - 5" if default else "  ".join(_show(x) for x in stars), "Star rating (0 clears it; the same number again removes it)"))
            continue
        rows[action.category].append((_show(current.get(action.id, "")), action.label))
    for category, keys, what in binds.FIXED_KEYS:
        rows.setdefault(category, []).append((keys, what))
        if category not in order:
            order.append(category)
    return [(c, rows[c]) for c in order]


class ShortcutsDialog(QDialog):
    """The keyboard cheat sheet: every shortcut in two columns. Non-modal, so it can stay open beside the photo while the keys are learned."""

    def __init__(self, parent: QWidget | None = None, current: dict[str, str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        sections = build_sections(current if current is not None else binds.DEFAULT_BINDINGS)
        self.setModal(False)
        outer = QVBoxLayout(self)
        outer.setSpacing(THEME.space_lg)
        columns = QHBoxLayout()
        columns.setSpacing(THEME.space_xl)
        half = (len(sections) + 1) // 2
        for chunk in (sections[:half], sections[half:]):
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
        note = QLabel("Letter and number keys do nothing while you are typing in a field. Change any of these in Settings > Preferences > Keybinds.")
        note.setStyleSheet(f"color: {THEME.text_hint};")
        outer.addWidget(note)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        outer.addLayout(row)
