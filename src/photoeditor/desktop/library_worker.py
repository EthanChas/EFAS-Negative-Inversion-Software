"""Background work for the Lighttable: bringing the library index up to date, and making thumbnails for the grid."""

from collections import OrderedDict

from PyQt6.QtCore import QObject, QRunnable, QThread, QThreadPool, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap

from ..features.browse.processor import get_or_make_thumbnail_bytes
from ..features.library.index import LibraryIndex


class LibraryIndexWorker(QThread):
    """Scans the library folders and reads the EXIF of new and changed files into the index (features/library/index.py)."""

    progress = pyqtSignal(int, int)
    finished_ok = pyqtSignal(int, int, int)

    def __init__(self, roots: list[str], db_path: str | None = None):
        super().__init__()
        self._roots = list(roots)
        self._db_path = db_path
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        index = LibraryIndex(self._db_path)
        try:
            added, changed, removed = index.refresh(
                self._roots, progress=lambda done, total, _path: self.progress.emit(done, total), cancelled=lambda: self._cancel
            )
        finally:
            index.close()
        self.finished_ok.emit(added, changed, removed)


class _ThumbSignals(QObject):
    ready = pyqtSignal(str, object)


class _ThumbTask(QRunnable):
    def __init__(self, path: str, cache_dir: str | None, signals: _ThumbSignals):
        super().__init__()
        self._path, self._cache_dir, self._signals = path, cache_dir, signals

    def run(self) -> None:
        data = get_or_make_thumbnail_bytes(self._cache_dir, self._path)
        image = QImage.fromData(data) if data else QImage()
        self._signals.ready.emit(self._path, image)


class ThumbPool(QObject):
    """Thumbnails for the grid, made a few at a time in the background."""

    thumb_ready = pyqtSignal(str)

    def __init__(self, cache_dir: str | None, keep: int = 800, threads: int = 3, parent: QObject | None = None):
        super().__init__(parent)
        self._cache_dir = cache_dir
        self._keep = keep
        self._pixmaps: OrderedDict[str, QPixmap] = OrderedDict()
        self._pending: set[str] = set()
        self._counter = 0
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(threads)
        self._signals = _ThumbSignals()
        self._signals.ready.connect(self._on_ready)

    def pixmap(self, path: str) -> QPixmap | None:
        pix = self._pixmaps.get(path)
        if pix is not None:
            self._pixmaps.move_to_end(path)
        return pix

    def request(self, path: str) -> None:
        if path in self._pixmaps or path in self._pending:
            return
        self._pending.add(path)
        self._counter += 1
        self._pool.start(_ThumbTask(path, self._cache_dir, self._signals), self._counter)

    def forget(self, path: str) -> None:
        """Drop a thumbnail so it is read again (its edit changed it)."""
        self._pixmaps.pop(path, None)

    def clear_pending(self) -> None:
        self._pool.clear()
        self._pending.clear()

    def _on_ready(self, path: str, image: QImage) -> None:
        self._pending.discard(path)
        if image.isNull():
            return
        self._pixmaps[path] = QPixmap.fromImage(image)
        while len(self._pixmaps) > self._keep:
            self._pixmaps.popitem(last=False)
        self.thumb_ready.emit(path)

    def shutdown(self) -> None:
        self._pool.clear()
        self._pool.waitForDone(5000)
