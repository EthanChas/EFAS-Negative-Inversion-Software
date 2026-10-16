"""The Workbench's live folder: asks the folder watch (features/livefolder/logic.py) for news a few times a second and says when photos arrive."""
import os
import time

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ..features.livefolder.logic import LiveWatch

POLL_MS = 700   # a photo shows about two polls after its file stops growing


class LiveFolder(QObject):
    arrived = pyqtSignal(list)   # the paths of photos that have just landed and are complete, oldest first

    def __init__(self, parent: QObject | None = None, interval_ms: int = POLL_MS):
        super().__init__(parent)
        self._interval = interval_ms
        self._watch: LiveWatch | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.poll)

    def start(self, folder: str) -> bool:
        """Begin watching `folder` (what is in it now is not news). False when it is not a folder."""
        if not folder or not os.path.isdir(folder):
            return False
        self._watch = LiveWatch(folder)
        self._timer.start(self._interval)
        return True

    def stop(self) -> None:
        self._timer.stop()
        self._watch = None

    def running(self) -> bool:
        return self._watch is not None

    def folder(self) -> str:
        return self._watch.folder if self._watch is not None else ""

    def ignore(self, paths: list[str]) -> None:
        """Files the editor itself put in the folder (a set-aside retake) are not news."""
        if self._watch is not None:
            self._watch.ignore(paths)

    def poll(self) -> list[str]:
        """Look now (the timer does this; the tests do it too). A big folder that is slow to read is looked at less often."""
        if self._watch is None:
            return []
        started = time.perf_counter()
        paths = self._watch.poll()
        self._timer.setInterval(max(self._interval, int((time.perf_counter() - started) * 4000)))
        if paths:
            self.arrived.emit(paths)
        return paths
