"""Find (Ctrl+K): type what you are after and jump to it - a module, a slider, a button, a menu action, a preset or a smart collection."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from ...features.find import logic as F

_KIND_LABEL = {"module": "Module", "control": "Control", "action": "Menu", "preset": "Preset", "collection": "Collection"}
_ROLE = Qt.ItemDataRole.UserRole


class FindDialog(QDialog):
    """A small window with a search box and the best matches under it. Up and Down choose, Enter goes there, Esc closes."""

    chosen = pyqtSignal(object)

    def __init__(self, entries: list[F.Entry], parent=None):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.setMinimumWidth(460)
        self._entries = entries
        col = QVBoxLayout(self)
        self.hint = QLabel("Find a module, slider or action by name or by what it does (try: brightness, straighten, vignette)")
        self.hint.setProperty("role", "hint")
        self.hint.setWordWrap(True)
        col.addWidget(self.hint)
        self.box = QLineEdit()
        self.box.setPlaceholderText("Type to find...")
        self.box.textChanged.connect(self._refresh)
        col.addWidget(self.box)
        self.list = QListWidget()
        self.list.setMinimumHeight(260)
        self.list.itemActivated.connect(self._pick)
        self.list.itemClicked.connect(self._pick)
        col.addWidget(self.list)
        self.box.installEventFilter(self)
        self.box.setFocus()

    def eventFilter(self, obj, event) -> bool:
        from PyQt6.QtCore import QEvent

        if obj is self.box and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = self.list.currentRow() + (1 if key == Qt.Key.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self.list.currentItem() or (self.list.item(0) if self.list.count() else None)
                if item is not None:
                    self._pick(item)
                return True
        return super().eventFilter(obj, event)

    def _refresh(self, text: str) -> None:
        self.list.clear()
        found = F.search(self._entries, text)
        for e in found:
            item = QListWidgetItem(f"{e.title}      {_KIND_LABEL.get(e.kind, '')}" + (f"  -  {e.where}" if e.where else ""))
            item.setData(_ROLE, e)
            self.list.addItem(item)
        if found:
            self.list.setCurrentRow(0)
        self.hint.setVisible(not text.strip())
        if text.strip() and not found:
            self.list.addItem(QListWidgetItem("Nothing matches. Try another word."))
            self.list.item(0).setFlags(Qt.ItemFlag.NoItemFlags)

    def _pick(self, item: QListWidgetItem) -> None:
        entry = item.data(_ROLE)
        if entry is not None:
            self.accept()
            self.chosen.emit(entry)
