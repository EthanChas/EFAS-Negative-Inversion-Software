"""The Tagging panel, on the left of the editor and of the Workbench - laid out like darktable's Tagging module.

Top: the tags attached to the photo(s) in front of you (the open photo, or the Workbench's selection), with counts when there are several.
Below: the tag dictionary - every tag there is - with an entry box that filters it, a flat list or a tree, and marks for which tags are on all
(check) or some (dash) of those photos. Double-click a dictionary tag to attach it, an attached tag to detach it. Right-click for the rest."""

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...features.tags import logic as T
from ...features.tags import tagging as G
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel

_TAG = Qt.ItemDataRole.UserRole.value
_DEFINED = _TAG + 1
_LIST_HEIGHT = 96
_DICT_HEIGHT = 190


def _small(text: str, tip: str, checkable: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setToolTip(tip)
    button.setCheckable(checkable)
    return button


class TaggingPanel(CollapsiblePanel):
    attach_requested = pyqtSignal(list)           # tags to put on the photos in front of you
    detach_requested = pyqtSignal(list)           # tags to take off them
    create_requested = pyqtSignal(str, bool)      # a new tag (typed), and whether to attach it too
    rename_requested = pyqtSignal(str, str)       # tag, its new whole path (what is inside it moves along)
    delete_requested = pyqtSignal(str, bool)      # tag, and whether what is inside it goes too
    collection_requested = pyqtSignal(str)        # show the photos with this tag in the Workbench
    import_requested = pyqtSignal(str)            # the text of a keyword file
    export_requested = pyqtSignal(str)            # where to write the keyword file

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Tagging",
            help_text=(
                "Like darktable's Tagging module. The top list is the tags on the photo(s) in front of you (the open photo; in the Workbench, the selected "
                "ones, with how many of them have each). The dictionary below is every tag there is: type in the box to filter it - Enter attaches the best "
                "match, or makes the tag if nothing fits (New makes exactly what you typed) - and double-click a tag to attach it, or an attached tag to "
                "detach it. A check mark is a tag on all those photos, a dash on some. List or Tree shows the dictionary flat or nested (a / makes a level, "
                "People/Family); Suggest lists tags that usually go with the ones attached. Right-click a tag to rename it, change its path (what is inside "
                "it moves too), delete it, or see its photos. Import and Export read and write a Lightroom keyword file."
            ),
            collapsible=True,
            start_expanded=True,
            parent=parent,
        )
        self._paths: list[str] = []
        self._per_path: dict[str, list[str]] = {}
        self._dictionary: dict[str, int] = {}
        self._tag_lists = lambda: []
        self._expanded: set[str] = set()
        body = self.body()
        body.setSpacing(THEME.space_sm)

        self._hint = QLabel("")
        self._hint.setProperty("role", "hint")
        self._hint.setWordWrap(True)
        body.addWidget(self._hint)

        head = QHBoxLayout()
        head.setSpacing(THEME.space_sm)
        title = QLabel("ATTACHED")
        title.setProperty("role", "subtitle")
        head.addWidget(title, 1)
        self._sort_btn = _small("Sort: name", "Sort the attached tags A to Z, or with the ones on the most photos first.", True)
        self._sort_btn.toggled.connect(lambda on: (self._sort_btn.setText("Sort: count" if on else "Sort: name"), self._rebuild()))
        self._leaf_btn = _small("Leaf only", "Show only the last level of each tag (Family instead of People › Family).", True)
        self._leaf_btn.toggled.connect(lambda _on: self._rebuild())
        head.addWidget(self._sort_btn)
        head.addWidget(self._leaf_btn)
        body.addLayout(head)

        self._attached = QListWidget()
        self._attached.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._attached.setFixedHeight(_LIST_HEIGHT)
        self._attached.itemDoubleClicked.connect(lambda item: self.detach_requested.emit([item.data(_TAG)]))
        self._attached.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._attached.customContextMenuRequested.connect(self._attached_menu)
        self._attached.itemSelectionChanged.connect(self._sync_buttons)
        body.addWidget(self._attached)
        self._detach_btn = _small("Detach", "Take the selected tags off the photo(s) (or double-click one).")
        self._detach_btn.clicked.connect(lambda: self.detach_requested.emit(self._selected_attached()))
        body.addWidget(self._detach_btn)

        title2 = QLabel("DICTIONARY")
        title2.setProperty("role", "subtitle")
        body.addWidget(title2)
        entry = QHBoxLayout()
        entry.setSpacing(THEME.space_sm)
        self._entry = QLineEdit()
        self._entry.setPlaceholderText("filter, or type a tag and press Enter")
        self._entry.setClearButtonEnabled(True)
        self._entry.setToolTip("Filters the dictionary as you type. Enter attaches the best match; if nothing fits, it makes what you typed and attaches it.")
        self._entry.textChanged.connect(lambda _t: self._rebuild())
        self._entry.returnPressed.connect(self._on_enter)
        entry.addWidget(self._entry, 1)
        self._new_btn = _small("New", "Make a tag of exactly what is typed (a / makes a level). It goes on the photo(s) in front of you, if any; otherwise it just joins the dictionary.")
        self._new_btn.clicked.connect(self._on_new)
        entry.addWidget(self._new_btn)
        body.addLayout(entry)

        modes = QHBoxLayout()
        modes.setSpacing(THEME.space_sm)
        self._tree_btn = _small("List", "Show the dictionary as a flat list, or as a tree (click to switch).", True)
        self._tree_btn.toggled.connect(lambda on: (self._tree_btn.setText("Tree" if on else "List"), self._rebuild()))
        self._suggest_btn = _small("Suggest", "While the box is empty, list the tags that usually go with the ones attached (worked out from your other photos).", True)
        self._suggest_btn.toggled.connect(lambda _on: self._rebuild())
        modes.addWidget(self._tree_btn)
        modes.addWidget(self._suggest_btn)
        modes.addStretch(1)
        body.addLayout(modes)

        self._stack = QStackedWidget()
        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.itemDoubleClicked.connect(lambda item: self.attach_requested.emit([item.data(_TAG)]))
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(lambda pos: self._dictionary_menu(self._list, pos))
        self._list.itemSelectionChanged.connect(self._sync_buttons)
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(14)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._tree.itemDoubleClicked.connect(self._on_tree_double_click)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(lambda pos: self._dictionary_menu(self._tree, pos))
        self._tree.itemSelectionChanged.connect(self._sync_buttons)
        self._tree.itemExpanded.connect(lambda item: self._expanded.add(item.data(0, _TAG)))
        self._tree.itemCollapsed.connect(lambda item: self._expanded.discard(item.data(0, _TAG)))
        self._stack.addWidget(self._list)
        self._stack.addWidget(self._tree)
        self._stack.setFixedHeight(_DICT_HEIGHT)
        body.addWidget(self._stack)

        buttons = QHBoxLayout()
        buttons.setSpacing(THEME.space_sm)
        self._attach_btn = _small("Attach", "Put the selected dictionary tags on the photo(s) in front of you (or double-click one).")
        self._attach_btn.clicked.connect(lambda: self.attach_requested.emit(self._selected_dictionary()))
        self._import_btn = _small("Import...", "Add the keywords of a Lightroom keyword file to the dictionary (they are not put on any photo).")
        self._import_btn.clicked.connect(self._import)
        self._export_btn = _small("Export...", "Save every tag as a Lightroom keyword file.")
        self._export_btn.clicked.connect(self._export)
        for b in (self._attach_btn, self._import_btn, self._export_btn):
            buttons.addWidget(b)
        body.addLayout(buttons)
        self._sync_buttons()

    # ---- data in ----
    def set_tag_lists_provider(self, provider) -> None:
        """`provider()` gives every tagged photo's tag list - asked for only when Suggest is on."""
        self._tag_lists = provider

    def set_data(self, paths: list[str], per_path: dict[str, list[str]], dictionary: dict[str, int]) -> None:
        """Show these photos' tags against this dictionary."""
        self._paths, self._per_path, self._dictionary = list(paths), dict(per_path), dict(dictionary)
        self._rebuild()

    def paths(self) -> list[str]:
        return list(self._paths)

    # ---- building the lists ----
    def _attached_counts(self) -> dict[str, int]:
        return G.attached_counts(self._per_path, self._paths)

    def _rebuild(self) -> None:
        total = len(self._paths)
        self._hint.setText(
            "No photo open: pick one to see and change its tags." if not total
            else "Tags for this photo." if total == 1 else f"Tags for the {total} selected photos (how many have each is in brackets)."
        )
        self._rebuild_attached()
        query = self._entry.text()
        typed = bool(T.clean_tag(query))
        attached = self._attached_counts()
        if self._tree_btn.isChecked():
            self._stack.setCurrentWidget(self._tree)
            self._fill_tree(G.build_tree(self._dictionary, attached, total, query), expand_all=typed)
        else:
            self._stack.setCurrentWidget(self._list)
            if not typed and self._suggest_btn.isChecked():
                names = G.suggestions(set(attached), self._tag_lists(), self._dictionary)
                entries = [G.Entry(t, self._dictionary.get(t, 0), G.mark_for(t, attached, total)) for t in names if t in self._dictionary]
            else:
                entries = G.dictionary_rows(self._dictionary, attached, total, query)
            self._fill_list(entries)
        self._sync_buttons()

    def _rebuild_attached(self) -> None:
        selected = set(self._selected_attached())
        self._attached.blockSignals(True)
        self._attached.clear()
        for row in G.attached_rows(self._per_path, self._paths, self._sort_btn.isChecked(), self._leaf_btn.isChecked()):
            item = QListWidgetItem(row.label)
            item.setData(_TAG, row.tag)
            item.setToolTip(T.display(row.tag))
            self._attached.addItem(item)
            item.setSelected(row.tag in selected)
        self._attached.blockSignals(False)

    def _fill_list(self, entries: list) -> None:
        keep = set(self._selected_dictionary())
        self._list.blockSignals(True)
        self._list.clear()
        for e in entries:
            item = QListWidgetItem(f"{G.MARKS[e.mark]}{T.display(e.tag)}   ({e.count})")
            item.setData(_TAG, e.tag)
            item.setToolTip(e.tag)
            self._list.addItem(item)
            item.setSelected(e.tag in keep)
        self._list.blockSignals(False)

    def _fill_tree(self, nodes: list, expand_all: bool) -> None:
        keep = set(self._selected_dictionary())
        self._tree.blockSignals(True)
        self._tree.clear()

        def add(node, parent):
            label = f"{G.MARKS[node.mark]}{node.name}" + (f"   ({node.count})" if node.defined else "")
            item = QTreeWidgetItem([label]) if parent is None else QTreeWidgetItem(parent, [label])
            if parent is None:
                self._tree.addTopLevelItem(item)
            item.setData(0, _TAG, node.path)
            item.setData(0, _DEFINED, node.defined)
            item.setToolTip(0, node.path + ("" if node.defined else "  (only a level other tags are inside)"))
            if not node.defined:
                font = item.font(0)
                font.setItalic(True)
                item.setFont(0, font)
            for child in node.children:
                add(child, item)
            if node.path in keep:
                item.setSelected(True)
            return item

        for node in nodes:
            add(node, None)
        if expand_all:
            self._tree.expandAll()
        else:
            self._restore_expansion()
        self._tree.blockSignals(False)

    def _restore_expansion(self) -> None:
        def walk(item):
            if item.data(0, _TAG) in self._expanded:
                item.setExpanded(True)
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(self._tree.topLevelItemCount()):
            walk(self._tree.topLevelItem(i))

    # ---- selection ----
    def _selected_attached(self) -> list[str]:
        return [i.data(_TAG) for i in self._attached.selectedItems()]

    def _selected_dictionary(self) -> list[str]:
        if self._stack.currentWidget() is self._tree:
            return [i.data(0, _TAG) for i in self._tree.selectedItems() if i.data(0, _DEFINED)]
        return [i.data(_TAG) for i in self._list.selectedItems()]

    def _sync_buttons(self) -> None:
        have = bool(self._paths)
        self._detach_btn.setEnabled(have and bool(self._selected_attached()))
        self._attach_btn.setEnabled(have and bool(self._selected_dictionary()))

    # ---- entry box ----
    def _on_enter(self) -> None:
        typed = T.clean_tag(self._entry.text())
        if not typed:
            return
        exact = next((t for t in self._dictionary if t.casefold() == typed.casefold()), None)
        best = exact or next(iter(T.rank(typed, self._dictionary, usage=self._dictionary, limit=1)), None)
        self._entry.clear()
        if best is not None:
            if self._paths:
                self.attach_requested.emit([best])
        else:
            self.create_requested.emit(typed, bool(self._paths))

    def _on_new(self) -> None:
        typed = T.clean_tag(self._entry.text())
        if typed:
            self._entry.clear()
            self.create_requested.emit(typed, bool(self._paths))

    def focus_entry(self) -> None:
        self._entry.setFocus()
        self._entry.selectAll()

    def find_tag(self, tag: str) -> None:
        """Put a tag in the box so the dictionary shows where it is."""
        self.set_expanded(True)
        self._entry.setText(tag)
        self.focus_entry()

    # ---- double-click in the tree ----
    def _on_tree_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        if item.data(0, _DEFINED):
            self.attach_requested.emit([item.data(0, _TAG)])
        else:
            item.setExpanded(not item.isExpanded())

    # ---- right-click menus ----
    def _attached_menu(self, pos) -> None:
        item = self._attached.itemAt(pos)
        if item is None:
            return
        tag = item.data(_TAG)
        menu = QMenu(self._attached)
        detach = menu.addAction("Detach")
        find = menu.addAction("Find in the dictionary")
        collection = menu.addAction("Show photos with this tag")
        copy = menu.addAction("Copy to clipboard")
        chosen = menu.exec(self._attached.viewport().mapToGlobal(pos))
        if chosen == detach:
            self.detach_requested.emit(self._selected_attached() or [tag])
        elif chosen == find:
            self.find_tag(tag)
        elif chosen == collection:
            self.collection_requested.emit(tag)
        elif chosen == copy:
            QApplication.clipboard().setText(tag)

    def _dictionary_menu(self, view, pos) -> None:
        if view is self._tree:
            item = view.itemAt(pos)
            if item is None:
                return
            tag, defined = item.data(0, _TAG), bool(item.data(0, _DEFINED))
            viewport = view.viewport()
        else:
            item = view.itemAt(pos)
            if item is None:
                return
            tag, defined, viewport = item.data(_TAG), True, view.viewport()
        attached = self._attached_counts()
        on = any(k.casefold() == tag.casefold() for k in attached)
        menu = QMenu(view)
        attach = menu.addAction("Attach tag")
        attach.setEnabled(defined and bool(self._paths))
        detach = menu.addAction("Detach tag")
        detach.setEnabled(defined and on)
        menu.addSeparator()
        edit = menu.addAction("Edit name...")
        path = menu.addAction("Change path...")
        menu.addSeparator()
        delete = menu.addAction("Delete tag")
        delete.setEnabled(defined)
        delete_node = menu.addAction("Delete node (and everything inside)")
        menu.addSeparator()
        collection = menu.addAction("Show photos with this tag")
        copy = menu.addAction("Copy to clipboard")
        chosen = menu.exec(viewport.mapToGlobal(pos))
        if chosen == attach:
            self.attach_requested.emit(self._selected_dictionary() or [tag])
        elif chosen == detach:
            self.detach_requested.emit([tag])
        elif chosen == edit:
            self._edit_name(tag)
        elif chosen == path:
            self._change_path(tag)
        elif chosen == delete:
            self._delete(tag, False)
        elif chosen == delete_node:
            self._delete(tag, True)
        elif chosen == collection:
            self.collection_requested.emit(tag)
        elif chosen == copy:
            QApplication.clipboard().setText(tag)

    def _edit_name(self, tag: str) -> None:
        text, ok = QInputDialog.getText(self, "Edit tag name", "The last level's new name:", text=T.leaf(tag))
        name = T.clean_tag(text.replace("/", " ")) if ok else ""
        if name:
            parent = T.parent(tag)
            self.rename_requested.emit(tag, f"{parent}/{name}" if parent else name)

    def _change_path(self, tag: str) -> None:
        inside = sum(1 for t in self._dictionary if T.is_inside(t, tag) and t.casefold() != tag.casefold())
        extra = f"\n\nThe {inside} tag{'s' if inside != 1 else ''} inside it will move with it." if inside else ""
        text, ok = QInputDialog.getText(self, "Change path", f"The whole new path for {T.display(tag)} (levels separated by /):{extra}", text=tag)
        new = T.clean_tag(text) if ok else ""
        if new and new != tag:
            self.rename_requested.emit(tag, new)

    def _delete(self, tag: str, with_children: bool) -> None:
        inside = [t for t in self._dictionary if T.is_inside(t, tag) and t.casefold() != tag.casefold()]
        if with_children and inside:
            text = f"Delete {T.display(tag)} and the {len(inside)} tag{'s' if len(inside) != 1 else ''} inside it?\n\nThey are taken off every photo that has them."
        else:
            n = self._dictionary.get(tag, 0)
            text = f"Delete the tag {T.display(tag)}?\n\nIt is taken off the {n} photo{'s' if n != 1 else ''} that {'have' if n != 1 else 'has'} it."
        box = QMessageBox(QMessageBox.Icon.Warning, "Delete tag", text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() == QMessageBox.StandardButton.Yes:
            self.delete_requested.emit(tag, with_children)

    # ---- keyword files ----
    def _import(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "Import tags", "", "Keyword files (*.txt);;All files (*)")
        if path:
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    self.import_requested.emit(f.read())
            except OSError as e:
                QMessageBox.warning(self, "Import tags", f"That file could not be read.\n\n{e}")

    def _export(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(self, "Export tags", "EFAS tags.txt", "Keyword files (*.txt)")
        if path:
            self.export_requested.emit(path)

    def sizeHint(self) -> QSize:
        return super().sizeHint()
