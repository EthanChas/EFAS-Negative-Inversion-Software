from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from ..library_worker import ThumbPool
from ..paths import thumbnail_cache_dir

_THUMB = 128


class SlideshowPhotosDialog(QDialog):
    """Which of the slideshow's photos are in it: a grid of every photo the chosen source holds, each with a tick. Untick a photo to leave it out (of the show and of an exported
    video); Select all, Select none and Invert do what they say. The photos' pictures are the Workbench's own thumbnails."""

    def __init__(self, items: list[tuple[str, str]], included: set[str], parent: QWidget | None = None, pool: ThumbPool | None = None):
        super().__init__(parent)
        self.setWindowTitle("Choose the Slideshow's Photos")
        self.resize(780, 560)
        self._pool = pool or ThumbPool(thumbnail_cache_dir(), keep=1500, parent=self)
        self._owns_pool = pool is None
        self._rows: dict[str, QListWidgetItem] = {}

        layout = QVBoxLayout(self)
        hint = QLabel("Tick the photos to show. A photo that is unticked is left out of the slideshow and of the video; nothing is deleted or changed.")
        hint.setWordWrap(True)
        hint.setProperty("role", "hint")
        layout.addWidget(hint)
        self._list = QListWidget()
        self._list.setViewMode(QListView.ViewMode.IconMode)
        self._list.setResizeMode(QListView.ResizeMode.Adjust)
        self._list.setMovement(QListView.Movement.Static)
        self._list.setIconSize(QSize(_THUMB, _THUMB))
        self._list.setGridSize(QSize(_THUMB + 28, _THUMB + 44))
        self._list.setWordWrap(True)
        self._list.setUniformItemSizes(True)
        self._list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        for path, caption in items:
            item = QListWidgetItem(QIcon(), caption.split("  ·  ")[0])
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if path in included else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(caption)
            item.setSizeHint(QSize(_THUMB + 28, _THUMB + 44))
            self._list.addItem(item)
            self._rows[path] = item
            self._pool.request(path)
        self._list.itemChanged.connect(self._update_count)
        layout.addWidget(self._list, 1)

        row = QHBoxLayout()
        for text, tip, action in (("Select all", "Put every photo in the show", self.select_all), ("Select none", "Leave every photo out", self.select_none),
                                  ("Invert", "Swap which photos are in and which are out", self.invert)):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(action)
            row.addWidget(button)
        self._count = QLabel("")
        row.addWidget(self._count)
        row.addStretch(1)
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        layout.addLayout(row)

        self._pool.thumb_ready.connect(self._on_thumb)
        for path in self._rows:
            self._on_thumb(path)
        self._update_count()

    # ------------------------------------------------------------ the pictures
    def _on_thumb(self, path: str) -> None:
        item = self._rows.get(path)
        pixmap = self._pool.pixmap(path)
        if item is not None and pixmap is not None:
            item.setIcon(QIcon(pixmap))

    # ------------------------------------------------------------ the ticks
    def included(self) -> set[str]:
        return {path for path, item in self._rows.items() if item.checkState() == Qt.CheckState.Checked}

    def _set_all(self, state: Qt.CheckState) -> None:
        self._list.blockSignals(True)
        for item in self._rows.values():
            item.setCheckState(state)
        self._list.blockSignals(False)
        self._update_count()

    def select_all(self) -> None:
        self._set_all(Qt.CheckState.Checked)

    def select_none(self) -> None:
        self._set_all(Qt.CheckState.Unchecked)

    def invert(self) -> None:
        self._list.blockSignals(True)
        for item in self._rows.values():
            item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked)
        self._list.blockSignals(False)
        self._update_count()

    def _update_count(self, _item=None) -> None:
        self._count.setText(f"{len(self.included())} of {len(self._rows)} in the show")

    def done(self, code: int) -> None:
        if self._owns_pool:
            self._pool.shutdown()
        super().done(code)
