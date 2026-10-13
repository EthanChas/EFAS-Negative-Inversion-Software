from PyQt6.QtCore import QRect, QSize, Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices, QKeyEvent, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from ...features.film_reference import logic as L
from ...theme.tokens import THEME
from .. import film_reference_client as client

PIXMAP_ROLE = Qt.ItemDataRole.UserRole + 1
PHOTO_ROLE = Qt.ItemDataRole.UserRole + 2
TILE_HEIGHT = 190
PAGE_NOTE = (
    "Photos by Lomography community members, shown here from lomography.com only as a colour reference for the film. They are not saved or edited; "
    "click one to see it larger and who took it."
)


class _TileDelegate(QStyledItemDelegate):
    """Draws each photo at its own width and a common height, edge to edge on a dark ground: a clean gallery with no captions or frames."""

    def paint(self, painter: QPainter, option, index) -> None:
        rect: QRect = option.rect.adjusted(2, 2, -2, -2)
        pixmap = index.data(PIXMAP_ROLE)
        painter.save()
        painter.fillRect(rect, QColor(THEME.bg_panel))  # a placeholder tile until the picture arrives
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            scaled = pixmap.scaled(rect.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(rect.topLeft(), scaled, QRect((scaled.width() - rect.width()) // 2, (scaled.height() - rect.height()) // 2, rect.width(), rect.height()))
        if option.state & (QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_Selected):
            painter.setPen(QColor(THEME.accent_primary))
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return index.data(Qt.ItemDataRole.SizeHintRole) or QSize(TILE_HEIGHT, TILE_HEIGHT)


class PhotoViewer(QDialog):
    """One photo large, with who took it, what they said and a link to its page; left and right arrows (or the buttons) move through the gallery."""

    def __init__(self, fetcher: client.Fetcher, photos: list[L.Photo], index: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Film Colour Reference")
        self.resize(1000, 760)
        self._fetcher, self._photos, self._index = fetcher, photos, index
        self._pixmap: QPixmap | None = None
        self._detail: L.PhotoDetail | None = None
        self._request = 0
        layout = QVBoxLayout(self)
        layout.setSpacing(THEME.space_md)
        self._image = QLabel("Loading...")
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setMinimumSize(300, 300)
        self._image.setStyleSheet(f"background: {THEME.bg_input};")
        layout.addWidget(self._image, 1)
        self._credit = QLabel("")
        self._credit.setStyleSheet("font-weight: bold;")
        layout.addWidget(self._credit)
        self._text = QLabel("")
        self._text.setWordWrap(True)
        self._text.setProperty("role", "hint")
        layout.addWidget(self._text)
        row = QHBoxLayout()
        self._prev = QPushButton("< Previous")
        self._next = QPushButton("Next >")
        self._open = QPushButton("Open on Lomography")
        close = QPushButton("Close")
        for b in (self._prev, self._next, self._open):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)
        self._prev.clicked.connect(lambda: self.step(-1))
        self._next.clicked.connect(lambda: self.step(1))
        self._open.clicked.connect(self._open_page)
        close.clicked.connect(self.accept)
        fetcher.done.connect(self._on_done)
        self.show_photo(index)

    def show_photo(self, index: int) -> None:
        self._index = max(0, min(index, len(self._photos) - 1))
        photo = self._photos[self._index]
        self._request += 1
        self._pixmap, self._detail = None, None
        self._image.setText("Loading...")
        self._image.setPixmap(QPixmap())
        self._credit.setText("")
        self._text.setText(f"Photo {self._index + 1} of {len(self._photos)}")
        self._prev.setEnabled(self._index > 0)
        self._next.setEnabled(self._index < len(self._photos) - 1)
        self._open.setEnabled(False)
        self._fetcher.get(("detail", self._request), L.BASE + photo.page_path)

    def step(self, delta: int) -> None:
        if 0 <= self._index + delta < len(self._photos):
            self.show_photo(self._index + delta)

    def _on_done(self, tag, data, error: str) -> None:
        if not (isinstance(tag, tuple) and tag[0] in ("detail", "big") and tag[1] == self._request):
            return
        if tag[0] == "detail":
            detail = L.parse_photo_detail(data.decode("utf-8", "replace")) if data else None
            if detail is None:
                self._image.setText(error or "That photo's page did not have a picture.")
                return
            self._detail = detail
            self._credit.setText(L.credit(detail.author))
            self._text.setText(detail.description or f"Photo {self._index + 1} of {len(self._photos)}")
            self._open.setEnabled(True)
            self._fetcher.get(("big", self._request), detail.image_url, image=True)
        elif data:
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                self._pixmap = pixmap
                self._fit()
            else:
                self._image.setText("The picture could not be read.")
        else:
            self._image.setText(error or "The picture could not be loaded.")

    def _fit(self) -> None:
        if self._pixmap is not None:
            self._image.setPixmap(self._pixmap.scaled(self._image.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Left:
            self.step(-1)
        elif event.key() == Qt.Key.Key_Right:
            self.step(1)
        else:
            super().keyPressEvent(event)

    def _open_page(self) -> None:
        if self._detail is not None and self._detail.page_url.startswith("https://www.lomography.com/"):
            QDesktopServices.openUrl(QUrl(self._detail.page_url))


class FilmReferenceDialog(QDialog):
    """Film Colour Reference: type a film stock, pick it from the list, and see photos shot on it, from lomography.com, in a plain gallery - the colour a stock
    really gives, for judging a conversion against. Search is done here on the film list (fetched once and kept for two weeks), so nothing you type is sent
    anywhere; opening a film fetches its page of photos."""

    def __init__(self, parent: QWidget | None = None, initial_query: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Film Colour Reference")
        self.resize(1180, 780)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self._fetcher = client.Fetcher(self)
        self._fetcher.done.connect(self._on_done)
        self._films: list[L.Film] = []
        self._film: L.Film | None = None
        self._order = "popular"
        self._page = 0
        self._more = False
        self._loading = False
        self._generation = 0
        self._photos: list[L.Photo] = []
        self._viewer: PhotoViewer | None = None

        outer = QHBoxLayout(self)
        outer.setSpacing(THEME.space_lg)
        left = QVBoxLayout()
        self._search = QLineEdit(initial_query)
        self._search.setPlaceholderText("Search a film: Portra 400, Ektar, HP5...")
        self._search.setClearButtonEnabled(True)
        left.addWidget(self._search)
        self._list = QListWidget()
        self._list.setFixedWidth(280)
        left.addWidget(self._list, 1)
        self._list_note = QLabel("Loading the film list...")
        self._list_note.setWordWrap(True)
        self._list_note.setProperty("role", "hint")
        left.addWidget(self._list_note)
        self._refresh = QPushButton("Update the film list")
        self._refresh.setToolTip("Fetch the list of films from lomography.com again (it is kept for two weeks)")
        left.addWidget(self._refresh)
        outer.addLayout(left)

        right = QVBoxLayout()
        head = QHBoxLayout()
        self._title = QLabel("Pick a film")
        self._title.setStyleSheet("font-weight: bold;")
        head.addWidget(self._title, 1)
        head.addWidget(QLabel("Show"))
        self._sort = QComboBox()
        for key, label in L.ORDERS:
            self._sort.addItem(label, key)
        head.addWidget(self._sort)
        self._open_film = QPushButton("Open on Lomography")
        self._open_film.setEnabled(False)
        head.addWidget(self._open_film)
        right.addLayout(head)
        self._grid = QListWidget()
        self._grid.setViewMode(QListView.ViewMode.IconMode)
        self._grid.setMovement(QListView.Movement.Static)
        self._grid.setResizeMode(QListView.ResizeMode.Adjust)
        self._grid.setWrapping(True)
        self._grid.setSpacing(2)
        self._grid.setUniformItemSizes(False)
        self._grid.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._grid.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._grid.setItemDelegate(_TileDelegate(self._grid))
        self._grid.setMouseTracking(True)
        self._grid.setStyleSheet(f"QListWidget {{ background: {THEME.bg_input}; border: none; }}")
        right.addWidget(self._grid, 1)
        foot = QHBoxLayout()
        self._status = QLabel("")
        self._status.setProperty("role", "hint")
        foot.addWidget(self._status, 1)
        self._more_btn = QPushButton("Show more")
        self._more_btn.setVisible(False)
        foot.addWidget(self._more_btn)
        right.addLayout(foot)
        note = QLabel(PAGE_NOTE)
        note.setWordWrap(True)
        note.setProperty("role", "hint")
        right.addWidget(note)
        outer.addLayout(right, 1)

        self._search.textChanged.connect(self._filter)
        self._list.currentItemChanged.connect(self._on_film_picked)
        self._sort.currentIndexChanged.connect(self._on_sort)
        self._more_btn.clicked.connect(self._load_page)
        self._refresh.clicked.connect(lambda: self._load_films(force=True))
        self._open_film.clicked.connect(self._open_film_page)
        self._grid.itemClicked.connect(self._open_viewer)
        self._grid.itemActivated.connect(self._open_viewer)
        self._grid.verticalScrollBar().valueChanged.connect(self._maybe_load_more)
        self._load_films()

    # ------------------------------------------------------------ the film list
    def _load_films(self, force: bool = False) -> None:
        self._list_note.setText("Fetching the film list from lomography.com...")
        self._refresh.setEnabled(False)
        self._fetcher.catalogue(("films", force), force)

    def _filter(self) -> None:
        shown = L.search_films(self._films, self._search.text())
        self._list.blockSignals(True)
        self._list.clear()
        for film in shown:
            item = QListWidgetItem(film.name)
            item.setData(Qt.ItemDataRole.UserRole, film)
            self._list.addItem(item)
        self._list.blockSignals(False)
        if self._films:
            self._list_note.setText(f"{len(shown)} of {len(self._films)} films" + ("" if shown else ". None matches: try fewer words."))
        if shown and self._film is None and self._search.text().strip():
            self._list.setCurrentRow(0)  # typing a film and finding one opens its photos

    def _on_film_picked(self, item: QListWidgetItem | None, _previous=None) -> None:
        if item is None:
            return
        self._film = item.data(Qt.ItemDataRole.UserRole)
        self._title.setText(self._film.name)
        self._open_film.setEnabled(True)
        self._reset_gallery()
        self._load_page()

    def _on_sort(self) -> None:
        self._order = self._sort.currentData()
        if self._film is not None:
            self._reset_gallery()
            self._load_page()

    # ------------------------------------------------------------ the photos
    def _reset_gallery(self) -> None:
        self._generation += 1
        self._grid.clear()
        self._photos = []
        self._page = 0
        self._more = False
        self._loading = False
        self._more_btn.setVisible(False)

    def _load_page(self) -> None:
        if self._film is None or self._loading:
            return
        self._loading = True
        self._page += 1
        self._status.setText("Loading photos..." if self._page == 1 else "Loading more photos...")
        self._more_btn.setEnabled(False)
        self._fetcher.get(("photos", self._generation, self._page), L.photos_url(self._film, self._order, self._page))

    def _maybe_load_more(self) -> None:
        bar = self._grid.verticalScrollBar()
        if self._more and not self._loading and bar.maximum() > 0 and bar.value() >= bar.maximum() - 160:
            self._load_page()

    def _add_photos(self, photos: list[L.Photo]) -> None:
        for photo in photos:
            item = QListWidgetItem()
            w, h = L.tile_size(photo, TILE_HEIGHT)
            item.setSizeHint(QSize(w + 4, h + 4))
            item.setData(PHOTO_ROLE, photo)
            self._grid.addItem(item)
            self._photos.append(photo)
            self._fetcher.get(("thumb", self._generation, photo.photo_id), photo.thumb_url, image=True)

    def _on_done(self, tag, data, error: str) -> None:
        kind = tag[0] if isinstance(tag, tuple) else ""
        if kind == "films":
            self._refresh.setEnabled(True)
            if data is None:
                self._list_note.setText(error or "The film list could not be loaded.")
                return
            self._films, from_saved = data
            self._filter()
            if self._search.text().strip() and self._list.count() == 0:
                self._list_note.setText("No film matches that. Try fewer words, or check the spelling.")
        elif kind == "photos" and tag[1] == self._generation:
            self._loading = False
            self._more_btn.setEnabled(True)
            if data is None:
                self._status.setText(error or "The photos could not be loaded.")
                self._page = max(0, self._page - 1)
                self._more_btn.setVisible(self._page > 0)
                return
            photos, self._more = L.parse_photos(data.decode("utf-8", "replace"))
            self._add_photos(photos)
            self._more_btn.setVisible(self._more)
            self._status.setText(f"{len(self._photos)} photos" + ("" if self._photos else ": none found for this film"))
        elif kind == "thumb" and tag[1] == self._generation and data:
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                for row in range(self._grid.count()):
                    item = self._grid.item(row)
                    if item.data(PHOTO_ROLE).photo_id == tag[2]:
                        item.setData(PIXMAP_ROLE, pixmap)
                        break
                self._grid.viewport().update()

    # ------------------------------------------------------------ opening things
    def _open_viewer(self, item: QListWidgetItem) -> None:
        photo = item.data(PHOTO_ROLE)
        if photo is None or not self._photos:
            return
        index = next((i for i, p in enumerate(self._photos) if p.photo_id == photo.photo_id), 0)
        self._viewer = PhotoViewer(self._fetcher, list(self._photos), index, self)
        self._viewer.show()

    def _open_film_page(self) -> None:
        if self._film is not None:
            QDesktopServices.openUrl(QUrl(self._film.url))

    def closeEvent(self, event) -> None:
        self._fetcher.close()
        super().closeEvent(event)
