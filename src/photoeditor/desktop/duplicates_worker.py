"""Background thread for the duplicate finder, so comparing a large library never freezes the window."""

from PyQt6.QtCore import QThread, pyqtSignal

from ..features.library import duplicates


class DuplicatesWorker(QThread):
    progress = pyqtSignal(str, float)
    done = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, infos: list, similarity: str | None, cache_dir: str | None):
        super().__init__()
        self._infos = infos
        self._similarity = similarity
        self._cache_dir = cache_dir
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            groups = duplicates.find_duplicates(self._infos, self._similarity, self._cache_dir, self.progress.emit, lambda: self._cancel)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.done.emit([] if self._cancel else groups)
