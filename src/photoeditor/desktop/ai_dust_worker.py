"""AI dust analysis of one photo on a worker thread: a full-resolution pass of the model takes seconds to a minute on a CPU, far too long for
the window's own thread. Progress is reported tile by tile; the result is cached on disk (features/aidust/logic.py)."""

from PyQt6.QtCore import QThread, pyqtSignal

from ..features.aidust import logic as ai


class AiDustWorker(QThread):
    progress = pyqtSignal(int, int)  # tiles done, tiles in all
    finished_ok = pyqtSignal(object)  # the worker itself, so its key and result can be read: .path, .inverted, .mono, .prob
    failed = pyqtSignal(object, str)  # the worker, a message

    def __init__(self, path: str, raw, inverted: bool, mono: bool):
        super().__init__()
        self.path, self.raw, self.inverted, self.mono = path, raw, inverted, mono
        self.prob = None
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            self.prob = ai.probability(
                self.path, self.raw, self.inverted, self.mono, progress=lambda done, total: self.progress.emit(done, total), cancelled=lambda: self._cancel
            )
        except Exception as exc:  # a missing runtime or a corrupt model must not take the editor down
            self.failed.emit(self, f"{type(exc).__name__}: {exc}")
            return
        if self.prob is not None and not self._cancel:
            self.finished_ok.emit(self)
