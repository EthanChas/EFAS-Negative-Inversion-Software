"""Background thread for the roll consistency check, so reading a whole roll never freezes the window."""

from PyQt6.QtCore import QThread, pyqtSignal

from ..features.densitometry import roll_job


class RollCheckWorker(QThread):
    progress = pyqtSignal(int, int, str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, paths: list[str], reference):
        super().__init__()
        self._paths = paths
        self._reference = reference

    def run(self) -> None:
        try:
            self.done.emit(roll_job.run(self._paths, self._reference, self.progress.emit))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
