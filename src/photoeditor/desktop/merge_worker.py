"""Background thread for merging scans, so the window stays responsive while several large RAW files are decoded."""

from PyQt6.QtCore import QThread, pyqtSignal

from ..features.densitometry import merge, merge_job


class MergeWorker(QThread):
    progress = pyqtSignal(int, int, str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, mode: str, paths: list[str], times, out_path: str, align: bool):
        super().__init__()
        self._args = (mode, paths, times, out_path, align)

    def run(self) -> None:
        try:
            self.done.emit(merge_job.run(*self._args, progress=self.progress.emit))
        except merge.MergeError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
