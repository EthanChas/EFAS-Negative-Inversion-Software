import os

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from ..settings_store import qsettings
from ...theme.tokens import THEME
from ..controller import AppController
from ..paths import thumbnail_cache_dir
from ..workers import ThumbnailLoader
from .folder_tree import ROOTS_SETTINGS_KEY, FolderTree
from .thumbnail_delegate import ThumbnailDelegate


class ImportWindow(QMainWindow):
    """Opened from File -> Import Images."""

    def __init__(self, main_window, parent: QWidget | None = None):
        super().__init__(parent)
        self._main_window = main_window
        self.setWindowTitle("Import Images")
        self.resize(1100, 700)
        self.setMinimumSize(480, 360)

        self.controller = AppController()
        self.controller.folder_changed.connect(self._on_folder_changed)
        self._loader: ThumbnailLoader | None = None
        self._cache_dir = thumbnail_cache_dir()
        self._settings = qsettings()

        self._build_ui()
        self._tree.set_roots(self._settings.value(ROOTS_SETTINGS_KEY, [], type=list))

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(THEME.space_xl, THEME.space_xl, THEME.space_xl, THEME.space_xl)
        outer.setSpacing(THEME.space_lg)

        title = QLabel("Import Images")
        title.setProperty("role", "title")
        outer.addWidget(title)

        subtitle = QLabel("Add a root folder, then click it (or a subfolder) to browse the photos inside it.")
        subtitle.setProperty("role", "subtitle")
        outer.addWidget(subtitle)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        tree_panel = QWidget()
        tree_col = QVBoxLayout(tree_panel)
        tree_col.setContentsMargins(0, 0, 0, 0)
        tree_col.setSpacing(THEME.space_sm)

        add_root_btn = QPushButton("Add Root Folder...")
        add_root_btn.setObjectName("primaryButton")
        add_root_btn.clicked.connect(self._add_root_folder)
        tree_col.addWidget(add_root_btn)

        self._tree = FolderTree()
        self._tree.folder_selected.connect(self.controller.open_folder)
        tree_col.addWidget(self._tree, 1)

        splitter.addWidget(tree_panel)

        grid_panel = QWidget()
        grid_col = QVBoxLayout(grid_panel)
        grid_col.setContentsMargins(0, 0, 0, 0)
        grid_col.setSpacing(THEME.space_sm)

        folder_row = QHBoxLayout()
        self.l_folder = QLabel("No folder selected")
        self.l_folder.setProperty("role", "path")
        folder_row.addWidget(self.l_folder, 1)

        self.l_status = QLabel("")
        self.l_status.setProperty("role", "hint")
        folder_row.addWidget(self.l_status, 0)
        grid_col.addLayout(folder_row)

        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setIconSize(QSize(140, 140))
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setSpacing(THEME.space_md)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.setItemDelegate(ThumbnailDelegate(self.grid))
        self.grid.itemSelectionChanged.connect(self._on_selection_changed)
        self.grid.itemDoubleClicked.connect(self._on_item_double_clicked)
        grid_col.addWidget(self.grid, 1)

        splitter.addWidget(grid_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 860])

    def _add_root_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add a root folder")
        if not folder:
            return
        self._tree.add_root(folder)
        self._settings.setValue(ROOTS_SETTINGS_KEY, self._tree.roots())
        self.controller.open_folder(folder)

    def _on_folder_changed(self) -> None:
        state = self.controller.state
        self.l_folder.setText(state.folder or "No folder selected")
        self.grid.clear()
        self._update_status()

        if not state.image_paths:
            return

        self._loader = ThumbnailLoader(state.image_paths, self._cache_dir)
        self._loader.thumb_ready.connect(self._add_tile)
        self._loader.finished.connect(self._loader.deleteLater)
        self._loader.start()

    def _add_tile(self, path: str, data: bytes | None) -> None:
        item = QListWidgetItem(os.path.basename(path))
        item.setData(Qt.ItemDataRole.UserRole, path)
        if data:
            pix = QPixmap()
            pix.loadFromData(data)
            item.setIcon(QIcon(pix))
        self.grid.addItem(item)
        self._update_status()

    def _on_selection_changed(self) -> None:
        self._update_status()

    def _update_status(self) -> None:
        total = self.grid.count()
        selected = len(self.grid.selectedItems())
        if total == 0:
            self.l_status.setText("")
        elif selected:
            self.l_status.setText(f"{selected} of {total} selected")
        else:
            self.l_status.setText(f"{total} images")

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        self._main_window.controller.open_file(path)
        self._main_window.show()
        self._main_window.raise_()
        self._main_window.activateWindow()
