from PyQt6.QtCore import QEventLoop, QThread, pyqtSignal

from ..features.browse.processor import get_or_make_thumbnail_bytes


class ThumbnailLoader(QThread):
    """Generates tile-grid thumbnails off the UI thread, one at a time, so
    opening a folder with hundreds of photos never freezes the window.
    Reads/writes the on-disk cache (cache_dir) first, so re-opening the same
    folder later is instant instead of re-decoding every RAW file again."""

    thumb_ready = pyqtSignal(str, object)

    def __init__(self, paths: list[str], cache_dir: str | None = None):
        super().__init__()
        self.paths = paths
        self.cache_dir = cache_dir

    def run(self) -> None:
        for path in self.paths:
            self.thumb_ready.emit(path, get_or_make_thumbnail_bytes(self.cache_dir, path))


class _CallWorker(QThread):
    def __init__(self, fn):
        super().__init__()
        self._fn = fn
        self.result = None
        self.error: BaseException | None = None

    def run(self) -> None:
        try:
            self.result = self._fn()
        except BaseException as exc:
            self.error = exc


def run_blocking(fn):
    """Runs fn on a worker thread but doesn't return until it's done - the
    caller still reads as synchronous, yet the UI thread keeps spinning its
    event loop meanwhile (user input excluded), so things like the loading
    spinner keep animating instead of freezing with the window."""
    worker = _CallWorker(fn)
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    worker.start()
    if not worker.isFinished():
        loop.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    worker.wait()
    if worker.error is not None:
        raise worker.error
    return worker.result


class FlatFieldWorker(QThread):
    """Builds a flat-field gain map from every frame of a folder ("Auto (Roll)")
    off the UI thread - decoding a roll's worth of frames takes a while."""

    progress = pyqtSignal(int, int, str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, paths: list[str]):
        super().__init__()
        self._paths = list(paths)
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        from ..features.flatfield.processor import gain_from_roll

        try:
            gain = gain_from_roll(self._paths, self.progress.emit, lambda: self._cancel)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.done.emit(gain)
