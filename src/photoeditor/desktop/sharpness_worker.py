"""Grading a roll's sharpness in the background (features/sharpgrade): one frame at a time, so the window stays usable and a long roll can be stopped."""

import os

from PyQt6.QtCore import QThread, pyqtSignal

from ..features.sharpgrade import logic
from ..features.sharpgrade.processor import load_for_grading


class SharpnessWorker(QThread):
    progress = pyqtSignal(int, int, str)       # frames done, frames in all, the one being read
    graded = pyqtSignal(str, str, float)       # path, severity, score
    frame_failed = pyqtSignal(str, str)        # path, why it could not be read
    all_done = pyqtSignal(bool)                # True when it was stopped before the end

    def __init__(self, paths: list[str]):
        super().__init__()
        self._paths = list(paths)
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        total = len(self._paths)
        for i, path in enumerate(self._paths):
            if self._stop:
                self.all_done.emit(True)
                return
            self.progress.emit(i, total, os.path.basename(path))
            try:
                result = logic.grade_sharpness(load_for_grading(path, logic.MAX_DIM))
            except Exception as exc:    # one unreadable file must not stop the roll
                self.frame_failed.emit(path, f"{type(exc).__name__}: {exc}")
                continue
            self.graded.emit(path, result.severity, result.score)
        self.progress.emit(total, total, "")
        self.all_done.emit(False)
