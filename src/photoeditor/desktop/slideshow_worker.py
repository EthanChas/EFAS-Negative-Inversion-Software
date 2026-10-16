"""Makes the slideshow's pictures on a worker thread: each photo with its saved edits applied (or as the scan is), at the size the screen needs, as a QImage."""
import queue

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage

from ..features.persistence import edit_store
from .export_worker import render_slide


def to_qimage(pixels: np.ndarray) -> QImage:
    """An independent QImage (it owns its bytes) of 8-bit RGB pixels."""
    pixels = np.ascontiguousarray(pixels[..., :3])
    h, w = pixels.shape[:2]
    return QImage(pixels.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()


class SlideLoader(QThread):
    """Takes requests (path, size, edited) one at a time, newest first, and answers with loaded(path, size, edited, image or None, error). Its own database connection."""

    loaded = pyqtSignal(str, int, bool, object, str)

    def __init__(self, db_path: str, parent=None):
        super().__init__(parent)
        self._db_path = db_path
        self._queue: queue.LifoQueue = queue.LifoQueue()
        self._wanted: set = set()
        self._stop = False

    def request(self, path: str, size: int, edited: bool) -> None:
        """Ask for a picture; asking again for one already waiting does nothing. A later request is made before an earlier one (the slide on screen beats the ones ahead)."""
        key = (path, size, edited)
        if key in self._wanted:
            return
        self._wanted.add(key)
        self._queue.put(key)

    def forget_waiting(self) -> None:
        """Drop everything still queued (the person jumped elsewhere)."""
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        self._wanted.clear()

    def stop(self) -> None:
        self._stop = True
        self._queue.put(None)

    def run(self) -> None:
        conn = edit_store.connect(self._db_path)
        try:
            while not self._stop:
                key = self._queue.get()
                if key is None or self._stop:
                    break
                path, size, edited = key
                image, error = None, ""
                try:
                    image = to_qimage(render_slide(path, conn, size, edited))
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                self._wanted.discard(key)
                self.loaded.emit(path, size, edited, image, error)
        finally:
            conn.close()
