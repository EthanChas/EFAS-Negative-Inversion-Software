"""The quick tag bar: a small box to type a few letters of a tag; the closest tags are listed, and Enter adds the top one."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from ...features.tags import logic as tag_logic

_ROLE = Qt.ItemDataRole.UserRole
MAX_ROWS = 12


class QuickTagDialog(QDialog):
    """Type, and the tags that fit best are listed under the box (best first, the first one highlighted). Enter adds the highlighted one - so after a
    few letters, Enter is all it takes - Up and Down choose another, Esc closes. If nothing fits, Enter adds what was typed as a new tag.
    A / in what you type nests a new tag (People/Family)."""

    chosen = pyqtSignal(str)

    def __init__(self, usage: dict[str, int], photo_count: int = 1, parent: QWidget | None = None, premade: list[str] | tuple[str, ...] = ()):
        super().__init__(parent)
        self.setWindowTitle("Quick tag")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setModal(True)
        self.setMinimumWidth(380)
        self._usage = dict(usage)
        self._candidates = list(dict.fromkeys([*self._usage, *premade]))
        col = QVBoxLayout(self)
        col.setSpacing(6)
        what = "this photo" if photo_count == 1 else f"the {photo_count} selected photos"
        self._title = QLabel(f"Tag {what}:")
        self._title.setProperty("role", "subtitle")
        col.addWidget(self._title)
        self._entry = QLineEdit()
        self._entry.setPlaceholderText("type a tag, then Enter")
        self._entry.textChanged.connect(self._refill)
        self._entry.installEventFilter(self)
        col.addWidget(self._entry)
        self._list = QListWidget()
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.itemClicked.connect(lambda item: self._pick(item.data(_ROLE)))
        col.addWidget(self._list)
        self._hint = QLabel("Enter adds the top match  -  Up/Down choose  -  Esc closes")
        self._hint.setProperty("role", "hint")
        col.addWidget(self._hint)
        self._refill("")
        self._entry.setFocus()

    # ---- results ----
    def results(self) -> list[str]:
        """The tags listed now, best first (the typed text itself, as a new tag, when nothing fits)."""
        typed = tag_logic.clean_tag(self._entry.text())
        if not typed:
            return sorted(self._candidates, key=lambda t: (-self._usage.get(t, 0), t.casefold()))[:MAX_ROWS]
        found = tag_logic.rank(typed, self._candidates, self._usage, limit=MAX_ROWS)
        return found or [typed]

    def _refill(self, _text: str) -> None:
        typed = tag_logic.clean_tag(self._entry.text())
        rows = self.results()
        self._list.clear()
        exists = {t.casefold() for t in self._candidates}
        for tag in rows:
            new = bool(typed) and tag.casefold() not in exists
            item = QListWidgetItem((f"New tag: {tag_logic.display(tag)}" if new else tag_logic.display(tag)))
            item.setData(_ROLE, tag)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)

    def selected(self) -> str | None:
        item = self._list.currentItem()
        return item.data(_ROLE) if item is not None else None

    def _pick(self, tag: str | None) -> None:
        if tag:
            self.chosen.emit(tag)
            self.accept()

    def _move(self, step: int) -> None:
        if self._list.count():
            self._list.setCurrentRow(max(0, min(self._list.count() - 1, self._list.currentRow() + step)))

    def eventFilter(self, watched, event) -> bool:
        if watched is self._entry and isinstance(event, QKeyEvent) and event.type() == QKeyEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._pick(self.selected())
                return True
            if key == Qt.Key.Key_Down:
                self._move(1)
                return True
            if key == Qt.Key.Key_Up:
                self._move(-1)
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)
