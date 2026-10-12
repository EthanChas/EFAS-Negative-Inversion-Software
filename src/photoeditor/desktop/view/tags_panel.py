from PyQt6.QtCore import QStringListModel, Qt, pyqtSignal
from PyQt6.QtWidgets import QAbstractItemView, QComboBox, QCompleter, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from ...features.tags import logic as tag_logic
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .premade_dialog import PremadeTagsDialog

_ROLE_TAG = Qt.ItemDataRole.UserRole


class TagsEditor(QWidget):
    """Type tags (comma separated) and press Enter to add them, or pick one from the pre-made list under the box; select tags in the list and press
    Remove to take them off. A tag can sit inside another: type People/Family. Used for the open photo (TagsPanel) and for the Workbench's selection.
    It only asks (add_requested / remove_requested); whoever owns it changes the photos."""

    add_requested = pyqtSignal(list)
    remove_requested = pyqtSignal(list)
    premade_add_requested = pyqtSignal(list)      # tags to put on the user's pre-made list
    premade_remove_requested = pyqtSignal(list)   # tags to take off it

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(THEME.space_sm)
        row = QHBoxLayout()
        row.setSpacing(THEME.space_sm)
        self._entry = QLineEdit()
        self._entry.setPlaceholderText("Add tags: holiday, People/Family")
        self._entry.setToolTip("Type one or more tags, separated by commas, and press Enter. Put a / between levels to nest a tag (People/Family): searching "
                               "for People then finds everything inside it. Tags are searchable in the Workbench (tag:holiday).")
        self._model = QStringListModel(self)
        completer = QCompleter(self._model, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._entry.setCompleter(completer)
        self._entry.returnPressed.connect(self._add)
        row.addWidget(self._entry, 1)
        self._add_btn = QPushButton("Add")
        self._add_btn.clicked.connect(self._add)
        row.addWidget(self._add_btn)
        col.addLayout(row)
        premade_row = QHBoxLayout()
        premade_row.setSpacing(THEME.space_sm)
        self._premade = QComboBox()
        self._premade.setToolTip("Your own pre-made tags, the ones you use again and again: pick one to add it, without typing. Manage... edits the list.")
        self._premade.activated.connect(self._on_premade)
        premade_row.addWidget(self._premade, 1)
        self._manage_btn = QPushButton("Manage...")
        self._manage_btn.setToolTip("Choose which tags are on your pre-made list")
        self._manage_btn.clicked.connect(self._manage_premade)
        premade_row.addWidget(self._manage_btn)
        col.addLayout(premade_row)
        self._premade_list: list[str] = []
        self._known_tags: list[str] = []
        self.set_premade([])
        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.setFixedHeight(84)
        self._list.itemSelectionChanged.connect(self._refresh_buttons)
        col.addWidget(self._list)
        remove_row = QHBoxLayout()
        self._hint = QLabel("")
        self._hint.setProperty("role", "hint")
        self._remove_btn = QPushButton("Remove Selected")
        self._remove_btn.setToolTip("Take the selected tags off")
        self._remove_btn.clicked.connect(self._remove)
        remove_row.addWidget(self._hint, 1)
        remove_row.addWidget(self._remove_btn)
        col.addLayout(remove_row)
        self.set_tags([])

    def set_suggestions(self, tags: list[str]) -> None:
        """Every tag in use, offered as you type."""
        self._known_tags = list(tags)
        self._model.setStringList(list(tags))

    def set_premade(self, tags: list[str]) -> None:
        """The user's pre-made tags, for the drop-down."""
        self._premade_list = list(tags)
        self._premade.blockSignals(True)
        self._premade.clear()
        self._premade.addItem("Add a pre-made tag..." if tags else "No pre-made tags yet - click Manage", "")
        self._premade.model().item(0).setEnabled(False)
        for tag in tags:
            self._premade.addItem(tag_logic.display(tag), tag)
        self._premade.setCurrentIndex(0)
        self._premade.blockSignals(False)

    def _manage_premade(self) -> None:
        dialog = PremadeTagsDialog(self._premade_list, self._known_tags, self)
        if not dialog.exec():
            return
        new = dialog.tags()
        old_keys, new_keys = {t.casefold() for t in self._premade_list}, {t.casefold() for t in new}
        added = [t for t in new if t.casefold() not in old_keys]
        removed = [t for t in self._premade_list if t.casefold() not in new_keys]
        if added:
            self.premade_add_requested.emit(added)
        if removed:
            self.premade_remove_requested.emit(removed)

    def set_tags(self, tags: list[str], labels: dict[str, str] | None = None) -> None:
        """The tags to list."""
        self._list.clear()
        for tag in tag_logic.tree_order(tags):
            item = QListWidgetItem((labels or {}).get(tag, tag_logic.display(tag)))
            item.setToolTip(tag)
            item.setData(_ROLE_TAG, tag)
            self._list.addItem(item)
        self._hint.setText("" if tags else "No tags yet")
        self._refresh_buttons()

    def set_active(self, active: bool) -> None:
        for w in (self._entry, self._add_btn, self._premade, self._list):
            w.setEnabled(active)
        self._refresh_buttons()

    def selected_tags(self) -> list[str]:
        return [i.data(_ROLE_TAG) for i in self._list.selectedItems()]

    def _refresh_buttons(self) -> None:
        self._remove_btn.setEnabled(self._list.isEnabled() and bool(self._list.selectedItems()))

    def _on_premade(self, index: int) -> None:
        tag = self._premade.itemData(index)
        self._premade.setCurrentIndex(0)
        if tag:
            self.add_requested.emit([tag])

    def _add(self) -> None:
        tags = tag_logic.parse_tags(self._entry.text())
        self._entry.clear()
        if tags:
            self.add_requested.emit(tags)

    def _remove(self) -> None:
        tags = self.selected_tags()
        if tags:
            self.remove_requested.emit(tags)


class TagsPanel(CollapsiblePanel):
    """The open photo's tags, in the Metadata tab."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Tags",
            help_text="Keywords for this photo. Put a / between levels to nest one inside another (People/Family) - searching for People then finds "
                      "everything inside it - and keep your own pre-made list (Manage...) of the tags you use again and again, to pick instead of typing. Press T anywhere for the quick tag bar: "
                      "type a few letters and press Enter to add the best match. They are saved with it (and in its .xmp sidecar, where Lightroom and darktable read them as keywords), "
                      "searchable in the Workbench with tag:name, and written into exported JPEGs as Windows tags.",
            collapsible=True,
            start_expanded=True,
            parent=parent,
        )
        self.editor = TagsEditor()
        self.body().addWidget(self.editor)
