"""Focus peaking on a worker thread: the analysis (features/focuspeaking) takes a few tenths of a second on a big picture, which would stall
the window if it ran on the UI thread."""

from PyQt6.QtCore import QThread, pyqtSignal

from ..features.focuspeaking.logic import level_map


class PeakingWorker(QThread):
    done = pyqtSignal(int, object)

    def __init__(self, request: int, pixels):
        super().__init__()
        self._request = request
        self._pixels = pixels

    def run(self) -> None:
        try:
            levels = level_map(self._pixels)
        except Exception:
            levels = None
        self.done.emit(self._request, levels)
