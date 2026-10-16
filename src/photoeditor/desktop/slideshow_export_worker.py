"""Makes the slideshow into an MP4 on a worker thread: each photo is made with its saved edits (or as the scan is) at the video's size and handed to features/slideshow/video.py."""
import dataclasses

from PyQt6.QtCore import QThread, pyqtSignal

from ..features.persistence import edit_store
from ..features.slideshow import music, video
from .export_worker import render_slide


class SlideshowExportWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished_all = pyqtSignal(object)

    def __init__(self, items: list[tuple[str, str]], out_path: str, options: video.ExportOptions, edited: bool, music_choice: str, db_path: str, parent=None):
        super().__init__(parent)
        self._items = list(items)
        self._out_path = out_path
        self._options = options
        self._edited = edited
        self._music_choice = music_choice
        self._db_path = db_path
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        summary = {"path": None, "slides": 0, "failed": [], "cancelled": False, "error": "", "backend": "", "audio": False, "seconds": 0.0}
        conn = edit_store.connect(self._db_path)
        try:
            options = dataclasses.replace(self._options)
            note = ""
            try:
                options.music = music.path_for(self._music_choice, make=True)   # a built-in piece is made now if it never was
            except Exception as exc:
                options.music, note = None, f"The music could not be made ({type(exc).__name__}), so the video has none."
            size = max(options.size)
            summary = video.export_slideshow(self._items, self._out_path, options, lambda path: render_slide(path, conn, size, self._edited),
                                             progress=lambda done, total, name: self.progress.emit(done, total, name), cancelled=lambda: self._cancel)
            summary["note"], summary["music_wanted"] = note, self._music_choice != music.OFF
        except Exception as exc:
            summary["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            conn.close()
        self.finished_all.emit(summary)
