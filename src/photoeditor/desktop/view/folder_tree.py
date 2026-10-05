import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem

from ...features.browse.logic import folder_counts, list_subfolders
from ...theme.tokens import THEME

_PLACEHOLDER = "__loading__"  # UserRole marker for an unexpanded node's dummy child
ROOTS_SETTINGS_KEY = "library/roots"  # shared between ImportWindow and the embedded LibraryPanel


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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setColumnCount(2)
        self.header().setStretchLastSection(False)
        self.itemExpanded.connect(self._on_expanded)
        self.itemClicked.connect(self._on_clicked)
        self.itemDoubleClicked.connect(self._on_double_clicked)

    def set_roots(self, roots: list[str]) -> None:
        self.clear()
        for root in roots:
            self.addTopLevelItem(self._make_item(root))
        self._resize_columns()

    def add_root(self, folder: str) -> None:
        for i in range(self.topLevelItemCount()):
            if self.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == folder:
                return  # already a root
        self.addTopLevelItem(self._make_item(folder))
        self._resize_columns()

    def roots(self) -> list[str]:
        return [self.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) for i in range(self.topLevelItemCount())]

    def refresh(self) -> None:
        """Re-scans every root from scratch (fresh counts, expanded nodes
        collapsed back to lazy placeholders) - there's no cached index to
        go stale (see list_subfolders/folder_counts), so this is just
        re-running the same cheap shallow scans, not a real "reindex"."""
        self.set_roots(self.roots())

    def _resize_columns(self) -> None:
        self.resizeColumnToContents(0)

    def _make_item(self, folder: str) -> QTreeWidgetItem:
        name = os.path.basename(folder.rstrip(os.sep)) or folder
        item = QTreeWidgetItem([name, _count_label(*folder_counts(folder))])
        item.setData(0, Qt.ItemDataRole.UserRole, folder)
        item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setForeground(1, QColor(THEME.text_muted))
        if list_subfolders(folder):
            placeholder = QTreeWidgetItem(["Loading..."])
            placeholder.setData(0, Qt.ItemDataRole.UserRole, _PLACEHOLDER)
            item.addChild(placeholder)
        return item

    def reveal(self, folder: str) -> bool:
        """Expand down to folder and highlight it, when it sits under one of the roots (nothing is emitted). False when it does not."""
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
                self.expandItem(item)  # reads the children on first expand
                item = next((item.child(c) for c in range(item.childCount())
                             if item.child(c).data(0, Qt.ItemDataRole.UserRole) not in (None, _PLACEHOLDER)
                             and (target == os.path.normcase(os.path.abspath(item.child(c).data(0, Qt.ItemDataRole.UserRole)))
                                  or target.startswith(os.path.normcase(os.path.abspath(item.child(c).data(0, Qt.ItemDataRole.UserRole))).rstrip(os.sep) + os.sep))), None)
        return False

    def _on_expanded(self, item: QTreeWidgetItem) -> None:
        if item.childCount() != 1 or item.child(0).data(0, Qt.ItemDataRole.UserRole) != _PLACEHOLDER:
            return  # already expanded once, or has no children at all
        item.takeChildren()
        folder = item.data(0, Qt.ItemDataRole.UserRole)
        for sub in list_subfolders(folder):
            item.addChild(self._make_item(sub))
        self._resize_columns()

    def _on_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        folder = item.data(0, Qt.ItemDataRole.UserRole)
        if folder and folder != _PLACEHOLDER:
            self.folder_selected.emit(folder)

    def _on_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        folder = item.data(0, Qt.ItemDataRole.UserRole)
        if folder and folder != _PLACEHOLDER:
            self.folder_double_clicked.emit(folder)


def _count_label(images: int, subfolders: int) -> str:
    # A folder of folders (a library root above the rolls themselves) shows
    # how many folders it holds; a roll - any folder that actually contains
    # images, even alongside subfolders - shows its photo count instead,
    # "empty" at zero rather than "0 photos".
    if images == 0 and subfolders > 0:
        return f"{subfolders} folder" + ("" if subfolders == 1 else "s")
    if images == 0:
        return "empty"
    return f"{images} photo" + ("" if images == 1 else "s")
