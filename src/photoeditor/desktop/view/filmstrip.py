import os

import numpy as np
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QImage, QPixmap, QWheelEvent
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from ...theme.tokens import THEME
from ...features.browse.processor import save_edited_thumbnail
from ..paths import thumbnail_cache_dir
from ..workers import ThumbnailLoader
from .thumbnail_delegate import FLAG_ROLE, RATING_ROLE, ThumbnailDelegate

_THUMB_SIZE = 90
_STRIP_HEIGHT = 110

# (mode key, label) - what the strip shows. "unedited" means nothing was changed on the photo (merely opening one doesn't count).
FILTERS = (
    ("all", "All photos"),
    ("keepers", "Keepers"),
    ("not_rejected", "Not rejected"),
    ("rejected", "Rejected"),
    ("unedited", "Unedited"),
    ("rated", "Rated (1+ stars)"),
)


class _FilmstripList(QListWidget):
    """A QListWidget whose wheel always scrolls its horizontal scrollbar -
    without this, a plain mouse wheel scrolls the (disabled, so invisible
    but still logically present) vertical axis instead of sliding along the
    strip, the same reasoning _ZoomScrollArea repurposes the wheel for in
    image_view.py."""

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y() or event.angleDelta().x()
        hbar = self.horizontalScrollBar()
        hbar.setValue(hbar.value() - delta)
        event.accept()


class Filmstrip(QWidget):
    """A darktable-style filmstrip along the bottom of the main editor -
    double-clicking a folder in the Library panel (above Masking) loads its
    images here instead of only opening the separate Import window, so you
    can flip between a roll's photos without leaving the single-image edit
    view. Click a thumbnail to open it; the currently open image is shown
    selected (see ThumbnailDelegate), tracked automatically as the file
    changes however it was opened (this strip, the Import window, File >
    Open Image...). Its thumbnail updates live from the actual edited
    pixels once an edit settles (see update_active_thumbnail) - not on
    every preview tick, the same settle-only cost tier as history logging,
    since regenerating a scaled pixmap on every slider tick would undo the
    whole point of the two-tier preview architecture."""

    image_selected = pyqtSignal(str)
    filter_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        bar = QHBoxLayout()
        bar.setContentsMargins(THEME.space_sm, 0, THEME.space_sm, 0)
        bar.addWidget(QLabel("Show"))
        self._filter = QComboBox()
        for key, label in FILTERS:
            self._filter.addItem(label, key)
        self._filter.setToolTip("Only show some of this roll's photos: keepers, the ones not rejected, the ones you haven't touched yet...")
        self._filter.currentIndexChanged.connect(self._on_filter_picked)
        bar.addWidget(self._filter)
        self._count = QLabel("")
        bar.addWidget(self._count)
        bar.addStretch(1)
        layout.addLayout(bar)

        self._list = _FilmstripList()
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setFlow(QListView.Flow.LeftToRight)
        self._list.setWrapping(False)
        self._list.setIconSize(QSize(_THUMB_SIZE, _THUMB_SIZE))
        self._list.setFixedHeight(_STRIP_HEIGHT)
        self._list.setSpacing(THEME.space_sm)
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setItemDelegate(ThumbnailDelegate(self._list))
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list)

        self._loader: ThumbnailLoader | None = None
        self._active_path: str | None = None
        self._active_icon: QIcon | None = None  # the latest edited look, re-applied if its tile loads in later
        self._paths: list[str] = []
        self._flags: dict[str, str] = {}
        self._ratings: dict[str, int] = {}
        self._edited: set[str] = set()
        self._panels_hidden = False  # Tab hides the strip along with the side panels
        self.setVisible(False)  # hidden until a folder is actually loaded

    def paths(self) -> list[str]:
        """The folder currently loaded into the strip."""
        return list(self._paths)

    def set_panels_hidden(self, hidden: bool) -> None:
        self._panels_hidden = hidden
        self.setVisible(bool(self._paths) and not hidden)

    def load_folder(
        self, paths: list[str], flags: dict[str, str] | None = None, ratings: dict[str, int] | None = None, edited: set[str] | None = None
    ) -> None:
        self._list.clear()
        self._paths = list(paths)
        self._flags = dict(flags or {})  # keeper/rejected marks, tinted onto the tiles
        self._ratings = dict(ratings or {})  # star ratings, drawn on the tiles
        self._edited = set(edited or ())  # photos with changed edits, for the Unedited filter
        self.setVisible(bool(paths) and not self._panels_hidden)
        if not paths:
            return
        self._loader = ThumbnailLoader(paths, thumbnail_cache_dir())
        self._loader.thumb_ready.connect(self._add_tile)
        self._loader.finished.connect(self._loader.deleteLater)
        self._loader.start()

    def set_active_path(self, path: str | None) -> None:
        self._active_path = path
        self._active_icon = None  # a newly-opened file starts from its own plain cached thumbnail
        item = self._find_item(path)
        if self.filter_mode() != "all":
            self._apply_filter()
        self._list.setCurrentItem(item)
        if item is not None:
            self._list.scrollToItem(item)

    def update_active_thumbnail(self, pixels: np.ndarray) -> None:
        """Refreshes the active path's tile icon from pixels (the live
        edited image) - looked up by path, not Qt's currentItem(), so this
        still finds the right tile regardless of the list's own selection
        state. Doesn't touch the on-disk thumbnail cache, which
        deliberately stays a neutral read of the untouched source file (see
        features/browse/processor.py). If that tile hasn't finished loading
        in from the background thumbnailer yet, the icon is remembered and
        applied the moment it does (see _add_tile) instead of being
        silently dropped and overwritten by the plain cached one."""
        if self._active_path is None:
            return
        step = max(1, max(pixels.shape[:2]) // 800)  # an HQ frame is far bigger than any tile needs
        pixels = pixels[::step, ::step]
        save_edited_thumbnail(thumbnail_cache_dir(), self._active_path, pixels)
        self._active_icon = QIcon(_make_thumbnail_pixmap(pixels, _THUMB_SIZE))
        item = self._find_item(self._active_path)
        if item is not None:
            item.setIcon(self._active_icon)

    def flags(self) -> dict[str, str]:
        return dict(self._flags)

    def set_flag(self, path: str, flag: str | None) -> None:
        """Marks a tile keeper (light green) / rejected (red) / neither."""
        if flag is None:
            self._flags.pop(path, None)
        else:
            self._flags[path] = flag
        item = self._find_item(path)
        if item is not None:
            item.setData(FLAG_ROLE, flag)
            item.setHidden(not self._passes(path))
            self._list.viewport().update()
        self._update_count()

    def set_rating(self, path: str, stars: int) -> None:
        if stars:
            self._ratings[path] = stars
        else:
            self._ratings.pop(path, None)
        item = self._find_item(path)
        if item is not None:
            item.setData(RATING_ROLE, stars)
            item.setHidden(not self._passes(path))
            self._list.viewport().update()
        self._update_count()

    def mark_edited(self, path: str) -> None:
        """The photo now has edits that change something (so the Unedited filter no longer shows it)."""
        if path in self._edited:
            return
        self._edited.add(path)
        item = self._find_item(path)
        if item is not None:
            item.setHidden(not self._passes(path))
        self._update_count()

    # ---- filtering and stepping ----
    def filter_mode(self) -> str:
        return self._filter.currentData()

    def set_filter(self, mode: str) -> None:
        i = self._filter.findData(mode)
        if i >= 0 and i != self._filter.currentIndex():
            self._filter.setCurrentIndex(i)  # _on_filter_picked does the rest

    def _passes(self, path: str) -> bool:
        mode = self._filter.currentData()
        flag = self._flags.get(path)
        if mode == "keepers":
            return flag == "keeper"
        if mode == "not_rejected":
            return flag != "rejected"
        if mode == "rejected":
            return flag == "rejected"
        if mode == "unedited":
            return path not in self._edited
        if mode == "rated":
            return self._ratings.get(path, 0) > 0
        return True

    def _apply_filter(self) -> None:
        for i in range(self._list.count()):
            item = self._list.item(i)
            path = item.data(Qt.ItemDataRole.UserRole)
            # the photo that is open stays visible, so the strip never loses its place under you
            item.setHidden(not (self._passes(path) or path == self._active_path))
        self._update_count()

    def _on_filter_picked(self, _index: int) -> None:
        self._apply_filter()
        self.filter_changed.emit(self._filter.currentData())

    def _update_count(self) -> None:
        total = len(self._paths)
        shown = sum(1 for p in self._paths if self._passes(p))
        self._count.setText(f"{shown} of {total}" if total and self.filter_mode() != "all" else (f"{total} photos" if total else ""))

    def _visible_paths(self) -> list[str]:
        out = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if not item.isHidden():
                out.append(item.data(Qt.ItemDataRole.UserRole))
        return out

    def neighbor(self, delta: int) -> str | None:
        """The photo delta places along the visible strip from the open one (-1 previous, +1 next); None at either end."""
        visible = self._visible_paths()
        if not visible:
            return None
        if self._active_path in visible:
            j = visible.index(self._active_path) + delta
            return visible[j] if 0 <= j < len(visible) else None
        return visible[0] if delta > 0 else visible[-1]

    def edge(self, last: bool) -> str | None:
        visible = self._visible_paths()
        return (visible[-1] if last else visible[0]) if visible else None

    def step(self, delta: int) -> bool:
        """Open the previous/next photo of the strip. False when there is none (an end, or no folder loaded)."""
        path = self.neighbor(delta)
        if path is None:
            return False
        self.image_selected.emit(path)
        return True

    def list_widget(self) -> QListWidget:
        return self._list

    def _find_item(self, path: str | None) -> QListWidgetItem | None:
        if path is None:
            return None
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                return item
        return None

    def _add_tile(self, path: str, data: bytes | None) -> None:
        item = QListWidgetItem(os.path.basename(path))
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setData(FLAG_ROLE, self._flags.get(path))
        item.setData(RATING_ROLE, self._ratings.get(path, 0))
        if path == self._active_path and self._active_icon is not None:
            item.setIcon(self._active_icon)
        elif data:
            pix = QPixmap()
            pix.loadFromData(data)
            item.setIcon(QIcon(pix))
        self._list.addItem(item)
        item.setHidden(not (self._passes(path) or path == self._active_path))
        if path == self._active_path:
            self._list.setCurrentItem(item)
        self._update_count()

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.image_selected.emit(path)


def _make_thumbnail_pixmap(pixels: np.ndarray, size: int) -> QPixmap:
    pixels = np.ascontiguousarray(pixels)
    h, w, _ = pixels.shape
    image = QImage(pixels.data, w, h, w * 3, QImage.Format.Format_RGB888)
    pixmap = QPixmap.fromImage(image.copy())
    return pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
