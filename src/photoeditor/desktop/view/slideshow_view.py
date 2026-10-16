import os
from collections import OrderedDict

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QImage, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPixmap
from PyQt6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSlider, QVBoxLayout, QWidget

from ...features.settings import logic as app_settings
from ...features.slideshow import logic as show
from ...features.slideshow import music
from ...theme.tokens import THEME
from .. import music_player, slideshow_worker
from . import panel_icons

_CACHE_SLIDES = 8
_FAILED_SKIP_MS = 1500
_HIDE_CURSOR_MS = 2000
_BAR_MS = 33
_BAR_HEIGHT = 4


class SlideshowStage(QWidget):
    """Where the pictures are shown: black, the slide fitted into it, a crossfade from the one before, the caption along the bottom and the place in the show in the corner.
    It also takes the keys (the view decides what they do) and a double-click for full screen."""

    key_pressed = pyqtSignal(object)
    fullscreen_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(320, 220)
        self.setAutoFillBackground(False)
        self._image: QImage | None = None
        self._previous: QImage | None = None
        self._caption = ""
        self._counter = ""
        self._message = ""
        self._fade = 1.0
        self._progress: float | None = None
        self._scaled: dict[str, tuple] = {}
        self._animation = QVariantAnimation(self)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.valueChanged.connect(self._on_fade)
        self._animation.finished.connect(self._on_fade_done)
        self._hide_cursor = False
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setSingleShot(True)
        self._cursor_timer.setInterval(_HIDE_CURSOR_MS)
        self._cursor_timer.timeout.connect(self._maybe_hide_cursor)

    # ------------------------------------------------------------ what is shown
    def image(self) -> QImage | None:
        return self._image

    def fading(self) -> bool:
        return self._animation.state() == QVariantAnimation.State.Running

    def show_slide(self, image: QImage | None, caption: str, counter: str, fade_ms: int = 0) -> None:
        """Put a picture on the stage, fading from the one that was there when fade_ms is more than 0."""
        self._animation.stop()
        self._previous = self._image if (fade_ms > 0 and self._image is not None and image is not None) else None
        self._image = image
        self._caption, self._counter, self._message = caption, counter, ""
        self._scaled.pop("current", None)
        self._scaled.pop("previous", None)
        if self._previous is not None:
            self._fade = 0.0
            self._animation.setDuration(int(fade_ms))
            self._animation.start()
        else:
            self._fade = 1.0
        self.update()

    def replace_image(self, image: QImage) -> None:
        """Swap the picture for a sharper one of the same slide, with no fade."""
        self._image = image
        self._scaled.pop("current", None)
        self.update()

    def set_overlay(self, caption: str, counter: str) -> None:
        self._caption, self._counter = caption, counter
        self.update()

    def set_message(self, text: str) -> None:
        self._message = text
        self.update()

    def set_progress(self, fraction: float | None) -> None:
        """How far through its time the photo on show is (0-1), drawn as a bar along the bottom edge; None hides the bar."""
        if fraction != self._progress:
            self._progress = fraction
            self.update(0, self.height() - _BAR_HEIGHT - 2, self.width(), _BAR_HEIGHT + 2)

    def progress(self) -> float | None:
        return self._progress

    def clear(self) -> None:
        self._animation.stop()
        self._image = self._previous = None
        self._caption = self._counter = ""
        self._scaled.clear()
        self._progress = None
        self.update()

    def _on_fade(self, value) -> None:
        self._fade = float(value)
        self.update()

    def _on_fade_done(self) -> None:
        self._fade = 1.0
        self._previous = None
        self._scaled.pop("previous", None)
        self.update()

    # ------------------------------------------------------------ painting
    def _fitted(self, slot: str, image: QImage) -> QPixmap:
        ratio = self.devicePixelRatioF()
        size = (round(self.width() * ratio), round(self.height() * ratio))
        cached = self._scaled.get(slot)
        if cached is not None and cached[0] == size and cached[1] is image:
            return cached[2]
        fitted = image.scaled(size[0], size[1], Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        pixmap = QPixmap.fromImage(fitted)
        pixmap.setDevicePixelRatio(ratio)
        self._scaled[slot] = (size, image, pixmap)
        return pixmap

    def _draw_picture(self, painter: QPainter, slot: str, image: QImage, opacity: float) -> None:
        pixmap = self._fitted(slot, image)
        ratio = pixmap.devicePixelRatio() or 1.0
        w, h = pixmap.width() / ratio, pixmap.height() / ratio
        painter.setOpacity(opacity)
        painter.drawPixmap(QPointF((self.width() - w) / 2.0, (self.height() - h) / 2.0), pixmap)
        painter.setOpacity(1.0)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if self._previous is not None:
            self._draw_picture(painter, "previous", self._previous, 1.0)
        if self._image is not None:
            self._draw_picture(painter, "current", self._image, self._fade if self._previous is not None else 1.0)
        font = QFont(painter.font())
        font.setPointSize(max(10, THEME.font_size_small + 3))
        painter.setFont(font)
        metrics = painter.fontMetrics()
        pad = 10
        if self._caption:
            width = min(self.width() - 2 * pad, metrics.horizontalAdvance(self._caption) + 2 * pad)
            box = QRect(pad, self.height() - metrics.height() - 2 * pad, width, metrics.height() + pad)
            painter.fillRect(box, QColor(0, 0, 0, 150))
            painter.setPen(QColor(235, 235, 235))
            painter.drawText(box.adjusted(pad // 2, 0, -pad // 2, 0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), metrics.elidedText(self._caption, Qt.TextElideMode.ElideRight, width - pad))
        if self._counter:
            width = metrics.horizontalAdvance(self._counter) + 2 * pad
            box = QRect(self.width() - width - pad, self.height() - metrics.height() - 2 * pad, width, metrics.height() + pad)
            painter.fillRect(box, QColor(0, 0, 0, 150))
            painter.setPen(QColor(200, 200, 200))
            painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), self._counter)
        if self._message:
            width = metrics.horizontalAdvance(self._message) + 4 * pad
            box = QRectF((self.width() - width) / 2.0, (self.height() - metrics.height()) / 2.0 - pad, width, metrics.height() + 2 * pad)
            painter.fillRect(box, QColor(0, 0, 0, 170))
            painter.setPen(QColor(235, 235, 235))
            painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), self._message)
        if self._progress is not None:
            painter.fillRect(QRect(0, self.height() - _BAR_HEIGHT, self.width(), _BAR_HEIGHT), QColor(255, 255, 255, 45))
            painter.fillRect(QRect(0, self.height() - _BAR_HEIGHT, int(round(self.width() * self._progress)), _BAR_HEIGHT), QColor(THEME.accent_primary))
        painter.end()

    # ------------------------------------------------------------ keys, mouse, the cursor
    def keyPressEvent(self, event: QKeyEvent) -> None:
        self.key_pressed.emit(event)
        if not event.isAccepted():
            super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.fullscreen_requested.emit()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        super().mouseMoveEvent(event)
        self.unsetCursor()
        if self._hide_cursor:
            self._cursor_timer.start()

    def set_cursor_hiding(self, on: bool) -> None:
        """In full screen the cursor disappears after a couple of seconds still."""
        self._hide_cursor = on
        self.unsetCursor()
        if on:
            self._cursor_timer.start()
        else:
            self._cursor_timer.stop()

    def _maybe_hide_cursor(self) -> None:
        if self._hide_cursor:
            self.setCursor(Qt.CursorShape.BlankCursor)


class _FullscreenHost(QWidget):
    """The black full-screen window the stage moves into."""

    closed = pyqtSignal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.Window)
        self.setStyleSheet("background: black;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

    def closeEvent(self, event) -> None:
        self.closed.emit()
        super().closeEvent(event)


class SlideshowView(QWidget):
    """The Slideshow page: a bar of controls over the stage. Photos come from the Workbench (what it shows, or what is selected) or the editor's open folder, each made with its
    saved edits (or as the scan is) at the size the screen needs on a worker thread, with the next few made ahead. Play moves on after the chosen number of seconds, with a cut or a
    crossfade; the keys step, play and pause; Full screen moves the stage into a window of its own. The settings are remembered."""

    def __init__(self, db_path: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._db_path = db_path
        self._loader: slideshow_worker.SlideLoader | None = None
        self._providers: dict = {}
        self._all_items: list[tuple[str, str]] = []   # everything the chosen source gave
        self._excluded: set[str] = set()              # the photos the person left out (for this run of the program)
        self._items: list[tuple[str, str]] = []       # what is in the show: the first less the second
        self._order: list[int] = []
        self._pos = 0
        self._playing = False
        self._cache: OrderedDict = OrderedDict()
        self._failed: set = set()
        self._waiting: tuple | None = None
        self._shown_size = 0
        self._shown_key: tuple | None = None
        self._fullscreen: _FullscreenHost | None = None
        self._loading = False
        self._hold_total = 0
        self._hold_left: int | None = None
        self._music = music_player.MusicPlayer(self)
        self._music_pending: str | None = None
        self._music.failed.connect(lambda text: self._music_status.setText(text))
        self._maker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(THEME.space_md, THEME.space_sm, THEME.space_md, THEME.space_md)
        layout.setSpacing(THEME.space_sm)
        layout.addLayout(self._build_transport())
        layout.addLayout(self._build_options())
        layout.addLayout(self._build_music_row())
        self._stage_holder = QVBoxLayout()
        self._stage_holder.setContentsMargins(0, 0, 0, 0)
        self._stage = SlideshowStage()
        self._stage.key_pressed.connect(self._on_key)
        self._stage.fullscreen_requested.connect(self.toggle_fullscreen)
        self._stage_holder.addWidget(self._stage)
        layout.addLayout(self._stage_holder, 1)

        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(self._on_hold_done)
        self._bar_timer = QTimer(self)
        self._bar_timer.setInterval(_BAR_MS)
        self._bar_timer.timeout.connect(self._update_bar)
        self._apply_settings()
        self._sync_buttons()

    # ------------------------------------------------------------ building
    @staticmethod
    def _icon(name: str) -> QIcon:
        """A transport icon by its name here (previous, play, pause, next, fullscreen): the Lucide file in assets/icon it stands for."""
        return QIcon(panel_icons.pixmap(panel_icons.OTHER.get(name, name), 16, THEME.text_primary))

    def _icon_button(self, icon: str, tip: str, on_click) -> QPushButton:
        button = QPushButton()
        button.setIcon(self._icon(icon))
        button.setToolTip(tip)
        button.setFixedHeight(26)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(on_click)
        return button

    def _build_transport(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(THEME.space_sm)
        self._restart_btn = self._icon_button("restart", "Back to the beginning: the first photo, and the music from its start (Home)", self.restart)
        self._restart_btn.setText("Start over")   # a word beside the icon, so it is not missed
        self._previous_btn = self._icon_button("previous", "Previous photo (Left)", lambda: self.step(-1))
        self._play_btn = self._icon_button("play", "Play (Space)", self.toggle_play)
        self._next_btn = self._icon_button("next", "Next photo (Right)", lambda: self.step(1))
        self._full_btn = self._icon_button("fullscreen", "Full screen (F or double-click; Esc leaves)", self.toggle_fullscreen)
        for button in (self._restart_btn, self._previous_btn, self._play_btn, self._next_btn, self._full_btn):
            row.addWidget(button)
        row.addSpacing(THEME.space_md)
        row.addWidget(QLabel("Photos"))
        self._source = QComboBox()
        for key, label in show.SOURCES.items():
            self._source.addItem(label, key)
        self._source.setToolTip("Where the slideshow's photos come from: the ones the Workbench is showing now (its search and filters apply), the ones selected in it, or the folder open in the editor")
        self._source.currentIndexChanged.connect(self._on_source_changed)
        row.addWidget(self._source)
        self._choose_btn = QPushButton("Choose photos...")
        self._choose_btn.setToolTip("Pick which of these photos are in the slideshow and the video (X leaves out the one on screen)")
        self._choose_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._choose_btn.clicked.connect(self.choose_photos)
        row.addWidget(self._choose_btn)
        self._count = QLabel("")
        self._count.setProperty("role", "hint")
        row.addWidget(self._count)
        row.addStretch(1)
        self._hint = QLabel("Space play / pause   ← → step   Home restart   X leave out   F full screen   C captions")
        self._hint.setProperty("role", "hint")
        row.addWidget(self._hint)
        return row

    def _build_options(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(THEME.space_sm)
        row.addWidget(QLabel("Each photo for"))
        self._seconds = QDoubleSpinBox()
        self._seconds.setRange(*show.INTERVAL_RANGE)
        self._seconds.setDecimals(1)
        self._seconds.setSingleStep(0.5)
        self._seconds.setSuffix(" s")
        self._seconds.setToolTip("How long each photo stays on screen before the next")
        self._seconds.valueChanged.connect(self._on_option_changed)
        row.addWidget(self._seconds)
        row.addWidget(QLabel("Change with"))
        self._transition = QComboBox()
        for key, label in show.TRANSITIONS.items():
            self._transition.addItem(label, key)
        self._transition.currentIndexChanged.connect(self._on_option_changed)
        row.addWidget(self._transition)
        self._shuffle = QCheckBox("Shuffle")
        self._shuffle.setToolTip("Show the photos in a random order")
        self._loop = QCheckBox("Loop")
        self._loop.setToolTip("Start again after the last photo")
        self._captions = QCheckBox("Captions")
        self._captions.setToolTip("The file's name (and its film, roll and day, when known) along the bottom (C)")
        self._edits = QCheckBox("With edits")
        self._edits.setToolTip("Show each photo as you edited it (an unedited negative is shown inverted); off shows the scan as it is")
        self._progress_box = QCheckBox("Progress bar")
        self._progress_box.setToolTip("A bar along the bottom that fills as the photo's time runs out")
        for box in (self._shuffle, self._loop, self._captions, self._edits, self._progress_box):
            box.toggled.connect(self._on_option_changed)
            row.addWidget(box)
        row.addStretch(1)
        return row

    def _build_music_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(THEME.space_sm)
        row.addWidget(QLabel("Music"))
        self._music_combo = QComboBox()
        self._music_combo.setToolTip("Music that plays while the slideshow plays: three built-in pieces made for it, or songs of your own (.wav and .mp3) that you add")
        self._fill_music_combo()
        self._music_combo.currentIndexChanged.connect(self._on_music_changed)
        row.addWidget(self._music_combo)
        row.addWidget(QLabel("Volume"))
        self._volume = QSlider(Qt.Orientation.Horizontal)
        self._volume.setRange(0, 100)
        self._volume.setFixedWidth(110)
        self._volume.setToolTip("How loud the music is")
        self._volume.valueChanged.connect(self._on_volume_changed)
        row.addWidget(self._volume)
        self._add_music_btn = QPushButton("Add music...")
        self._add_music_btn.setToolTip("Add your own .wav or .mp3 files to the music list (they are copied into EFAS's folder; the originals are not touched)")
        self._add_music_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._add_music_btn.clicked.connect(self._on_add_music)
        self._remove_music_btn = QPushButton("Remove")
        self._remove_music_btn.setToolTip("Take the chosen song of yours out of the list (only EFAS's copy goes)")
        self._remove_music_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._remove_music_btn.clicked.connect(self._on_remove_music)
        row.addWidget(self._add_music_btn)
        row.addWidget(self._remove_music_btn)
        self._music_status = QLabel("")
        self._music_status.setProperty("role", "hint")
        row.addWidget(self._music_status)
        row.addStretch(1)
        self._export_btn = QPushButton("Export video...")
        self._export_btn.setToolTip("Make the slideshow into an MP4 video, with the music if you have chosen some")
        self._export_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._export_btn.clicked.connect(self.export_video)
        row.addWidget(self._export_btn)
        self._save_volume_timer = QTimer(self)
        self._save_volume_timer.setSingleShot(True)
        self._save_volume_timer.setInterval(400)
        self._save_volume_timer.timeout.connect(self._save_settings)
        return row

    # ------------------------------------------------------------ settings
    def _apply_settings(self) -> None:
        self._loading = True
        s = app_settings.load()
        self._seconds.setValue(s["slideshow_interval"])
        self._transition.setCurrentIndex(max(0, self._transition.findData(s["slideshow_transition"])))
        self._source.setCurrentIndex(max(0, self._source.findData(s["slideshow_source"])))
        self._shuffle.setChecked(s["slideshow_shuffle"])
        self._loop.setChecked(s["slideshow_loop"])
        self._captions.setChecked(s["slideshow_captions"])
        self._edits.setChecked(s["slideshow_edits"])
        self._progress_box.setChecked(s["slideshow_progress"])
        self._volume.setValue(s["slideshow_volume"])
        self._music.set_volume(s["slideshow_volume"])
        self._select_music(music.clean_choice(s["slideshow_music"]))
        self._loading = False

    def _save_settings(self) -> None:
        try:
            app_settings.save({
                "slideshow_interval": float(self._seconds.value()), "slideshow_transition": self._transition.currentData(), "slideshow_source": self._source.currentData(),
                "slideshow_shuffle": self._shuffle.isChecked(), "slideshow_loop": self._loop.isChecked(), "slideshow_captions": self._captions.isChecked(),
                "slideshow_edits": self._edits.isChecked(), "slideshow_progress": self._progress_box.isChecked(), "slideshow_music": self._music_combo.currentData() or music.OFF,
                "slideshow_volume": self._volume.value(),
            })
        except OSError:
            pass

    # ------------------------------------------------------------ the photos
    def set_sources(self, providers: dict) -> None:
        """providers maps "shown", "selected" and "folder" to a function that returns [(path, caption)]."""
        self._providers = dict(providers)

    def open_slideshow(self, start_path: str | None = None) -> None:
        """The page has been opened: gather the photos and show the first (or the one at start_path, the photo open in the editor), paused."""
        self._ensure_loader()
        self.reload_items(start_path)
        self._stage.setFocus()

    def reload_items(self, start_path: str | None = None) -> None:
        self.pause()
        provider = self._providers.get(self._source.currentData())
        self._all_items = list(provider()) if provider is not None else []
        self._rebuild(start_path)

    def _rebuild(self, keep_path: str | None = None) -> None:
        """Make the show from the source's photos less the ones left out, starting at keep_path if it is in it, and show the first."""
        self._items = [item for item in self._all_items if item[0] not in self._excluded]
        first = next((i for i, (path, _c) in enumerate(self._items) if path == keep_path), None)
        self._order = show.order(len(self._items), self._shuffle.isChecked(), first=first)
        self._pos = self._order.index(first) if first is not None else 0
        self._waiting = None
        self._shown_key = None
        left_out = len(self._all_items) - len(self._items)
        self._count.setText((f"{len(self._items)} photo{'s' if len(self._items) != 1 else ''}" + (f" ({left_out} left out)" if left_out else "")) if self._all_items else "")
        self._sync_buttons()
        if not self._items:
            self._stage.clear()
            self._stage.set_message("Every photo is left out: choose some to show" if self._all_items else
                                    {"shown": "Nothing in the Workbench to show: add a folder in the Library panel", "selected": "Select photos in the Workbench to show them",
                                     "folder": "Open a folder in the editor to show it"}.get(self._source.currentData(), "Nothing to show"))
            return
        self._show_current()

    # ------------------------------------------------------------ choosing the photos, starting again
    def left_out(self) -> set[str]:
        return set(self._excluded)

    def set_included(self, included: set[str]) -> None:
        """Put exactly these (of the photos the source holds) in the show and leave the rest out. The photo on screen stays up if it is still in."""
        listed = {path for path, _c in self._all_items}
        self._excluded = (self._excluded - listed) | (listed - set(included))
        playing, keep = self._playing, self.current_path()
        self._end_hold()
        self._rebuild(keep)
        if playing and self._items:
            self._playing = True
            self._sync_buttons()

    def choose_photos(self) -> None:
        from .slideshow_photos_dialog import SlideshowPhotosDialog

        if not self._all_items:
            return
        dialog = SlideshowPhotosDialog(self._all_items, {path for path, _c in self._all_items} - self._excluded, self)
        if dialog.exec():
            self.set_included(dialog.included())
        self._stage.setFocus()

    def leave_out_current(self) -> None:
        """X: leave the photo on screen out of the show (Choose photos... puts it back) and move on to the next one."""
        path = self.current_path()
        if path is None:
            return
        following = show.step(self._pos, len(self._items), 1, True)
        keep = self._items[self._order[following]][0] if following is not None and following != self._pos else None
        name = os.path.basename(path)
        self._excluded.add(path)
        playing = self._playing
        self._end_hold()
        self._rebuild(keep)
        if self._items:
            self._stage.set_message(f"Left out {os.path.splitext(name)[0]}")
            QTimer.singleShot(1800, lambda: self._stage.set_message("") if self._stage._message.startswith("Left out") else None)
        if playing and self._items:
            self._playing = True
            self._sync_buttons()

    def restart(self) -> None:
        """Back to the beginning: the first photo of the show, and the music from the start of its song. Playing or paused stays as it was."""
        if not self._items:
            return
        self._music.restart()
        self.go_to(0)
        self._stage.setFocus()

    def item_count(self) -> int:
        return len(self._items)

    def position(self) -> int:
        """Which photo (0-based, in the order they are being shown) is up."""
        return self._pos

    def current_path(self) -> str | None:
        return self._items[self._order[self._pos]][0] if self._items else None

    def _ensure_loader(self) -> None:
        if self._loader is None:
            self._loader = slideshow_worker.SlideLoader(self._db_path)
            self._loader.loaded.connect(self._on_loaded)
            self._loader.start()

    def _size(self) -> int:
        return show.render_size(self._stage.width(), self._stage.height(), self._stage.devicePixelRatioF())

    def _key_for(self, pos: int, size: int | None = None) -> tuple:
        path = self._items[self._order[pos]][0]
        return (path, size or self._size(), self._edits.isChecked())

    # ------------------------------------------------------------ showing
    def _show_current(self) -> None:
        if not self._items:
            return
        key = self._key_for(self._pos)
        if key in self._cache:
            self._cache.move_to_end(key)
            self._display(key)
            return
        if key[0] in self._failed:
            self._skip_failed(key)
            return
        self._waiting = key
        self._request(key)
        self._stage.set_message("Loading...")
        self._prefetch()

    def _request(self, key: tuple) -> None:
        if self._loader is not None:
            self._loader.request(*key)

    def _display(self, key: tuple) -> None:
        image = self._cache[key]
        self._waiting = None
        fade = int(show.FADE_SECONDS * 1000) if self._transition.currentData() == "fade" and self._shown_key is not None else 0
        self._stage.show_slide(image, self._caption_text(), self._counter_text(), fade)
        self._shown_key, self._shown_size = key, key[1]
        self._prefetch()
        if self._playing:
            self._begin_hold()
        else:
            self._end_hold()

    def _caption_text(self) -> str:
        return self._items[self._order[self._pos]][1] if self._captions.isChecked() and self._items else ""

    def _counter_text(self) -> str:
        return f"{self._pos + 1} / {len(self._items)}" if self._items else ""

    def _prefetch(self) -> None:
        position = self._pos
        for _ in range(show.PREFETCH):
            nxt = show.step(position, len(self._items), 1, True)
            if nxt is None or nxt == self._pos:
                break
            position = nxt
            key = self._key_for(position)
            if key not in self._cache and key[0] not in self._failed:
                self._request(key)

    def _on_loaded(self, path: str, size: int, edited: bool, image, error: str) -> None:
        key = (path, size, edited)
        if image is not None:
            self._cache[key] = image
            while len(self._cache) > _CACHE_SLIDES:
                self._cache.popitem(last=False)
            if self._waiting is not None and self._waiting[0] == path and self._waiting[2] == edited:   # whatever size the stage had when it was asked for
                self._display(key)
            elif self._shown_key is not None and self._shown_key[0] == path and self._shown_key[2] == edited and size > self._shown_size and self._waiting is None:
                self._stage.replace_image(image)   # the same photo, made bigger for a bigger stage
                self._shown_key, self._shown_size = key, size
            return
        self._failed.add(path)
        if self._waiting is not None and self._waiting[0] == path:
            self._skip_failed(self._waiting, error)

    def _skip_failed(self, key: tuple, error: str = "") -> None:
        self._waiting = None
        name = os.path.basename(key[0])
        self._stage.set_message(f"Could not open {name}" + (f" ({error.split(':')[0]})" if error else ""))
        if self._playing:
            self._begin_hold(_FAILED_SKIP_MS, bar=False)

    def _on_hold_done(self) -> None:
        if self._playing:
            self.step(1)

    # ------------------------------------------------------------ how long the photo has left, and the bar that shows it
    def _begin_hold(self, ms: int | None = None, bar: bool = True, total: int | None = None) -> None:
        """Start the photo's time (the whole interval, or `ms` of it left after a pause) and the bar that shows it running out."""
        ms = int(self._seconds.value() * 1000) if ms is None else int(ms)
        self._hold_total = max(1, int(total or ms)) if bar else 0
        self._hold_left = None
        self._hold.start(max(1, ms))
        if bar and self._progress_box.isChecked():
            self._bar_timer.start()
        self._update_bar()

    def _end_hold(self) -> None:
        self._hold.stop()
        self._bar_timer.stop()
        self._hold_left, self._hold_total = None, 0
        self._stage.set_progress(None)

    def _progress(self) -> float | None:
        if self._hold_total <= 0 or not self._progress_box.isChecked():
            return None
        left = self._hold.remainingTime() if self._hold.isActive() else self._hold_left
        if left is None or left < 0:
            return None
        return min(1.0, max(0.0, 1.0 - left / float(self._hold_total)))

    def _update_bar(self) -> None:
        self._stage.set_progress(self._progress())

    # ------------------------------------------------------------ playing and stepping
    def is_playing(self) -> bool:
        return self._playing

    def play(self) -> None:
        if not self._items:
            return
        if self._pos >= len(self._items) - 1 and not self._loop.isChecked() and self._shown_key is not None:
            self._pos = 0          # started again at the end: from the top
            self._playing = True
            self._show_current()
        else:
            self._playing = True
            if self._waiting is None and self._shown_key is not None:
                if self._hold_left is not None and self._hold_total > 0:   # carry on from where the pause was
                    self._begin_hold(self._hold_left, total=self._hold_total)
                else:
                    self._begin_hold()
        self._sync_buttons()
        self._music_sync()

    def pause(self) -> None:
        left = self._hold.remainingTime() if self._hold.isActive() else None
        self._playing = False
        self._hold.stop()
        self._bar_timer.stop()
        self._hold_left = left if (left is not None and left >= 0 and self._hold_total > 0) else None
        self._update_bar()
        self._sync_buttons()
        self._music_sync()

    def toggle_play(self) -> None:
        if self._playing:
            self.pause()
            self._stage.set_overlay(self._caption_text(), self._counter_text())
        else:
            self.play()
        self._stage.setFocus()

    def step(self, direction: int) -> bool:
        """Go to the next (1) or previous (-1) photo. At the end of a show that does not loop it stops and says so; returns whether it moved."""
        self._end_hold()
        target = show.step(self._pos, len(self._items), direction, self._loop.isChecked())
        if target is None:
            if direction > 0 and self._items:
                self.pause()
                self._stage.set_message("End of the slideshow: Start over, or press Space")
            return False
        self._pos = target
        self._show_current()
        self._stage.setFocus()
        return True

    def go_to(self, position: int) -> None:
        if self._items:
            self._end_hold()
            self._pos = min(max(position, 0), len(self._items) - 1)
            self._show_current()

    def leave(self) -> None:
        """The page is closed (another view opened): stop playing, leave full screen and drop what was queued."""
        self._leave_fullscreen()
        self.pause()
        self._music.stop()
        if self._loader is not None:
            self._loader.forget_waiting()
        self._waiting = None

    def shutdown(self) -> None:
        """The window is closing: stop the worker thread."""
        self._leave_fullscreen()
        self.pause()
        self._music.shutdown()
        if self._maker is not None and self._maker.isRunning():
            self._maker.wait(15000)
        loader, self._loader = self._loader, None
        if loader is not None:
            loader.stop()
            loader.wait(3000)

    # ------------------------------------------------------------ full screen
    def is_fullscreen(self) -> bool:
        return self._fullscreen is not None

    def toggle_fullscreen(self) -> None:
        if self._fullscreen is None:
            self._enter_fullscreen()
        else:
            self._leave_fullscreen()

    def _enter_fullscreen(self) -> None:
        host = _FullscreenHost()
        host.closed.connect(self._leave_fullscreen)
        host.layout().addWidget(self._stage)
        self._fullscreen = host
        host.showFullScreen()
        self._stage.show()
        self._stage.set_cursor_hiding(True)
        self._stage.setFocus()
        self._sync_buttons()
        QTimer.singleShot(400, self._upgrade)

    def _upgrade(self) -> None:
        """The stage changed size (full screen): ask for the photo on screen again at the size it needs now."""
        if self._shown_key is not None and self._items and self._waiting is None:
            wanted = self._size()
            if wanted > self._shown_size:
                self._request((self._shown_key[0], wanted, self._shown_key[2]))

    def _leave_fullscreen(self) -> None:
        host = self._fullscreen
        if host is None:
            return
        self._fullscreen = None
        self._stage_holder.addWidget(self._stage)
        self._stage.show()
        self._stage.set_cursor_hiding(False)
        host.hide()
        host.deleteLater()
        self._stage.setFocus()
        self._sync_buttons()

    # ------------------------------------------------------------ the controls
    def _sync_buttons(self) -> None:
        self._play_btn.setIcon(self._icon("pause" if self._playing else "play"))
        self._play_btn.setToolTip("Pause (Space)" if self._playing else "Play (Space)")
        has = bool(self._items)
        for button in (self._restart_btn, self._previous_btn, self._play_btn, self._next_btn, self._full_btn, self._choose_btn):
            button.setEnabled(has or button is self._choose_btn and bool(self._all_items))

    def _on_source_changed(self, _index=None) -> None:
        if self._loading:
            return
        self._save_settings()
        self.reload_items()
        self._stage.setFocus()

    def _on_option_changed(self, _value=None) -> None:
        if self._loading:
            return
        self._save_settings()
        sender = self.sender()
        if sender is self._shuffle and self._items:
            keep = self.current_path()
            self.reload_items_keeping(keep)
        elif sender is self._edits and self._items:
            self._failed.clear()
            self._shown_key = None
            self._show_current()
            if self._playing:
                self._end_hold()
        elif sender is self._progress_box:
            if self._progress_box.isChecked() and self._playing and self._hold.isActive():
                self._bar_timer.start()
            self._update_bar()
        elif sender is self._captions and self._items:
            self._stage.set_overlay(self._caption_text(), self._counter_text())
        elif sender is self._seconds and self._playing and self._waiting is None and self._shown_key is not None:
            self._begin_hold()
        self._stage.setFocus()

    def reload_items_keeping(self, path: str | None) -> None:
        """Rebuild the order (after Shuffle changed) and stay on the same photo."""
        playing = self._playing
        self._order = show.order(len(self._items), self._shuffle.isChecked(), first=next((i for i, (p, _c) in enumerate(self._items) if p == path), None))
        self._pos = 0 if self._shuffle.isChecked() else next((i for i, (p, _c) in enumerate(self._items) if p == path), 0)
        self._end_hold()
        if playing and self._shown_key is not None:
            self._begin_hold()
        self._prefetch()

    # ------------------------------------------------------------ the music
    def _fill_music_combo(self, keep: str | None = None) -> None:
        self._music_combo.blockSignals(True)
        self._music_combo.clear()
        for choice, label in music.choices():
            self._music_combo.addItem(label, choice)
        if keep is not None:
            self._music_combo.setCurrentIndex(max(0, self._music_combo.findData(keep)))
        self._music_combo.blockSignals(False)

    def _select_music(self, choice: str) -> None:
        self._music_combo.blockSignals(True)
        self._music_combo.setCurrentIndex(max(0, self._music_combo.findData(choice)))
        self._music_combo.blockSignals(False)
        self._apply_music_choice()

    def music_choice(self) -> str:
        return self._music_combo.currentData() or music.OFF

    def _apply_music_choice(self) -> None:
        """Make the player play what the drop-down names. A built-in piece that has not been made yet is made on a worker thread first (a few seconds, once)."""
        choice = self.music_choice()
        self._remove_music_btn.setEnabled(choice.startswith("user:"))
        self._music_status.setText("")
        if choice == music.OFF:
            self._music.set_track(None)
            return
        path = music.path_for(choice)
        if path is not None:
            self._music.set_track(path)
            self._music_sync()
            return
        if choice.startswith("builtin:"):
            self._music_pending = choice
            self._music_status.setText("Making the music...")
            self._maker = music_player.BuiltinMaker(choice, self)
            self._maker.made.connect(self._on_music_made)
            self._maker.start()
        else:
            self._music.set_track(None)
            self._music_status.setText("That song is not there any more.")

    def _on_music_made(self, choice: str, path: str, error: str) -> None:
        if choice != self.music_choice():
            return
        self._music_pending = None
        if path:
            self._music_status.setText("")
            self._music.set_track(path)
            self._music_sync()
        else:
            self._music_status.setText(f"The music could not be made: {error}")

    def _music_sync(self) -> None:
        """Music plays while the slideshow plays, waits while it is paused."""
        if self.music_choice() == music.OFF:
            self._music.stop()
        elif self._playing:
            self._music.play()
        else:
            self._music.pause()

    def _on_music_changed(self, _index=None) -> None:
        if self._loading:
            return
        self._save_settings()
        self._apply_music_choice()
        self._stage.setFocus()

    def _on_volume_changed(self, value: int) -> None:
        self._music.set_volume(value)
        if not self._loading:
            self._save_volume_timer.start()

    def import_music(self, paths: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
        """Add these .wav and .mp3 files to the list and choose the first. -> (the names added, [(path, why not)])."""
        added, refused = music.import_files(paths)
        if added:
            self._fill_music_combo(f"user:{added[0]}")
            self._save_settings()
            self._apply_music_choice()
        return added, refused

    def _on_add_music(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(self, "Add music", "", "Music (*.wav *.mp3)")
        if not paths:
            return
        added, refused = self.import_music(paths)
        if refused:
            QMessageBox.warning(self, "Add music", "\n".join(f"{os.path.basename(p)}: {why}" for p, why in refused))
        if added:
            self._music_status.setText(f"Added {len(added)} song{'s' if len(added) != 1 else ''}.")

    def remove_music(self, choice: str) -> bool:
        if not choice.startswith("user:") or not music.remove_user_track(choice.split(":", 1)[1]):
            return False
        self._fill_music_combo(music.OFF if self.music_choice() == choice else self.music_choice())
        self._save_settings()
        self._apply_music_choice()
        return True

    def _on_remove_music(self) -> None:
        choice = self.music_choice()
        if not choice.startswith("user:"):
            return
        name = choice.split(":", 1)[1]
        if QMessageBox.question(self, "Remove music", f"Take {name} out of the list? EFAS's copy is deleted; the file you added it from is not touched.") == QMessageBox.StandardButton.Yes:
            self.remove_music(choice)

    # ------------------------------------------------------------ the video
    def export_items(self) -> list[tuple[str, str]]:
        """The photos of the show in the order they are shown, with their captions."""
        return [self._items[i] for i in self._order]

    def make_export_dialog(self):
        from .slideshow_export_dialog import SlideshowExportDialog

        return SlideshowExportDialog(self.export_items(), self._db_path, float(self._seconds.value()), self._transition.currentData(), self._captions.isChecked(),
                                     self._edits.isChecked(), self.music_choice(), self._volume.value(), self)

    def export_video(self) -> None:
        if not self._items:
            self._music_status.setText("There are no photos to put in a video.")
            return
        self.pause()
        self.make_export_dialog().exec()

    def _on_key(self, event: QKeyEvent) -> None:
        if self.handle_key(event):
            event.accept()

    def handle_key(self, event: QKeyEvent) -> bool:
        key = event.key()
        if key == Qt.Key.Key_Space:
            self.toggle_play()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_PageDown, Qt.Key.Key_N):
            self.step(1)
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_PageUp, Qt.Key.Key_P):
            self.step(-1)
        elif key == Qt.Key.Key_Home:
            self.restart()
        elif key == Qt.Key.Key_X:
            self.leave_out_current()
        elif key == Qt.Key.Key_End:
            self.go_to(len(self._items) - 1)
        elif key in (Qt.Key.Key_F, Qt.Key.Key_F11):
            self.toggle_fullscreen()
        elif key == Qt.Key.Key_Escape:
            if self._fullscreen is None:
                return False
            self._leave_fullscreen()
        elif key == Qt.Key.Key_C:
            self._captions.toggle()
        else:
            return False
        return True
