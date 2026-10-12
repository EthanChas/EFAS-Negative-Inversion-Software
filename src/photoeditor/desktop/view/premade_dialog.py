"""Edit the list of pre-made tags: the tags you use again and again, so you pick them instead of typing them."""

from PyQt6.QtCore import QStringListModel, Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...features.tags import logic as T

_TAG = Qt.ItemDataRole.UserRole


class PremadeTagsDialog(QDialog):
    """Left: your pre-made tags (Remove takes one off the list; it never touches a photo). Right: every tag you have - select some and Add to put them on the
    list. Or type a new one at the bottom: a / makes a level (People/Family)."""

    def __init__(self, premade: list[str], known: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("My pre-made tags")
        self.resize(640, 420)
        self._premade = list(premade)
        self._known = list(dict.fromkeys(known))
        col = QVBoxLayout(self)
        intro = QLabel(
            "Pre-made tags are the ones you use again and again. They are offered in the Pre-made drop-down under the tag box, in the quick tag bar and "
            "in the Tagging panel's right-click menu, so you never have to type them twice. Taking one off this list does not take it off any photo."
        )
        intro.setWordWrap(True)
        col.addWidget(intro)
        row = QHBoxLayout()
        left, right = QVBoxLayout(), QVBoxLayout()
        left.addWidget(QLabel("My pre-made tags"))
        self._mine = QListWidget()
        self._mine.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        left.addWidget(self._mine, 1)
        remove = QPushButton("Remove from the list")
        remove.clicked.connect(self._remove)
        left.addWidget(remove)
        right.addWidget(QLabel("All my tags"))
        self._all = QListWidget()
        self._all.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._all.itemDoubleClicked.connect(lambda item: self._add([item.data(_TAG)]))
        right.addWidget(self._all, 1)
        add = QPushButton("Add to my pre-made tags")
        add.clicked.connect(lambda: self._add([i.data(_TAG) for i in self._all.selectedItems()]))
        right.addWidget(add)
        row.addLayout(left, 1)
        row.addLayout(right, 1)
        col.addLayout(row, 1)
        typed = QHBoxLayout()
        self._entry = QLineEdit()
        self._entry.setPlaceholderText("or type a new pre-made tag, e.g. People/Family")
        completer = QCompleter(QStringListModel(self._known, self), self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._entry.setCompleter(completer)
        self._entry.returnPressed.connect(self._add_typed)
        typed.addWidget(self._entry, 1)
        typed_add = QPushButton("Add")
        typed_add.clicked.connect(self._add_typed)
        typed.addWidget(typed_add)
        col.addLayout(typed)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)
        self._refill()

    def tags(self) -> list[str]:
        """The list as it is now."""
        return list(self._premade)

    def _refill(self) -> None:
        self._mine.clear()
        for tag in self._premade:
            item = QListWidgetItem(T.display(tag))
            item.setData(_TAG, tag)
            self._mine.addItem(item)
        have = {t.casefold() for t in self._premade}
        self._all.clear()
        for tag in T.tree_order(t for t in self._known if t.casefold() not in have):
            item = QListWidgetItem(T.display(tag))
            item.setData(_TAG, tag)
            self._all.addItem(item)

    def _add(self, tags: list[str]) -> None:
        self._premade = T.unique([*self._premade, *tags])
        self._refill()

    def _add_typed(self) -> None:
        tag = T.clean_tag(self._entry.text())
        self._entry.clear()
        if tag:
            if not any(k.casefold() == tag.casefold() for k in self._known):
                self._known.append(tag)
            self._add([tag])

    def _remove(self) -> None:
        gone = {i.data(_TAG).casefold() for i in self._mine.selectedItems()}
        self._premade = [t for t in self._premade if t.casefold() not in gone]
        self._refill()
