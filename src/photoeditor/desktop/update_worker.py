"""Background threads for the update check and download, so the window never waits on the network."""

from PyQt6.QtCore import QThread, pyqtSignal

from ..features.updates import processor


class UpdateCheckWorker(QThread):
    """Emits found(release) when a release exists (the caller compares versions), or failed(message)."""

    found = pyqtSignal(object)
    failed = pyqtSignal(str)

    def run(self) -> None:
        try:
            self.found.emit(processor.fetch_latest())
        except processor.UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"The update check failed: {exc}")


class UpdateDownloadWorker(QThread):
    progress = pyqtSignal(int, int)
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, release, dest: str):
        super().__init__()
        self._release = release
        self._dest = dest
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            path = processor.download(self._release, self._dest, self.progress.emit, lambda: self._cancel)
        except processor.UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"The download failed: {exc}")
        else:
            self.done.emit(path)
