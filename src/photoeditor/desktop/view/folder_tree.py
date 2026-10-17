import os

from datetime import datetime

from PyQt6.QtCore import QPoint, QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QDesktopServices, QIcon
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QMenu, QTreeWidget, QTreeWidgetItem

from ...features.browse.logic import DEFAULT_SORT, SORT_MODES, folder_stats, list_subfolders, sort_fact
from ...theme.tokens import THEME
from . import panel_icons

_PLACEHOLDER = "__loading__"
ROOTS_SETTINGS_KEY = "library/roots"
HIDDEN_SETTINGS_KEY = "library/hidden"   # the folders taken off the list that are not roots (right-click > Remove from Library)
SORT_SETTINGS_KEY = "library/sort"
_ROLE_NAME, _ROLE_DATE, _ROLE_COUNT, _ROLE_ORDER, _ROLE_LABEL = (Qt.ItemDataRole.UserRole + n for n in (1, 2, 3, 4, 5))


class _FolderItem(QTreeWidgetItem):
    """A folder row that knows how the tree is being sorted (its photos, its newest photo's date, its name, where it was added)."""

    def __lt__(self, other: "QTreeWidgetItem") -> bool:
        tree = self.treeWidget()
        fact = sort_fact(getattr(tree, "sort_mode", DEFAULT_SORT))[0]
        return _key(self, fact) < _key(other, fact)


def _key(item: QTreeWidgetItem, fact: str):
    """What a row is compared on; rows without folder data (the "Loading..." line) go last, ties by name."""
    name = item.data(0, _ROLE_NAME) or ""
    if not name:
        return (1, 0, "")
    value = {"order": item.data(0, _ROLE_ORDER), "name": name, "date": item.data(0, _ROLE_DATE), "count": item.data(0, _ROLE_COUNT)}[fact]
    if value is None:
        value = 10 ** 9 if fact == "order" else 0
    return (0, value, name)


class FolderTree(QTreeWidget):
    """A lazy folder browser, mirroring NegPy's own LibraryTree: each root
    folder you add appears as a top-level node; subfolders are only read
    (and their own image/folder counts computed) the first time a node is
    expanded, not walked upfront - so adding a root with a huge nested
    structure costs nothing until you actually open it. Single-clicking
    any node (root or nested) emits folder_selected with that folder's
    path, same as clicking a library root in NegPy's own tree. A second,
    muted, right-aligned column shows a folder/photo count the same way
    NegPy's own tree does."""

    folder_selected = pyqtSignal(str)
    folder_double_clicked = pyqtSignal(str)
    remove_root_requested = pyqtSignal(str)
    hotstack_requested = pyqtSignal(str, bool)   # a folder was marked (True) or unmarked (False) as a hotstack
    new_folder_requested = pyqtSignal(str)       # make a folder inside this one
    rename_folder_requested = pyqtSignal(str)
    move_folder_requested = pyqtSignal(str, str)   # (folder, the folder to move it into - "" when it is to be asked: the menu)
    delete_folder_requested = pyqtSignal(str)
    hide_folder_requested = pyqtSignal(str)      # take a folder that is not a root off the list
    restore_hidden_requested = pyqtSignal()      # bring back the folders taken off the list

    def __init__(self, parent=None, removable: bool = False):
        super().__init__(parent)
        self._removable = removable
        self._hot: set[str] = set()   # the folders marked hotstack (see set_hotstack)
        self._hidden: list[str] = []  # the folders taken off the list (see set_hidden)
        self._hidden_keys: set[str] = set()
        self.sort_mode = DEFAULT_SORT
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.setHeaderHidden(True)
        self.setColumnCount(2)
        self.header().setStretchLastSection(False)
        # the name takes what room there is (and is cut short with ... when it is too long, the tip has the whole path); the count or date beside it is always shown whole
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setIconSize(QSize(16, 16))
        self.itemExpanded.connect(self._on_expanded)
        self.itemCollapsed.connect(lambda item: item.setIcon(0, self._folder_icon(False, self._is_hot(item))))
        self.itemClicked.connect(self._on_clicked)
        self.itemDoubleClicked.connect(self._on_double_clicked)
        if removable:   # a folder dragged onto another is moved into it (after asking); the tree never reorders its own rows
            self.setDragEnabled(True)
            self.setAcceptDrops(True)
            self.setDropIndicatorShown(True)
            self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

    def _folder_icon(self, opened: bool, hot: bool = False) -> QIcon:
        """The folder icon beside a name (a Lucide file from assets/icon): shut, or open while the folder is expanded; red for a hotstack."""
        return QIcon(panel_icons.pixmap("folder-open" if opened else "folder", 16, THEME.status_critical if hot else THEME.text_secondary))

    def _is_hot(self, item: QTreeWidgetItem) -> bool:
        folder = item.data(0, Qt.ItemDataRole.UserRole)
        return bool(folder) and folder != _PLACEHOLDER and os.path.normcase(os.path.abspath(folder)) in self._hot

    def _paint(self, item: QTreeWidgetItem) -> None:
        """A hotstack folder's icon and text are red; any other folder is drawn as usual."""
        hot = self._is_hot(item)
        item.setIcon(0, self._folder_icon(item.isExpanded(), hot))
        item.setForeground(0, QColor(THEME.status_critical) if hot else QBrush())
        item.setForeground(1, QColor(THEME.status_critical) if hot else QColor(THEME.text_muted))

    def _paint_all(self, parent: QTreeWidgetItem) -> None:
        for i in range(parent.childCount()):
            item = parent.child(i)
            if item.data(0, Qt.ItemDataRole.UserRole) != _PLACEHOLDER:
                self._paint(item)
            self._paint_all(item)

    def set_hotstack(self, folders: list[str]) -> None:
        """The folders marked hotstack: their icon and name turn red here, in the rows that are shown now and in the ones that are made later."""
        self._hot = {os.path.normcase(os.path.abspath(f)) for f in folders if f}
        self._paint_all(self.invisibleRootItem())

    def is_hotstack(self, folder: str) -> bool:
        return os.path.normcase(os.path.abspath(folder)) in self._hot

    def set_sort(self, mode: str) -> None:
        """List the folders (the roots, and the subfolders under each) by name, date, number of photos, or as they were added."""
        self.sort_mode = mode if mode in dict(SORT_MODES) else DEFAULT_SORT
        self._apply_sort()

    def _apply_sort(self) -> None:
        descending = sort_fact(self.sort_mode)[1]
        self._relabel(self.invisibleRootItem())
        self.sortItems(0, Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder)
        self._resize_columns()

    def _relabel(self, parent: QTreeWidgetItem) -> None:
        """The muted right-hand column shows the fact the tree is sorted on: the date in a date sort, otherwise the photo count."""
        by_date = sort_fact(self.sort_mode)[0] == "date"
        for i in range(parent.childCount()):
            item = parent.child(i)
            if item.data(0, _ROLE_NAME):
                item.setText(1, _date_label(item.data(0, _ROLE_DATE)) if by_date and item.data(0, _ROLE_DATE) else item.data(0, _ROLE_LABEL))
            self._relabel(item)

    def set_hidden(self, folders: list[str]) -> None:
        """The folders taken off the list (right-click > Remove from Library on a folder that is not a root): they and everything in them are left out of the rows made from now on."""
        self._hidden = [f for f in folders if f]
        self._hidden_keys = {os.path.normcase(os.path.abspath(f)) for f in self._hidden}

    def hidden_folders(self) -> list[str]:
        return list(self._hidden)

    def _subfolders(self, folder: str) -> list[str]:
        """The folders inside `folder` that the list shows."""
        subs = list_subfolders(folder)
        if self._hidden_keys:
            subs = [s for s in subs if os.path.normcase(os.path.abspath(s)) not in self._hidden_keys]
        return subs

    def set_roots(self, roots: list[str]) -> None:
        self.clear()
        for n, root in enumerate(roots):
            self.addTopLevelItem(self._make_item(root, order=n))
        self._apply_sort()

    def expanded_folders(self) -> list[str]:
        """The folders that are opened now (so a list rebuilt after a change can open them again)."""
        out: list[str] = []

        def walk(parent: QTreeWidgetItem) -> None:
            for i in range(parent.childCount()):
                item = parent.child(i)
                folder = item.data(0, Qt.ItemDataRole.UserRole)
                if folder and folder != _PLACEHOLDER and item.isExpanded():
                    out.append(folder)
                    walk(item)

        walk(self.invisibleRootItem())
        return out

    def restore_expanded(self, folders: list[str]) -> None:
        """Open these folders again (each from the top: a folder opens only when the one it is in is open)."""
        wanted = {os.path.normcase(os.path.abspath(f)) for f in folders if f}

        def walk(parent: QTreeWidgetItem) -> None:
            for i in range(parent.childCount()):
                item = parent.child(i)
                folder = item.data(0, Qt.ItemDataRole.UserRole)
                if folder and folder != _PLACEHOLDER and os.path.normcase(os.path.abspath(folder)) in wanted:
                    self.expandItem(item)
                    walk(item)

        walk(self.invisibleRootItem())

    def current_folder(self) -> str:
        item = self.currentItem()
        folder = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else ""
        return folder if folder and folder != _PLACEHOLDER else ""

    def add_root(self, folder: str) -> None:
        for i in range(self.topLevelItemCount()):
            if self.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == folder:
                return
        self.addTopLevelItem(self._make_item(folder, order=self.topLevelItemCount()))
        self._apply_sort()

    def remove_root(self, folder: str) -> bool:
        """Take a top-level folder out of the tree (nothing on disk is touched)."""
        for i in range(self.topLevelItemCount()):
            if self.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == folder:
                self.takeTopLevelItem(i)
                self._resize_columns()
                return True
        return False

    def build_context_menu(self, item: QTreeWidgetItem | None) -> QMenu | None:
        folder = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        if not folder or folder == _PLACEHOLDER:
            if self._removable and self._hidden:   # a click on empty space: the one thing there is to do is bring folders back
                menu = QMenu(self)
                self._add_restore(menu)
                return menu
            return None
        menu = QMenu(self)
        hot = self.is_hotstack(folder)
        mark = menu.addAction("Remove Hotstack Mark" if hot else "Mark as Hotstack")
        mark.setToolTip("A hotstack folder is the one your photos land in (from Canon's EOS Utility, say): it is watched, and each photo that arrives in it is shown as it arrives. Its icon and name turn red.")
        mark.triggered.connect(lambda _c=False: self.hotstack_requested.emit(folder, not hot))
        menu.addSeparator()
        if self._removable:
            new = menu.addAction("New Folder...")
            new.setToolTip("Makes a new, empty folder on your disk inside this one.")
            new.triggered.connect(lambda _c=False: self.new_folder_requested.emit(folder))
            rename = menu.addAction("Rename Folder...")
            rename.setToolTip("Gives the folder on your disk another name. The edits, ratings, tags and versions of its photos go with it.")
            rename.triggered.connect(lambda _c=False: self.rename_folder_requested.emit(folder))
            move = menu.addAction("Move Folder to...")
            move.setToolTip("Moves the folder, with everything in it, into another folder on the same drive. You can also drag it onto that folder. The edits, ratings, tags and versions of its photos go with it.")
            move.triggered.connect(lambda _c=False: self.move_folder_requested.emit(folder, ""))
            menu.addSeparator()
        menu.addAction("Show in File Explorer").triggered.connect(lambda _c=False: QDesktopServices.openUrl(QUrl.fromLocalFile(folder)))
        if self._removable:
            menu.addSeparator()
            remove = menu.addAction("Remove from Library")
            if item.parent() is None:
                remove.setToolTip("Takes the folder off this list. Your photos and edits are not touched.")
                remove.triggered.connect(lambda _c=False: self.remove_root_requested.emit(folder))
            else:
                remove.setToolTip("Takes the folder, and the folders in it, off this list and out of the Workbench. Your photos and edits are not touched, and right-click > Bring Back Removed Folders shows them again.")
                remove.triggered.connect(lambda _c=False: self.hide_folder_requested.emit(folder))
            delete = menu.addAction("Delete Folder...")
            delete.setToolTip("Moves the folder, and everything in it, to the Recycle Bin. You are asked first.")
            delete.triggered.connect(lambda _c=False: self.delete_folder_requested.emit(folder))
            if self._hidden:
                self._add_restore(menu)
        return menu

    def _add_restore(self, menu: QMenu) -> None:
        n = len(self._hidden)
        back = menu.addAction(f"Bring Back Removed Folders ({n})")
        back.setToolTip("Shows the folders you took off the list again.")
        back.triggered.connect(lambda _c=False: self.restore_hidden_requested.emit())

    def dropEvent(self, event) -> None:
        """A drop does not move the row here: it asks (move_folder_requested) for the dragged folder to be moved into the folder it was dropped on, and the tree is rebuilt from the disk."""
        source = self.currentItem()
        target = self.itemAt(event.position().toPoint())
        event.ignore()
        if not self._removable or source is None or target is None or source is target:
            return
        src, dst = source.data(0, Qt.ItemDataRole.UserRole), target.data(0, Qt.ItemDataRole.UserRole)
        if src and dst and _PLACEHOLDER not in (src, dst):
            self.move_folder_requested.emit(src, dst)

    def _on_context_menu(self, pos: QPoint) -> None:
        menu = self.build_context_menu(self.itemAt(pos))
        if menu is not None:
            menu.exec(self.viewport().mapToGlobal(pos))

    def roots(self) -> list[str]:
        return [self.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) for i in range(self.topLevelItemCount())]

    def refresh(self, opened: list[str] | None = None, current: str | None = None) -> None:
        """Re-scans every root from scratch (fresh counts; there's no cached index to go stale, see list_subfolders/folder_counts), so this is just re-running the same cheap
        shallow scans, not a real "reindex". The folders that were open stay open and the chosen one stays chosen - or the ones named in `opened` and `current`, when a change
        (a folder renamed, a new one made) means those are not the same now."""
        opened = self.expanded_folders() if opened is None else opened
        current = self.current_folder() if current is None else current
        self.set_roots(self.roots())
        self.restore_expanded(opened)
        if current:
            self.reveal(current)

    def _resize_columns(self) -> None:
        """(The columns size themselves now: the name stretches, the count or date fits its text.)"""

    def _make_item(self, folder: str, order: int | None = None) -> QTreeWidgetItem:
        name = os.path.basename(folder.rstrip(os.sep)) or folder
        images, subfolders, newest = folder_stats(folder)
        if self._hidden_keys and subfolders:
            subfolders = len(self._subfolders(folder))
        label = _count_label(images, subfolders)
        item = _FolderItem([name, label])
        item.setData(0, Qt.ItemDataRole.UserRole, folder)
        item.setIcon(0, self._folder_icon(False))
        item.setData(0, _ROLE_NAME, name.lower())
        item.setData(0, _ROLE_DATE, newest)
        item.setData(0, _ROLE_COUNT, images)
        item.setData(0, _ROLE_ORDER, order)
        item.setData(0, _ROLE_LABEL, label)
        item.setToolTip(0, f"{folder}\n{label}" + (f", newest photo {_date_label(newest)}" if newest else ""))
        item.setToolTip(1, item.toolTip(0))
        item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setForeground(1, QColor(THEME.text_muted))
        if sort_fact(self.sort_mode)[0] == "date" and newest:
            item.setText(1, _date_label(newest))
        self._paint(item)
        if subfolders:
            placeholder = QTreeWidgetItem(["Loading..."])
            placeholder.setData(0, Qt.ItemDataRole.UserRole, _PLACEHOLDER)
            item.addChild(placeholder)
        return item

    def reveal(self, folder: str) -> bool:
        """Expand down to folder and highlight it, when it sits under one of the roots (nothing is emitted)."""
        target = os.path.normcase(os.path.abspath(folder))
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            while item is not None:
                here = os.path.normcase(os.path.abspath(item.data(0, Qt.ItemDataRole.UserRole)))
                if here == target:
                    self.setCurrentItem(item)
                    self.scrollToItem(item)
                    return True
                if not target.startswith(here.rstrip(os.sep) + os.sep):
                    break
                self.expandItem(item)
                item = next((item.child(c) for c in range(item.childCount())
                             if item.child(c).data(0, Qt.ItemDataRole.UserRole) not in (None, _PLACEHOLDER)
                             and (target == os.path.normcase(os.path.abspath(item.child(c).data(0, Qt.ItemDataRole.UserRole)))
                                  or target.startswith(os.path.normcase(os.path.abspath(item.child(c).data(0, Qt.ItemDataRole.UserRole))).rstrip(os.sep) + os.sep))), None)
        return False

    def _on_expanded(self, item: QTreeWidgetItem) -> None:
        item.setIcon(0, self._folder_icon(True, self._is_hot(item)))
        if item.childCount() != 1 or item.child(0).data(0, Qt.ItemDataRole.UserRole) != _PLACEHOLDER:
            return
        item.takeChildren()
        folder = item.data(0, Qt.ItemDataRole.UserRole)
        for sub in self._subfolders(folder):
            item.addChild(self._make_item(sub))
        descending = sort_fact(self.sort_mode)[1]
        item.sortChildren(0, Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder)
        self._resize_columns()

    def _on_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        folder = item.data(0, Qt.ItemDataRole.UserRole)
        if folder and folder != _PLACEHOLDER:
            self.folder_selected.emit(folder)

    def _on_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        folder = item.data(0, Qt.ItemDataRole.UserRole)
        if folder and folder != _PLACEHOLDER:
            self.folder_double_clicked.emit(folder)


def _date_label(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%d %b %Y") if timestamp else ""


def _count_label(images: int, subfolders: int) -> str:
    if images == 0 and subfolders > 0:
        return f"{subfolders} folder" + ("" if subfolders == 1 else "s")
    if images == 0:
        return "empty"
    return f"{images} photo" + ("" if images == 1 else "s")
