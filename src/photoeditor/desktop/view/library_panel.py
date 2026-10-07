from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QWidget

from ..settings_store import qsettings
from ...theme.tokens import THEME
from .bevel_widgets import CaptionButton
from .collapsible_panel import CollapsiblePanel
from .folder_tree import ROOTS_SETTINGS_KEY, FolderTree

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

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Library",
            help_text=(
                "A folder tree of your added root folders, like a film "
                "library - add one with the + button, click any folder "
                "(or subfolder) to browse its photos in the Import window."
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

        self._tree = FolderTree()
        self._tree.setMaximumHeight(_TREE_MAX_HEIGHT)
        self._tree.folder_selected.connect(self.folder_selected)
        self._tree.folder_double_clicked.connect(self.folder_double_clicked)
        body.addWidget(self._tree)

        self._tree.set_roots(self._settings.value(ROOTS_SETTINGS_KEY, [], type=list))

    def _add_root_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add a root folder")
        if not folder:
            return
        self._tree.add_root(folder)
        self._settings.setValue(ROOTS_SETTINGS_KEY, self._tree.roots())
        self.folder_selected.emit(folder)

    def _tree_refresh(self) -> None:
        self._tree.refresh()

    def reveal(self, folder: str) -> None:
        """Show where the open roll is: the tree opens down to its folder and highlights it."""
        self._tree.reveal(folder)

    def reload_roots(self) -> None:
        """Picks up roots added from the other root-list editor (the
        Import window) since this panel was built."""
        self._tree.set_roots(self._settings.value(ROOTS_SETTINGS_KEY, [], type=list))
