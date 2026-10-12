from PyQt6.QtCore import QStringListModel, Qt, pyqtSignal
from PyQt6.QtWidgets import QAbstractItemView, QComboBox, QCompleter, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from ...features.tags import logic as tag_logic
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel

_ROLE_TAG = Qt.ItemDataRole.UserRole


class TagsEditor(QWidget):
    """Type tags (comma separated) and press Enter to add them, or pick one from the list of your tags under the box; select tags in the list and press
    Remove to take them off. A tag can sit inside another: type People/Family. Used for the open photo (TagsPanel) and for the Workbench's selection.
    It only asks (add_requested / remove_requested); whoever owns it changes the photos."""

    add_requested = pyqtSignal(list)
    remove_requested = pyqtSignal(list)

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
        self._mytags = QComboBox()
        self._mytags.setToolTip("Every tag you have made, so you pick it instead of typing it again. Nested tags are shown as Parent \u203a Child.")
        self._mytags.activated.connect(self._on_my_tag)
        col.addWidget(self._mytags)
        self._known_tags: list[str] = []
        self._fill_my_tags()
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
        self._fill_my_tags()

    def _fill_my_tags(self) -> None:
        """The drop-down: every tag that has been made (in use or not), in tree order, to pick instead of typing."""
        self._mytags.blockSignals(True)
        self._mytags.clear()
        self._mytags.addItem("Add one of my tags..." if self._known_tags else "No tags made yet - type one above", "")
        self._mytags.model().item(0).setEnabled(False)
        for tag in tag_logic.tree_order(self._known_tags):
            self._mytags.addItem(tag_logic.display(tag), tag)
        self._mytags.setCurrentIndex(0)
        self._mytags.blockSignals(False)

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
        for w in (self._entry, self._add_btn, self._mytags, self._list):
            w.setEnabled(active)
        self._refresh_buttons()

    def selected_tags(self) -> list[str]:
        return [i.data(_ROLE_TAG) for i in self._list.selectedItems()]

    def _refresh_buttons(self) -> None:
        self._remove_btn.setEnabled(self._list.isEnabled() and bool(self._list.selectedItems()))

    def _on_my_tag(self, index: int) -> None:
        tag = self._mytags.itemData(index)
        self._mytags.setCurrentIndex(0)
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
                      "everything inside it - and the drop-down under the box lists every tag you have made, to pick instead of typing. Press T anywhere for the quick tag bar: "
                      "type a few letters and press Enter to add the best match. They are saved with it (and in its .xmp sidecar, where Lightroom and darktable read them as keywords), "
                      "searchable in the Workbench with tag:name, and written into exported JPEGs as Windows tags.",
            collapsible=True,
            start_expanded=True,
            parent=parent,
        )
        self.editor = TagsEditor()
        self.body().addWidget(self.editor)
