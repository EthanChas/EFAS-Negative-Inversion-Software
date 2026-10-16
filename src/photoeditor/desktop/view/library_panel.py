import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QWidget

from ..settings_store import qsettings
from ...theme.tokens import THEME
from .bevel_widgets import CaptionButton
from .collapsible_panel import CollapsiblePanel
from ...features.browse.logic import DEFAULT_SORT, SORT_MODES
from .folder_tree import ROOTS_SETTINGS_KEY, SORT_SETTINGS_KEY, FolderTree

_TREE_MAX_HEIGHT = 260


class LibraryPanel(CollapsiblePanel):
    """A constant, always-shown section at the top of the left column
    (above Masking) - a NegPy-style library folder tree (see FolderTree)
    embedded directly in the main editor, not just in the separate Import
    window, so jumping to a known roll doesn't need opening another window
    first. Shares its root-folder list and on-disk settings key with
    ImportWindow (ROOTS_SETTINGS_KEY), so adding a root in either place
    shows up in both.

    Clicking a folder here opens/raises the Import window already browsing
    it (see AppWindow._on_library_folder_selected) rather than duplicating
    the thumbnail grid in this already-narrow sidebar column."""

    folder_selected = pyqtSignal(str)
    folder_double_clicked = pyqtSignal(str)
    root_removed = pyqtSignal(str)
    root_added = pyqtSignal(str)
    sort_changed = pyqtSignal(str)
    hotstack_requested = pyqtSignal(str, bool)

    def __init__(self, parent: QWidget | None = None, workbench: bool = False):
        super().__init__(
            "Library",
            help_text=(
                "A folder tree of your added root folders, like a film library - add one with the + button. "
                + ("Click any folder (or subfolder) to show only the photos in it; the reset button in this header clears the choice and shows every photo. "
                   if workbench else "Click any folder (or subfolder) to browse its photos in the Import window. ")
                + "Sort the folders with the Sort box: by name, by date (when the newest photo in the folder was last changed), by number of photos, or as you added them. "
                + "Right-click a top-level folder to remove it from the list (your photos and edits are not touched). Right-click any folder to mark it as a Hotstack (its icon and name turn red): "
                + "it is watched, and each photo that lands in it is shown as it arrives."
            ),
            collapsible=False,
            parent=parent,
        )
        self.setMinimumWidth(220)
        body = self.body()
        body.setSpacing(THEME.space_sm)

        self._settings = qsettings()

        toolbar = QHBoxLayout()
        toolbar.setSpacing(THEME.space_sm)
        sort_label = QLabel("Sort")
        sort_label.setProperty("role", "hint")
        toolbar.addWidget(sort_label)
        self._sort = QComboBox()
        for key, label in SORT_MODES:
            self._sort.addItem(label, key)
        self._sort.setToolTip("Order the folders: by name, date (newest photo in the folder), number of photos, or as added")
        self._sort.setMinimumContentsLength(11)
        toolbar.addWidget(self._sort)
        toolbar.addStretch(1)
        add_btn = CaptionButton("add")
        add_btn.setToolTip("Add a root folder")
        add_btn.clicked.connect(self._add_root_folder)
        toolbar.addWidget(add_btn)
        refresh_btn = CaptionButton("refresh")
        refresh_btn.setToolTip("Refresh folder counts")
        refresh_btn.clicked.connect(self._tree_refresh)
        toolbar.addWidget(refresh_btn)
        body.addLayout(toolbar)

        self._tree = FolderTree(removable=True)
        self._tree.setMaximumHeight(_TREE_MAX_HEIGHT)
        self._tree.folder_selected.connect(self.folder_selected)
        self._tree.folder_double_clicked.connect(self.folder_double_clicked)
        self._tree.remove_root_requested.connect(self._remove_root_folder)
        self._tree.hotstack_requested.connect(self.hotstack_requested)
        body.addWidget(self._tree)

        saved = str(self._settings.value(SORT_SETTINGS_KEY, DEFAULT_SORT, type=str))
        self._sort.setCurrentIndex(max(0, self._sort.findData(saved)))
        self._tree.set_sort(self._sort.currentData())
        self._sort.currentIndexChanged.connect(self._on_sort_picked)
        self._tree.set_roots(self._settings.value(ROOTS_SETTINGS_KEY, [], type=list))

    def _on_sort_picked(self) -> None:
        mode = self._sort.currentData()
        self._settings.setValue(SORT_SETTINGS_KEY, mode)
        self._settings.sync()
        self._tree.set_sort(mode)
        self.sort_changed.emit(mode)

    def apply_sort(self, mode: str) -> None:
        """The other Library panel's choice (the editor's and the Workbench's list the same folders the same way)."""
        self._sort.blockSignals(True)
        self._sort.setCurrentIndex(max(0, self._sort.findData(mode)))
        self._sort.blockSignals(False)
        self._tree.set_sort(mode)

    def sort_mode(self) -> str:
        return self._tree.sort_mode

    def _add_root_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add a root folder")
        if not folder:
            return
        self._tree.add_root(folder)
        self._settings.setValue(ROOTS_SETTINGS_KEY, self._tree.roots())
        self._settings.sync()
        self.root_added.emit(folder)
        self.folder_selected.emit(folder)

    def _remove_root_folder(self, folder: str) -> None:
        name = os.path.basename(folder.rstrip("\\/")) or folder
        box = QMessageBox(QMessageBox.Icon.Question, "Remove from Library", f"Remove \"{name}\" from the Library?", parent=self)
        box.setInformativeText("Only the entry in this list goes. The folder, its photos and your edits stay exactly where they are, "
                               "and you can add the folder back at any time.")
        remove = box.addButton("Remove", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not remove:
            return
        if self._tree.remove_root(folder):
            self._settings.setValue(ROOTS_SETTINGS_KEY, self._tree.roots())
            self._settings.sync()
            self.root_removed.emit(folder)

    def set_hotstack(self, folders: list[str]) -> None:
        """The folders marked hotstack are drawn red."""
        self._tree.set_hotstack(folders)

    def _tree_refresh(self) -> None:
        self._tree.refresh()

    def clear_selection(self) -> None:
        """No folder selected (nothing is emitted)."""
        self._tree.clearSelection()
        self._tree.setCurrentItem(None)

    def selected_folder(self) -> str:
        item = self._tree.currentItem()
        return (item.data(0, Qt.ItemDataRole.UserRole) or "") if item is not None and item.isSelected() else ""

    def reveal(self, folder: str) -> None:
        """Show where the open roll is: the tree opens down to its folder and highlights it."""
        self._tree.reveal(folder)

    def reload_roots(self) -> None:
        """Picks up roots added from the other root-list editor (the Import window, the other Library panel) since this panel was built."""
        self._settings.sync()
        self._tree.set_roots(self._settings.value(ROOTS_SETTINGS_KEY, [], type=list))
