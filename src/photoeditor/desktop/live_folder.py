"""The hotstack folders' watch: asks the folder watch (features/livefolder/logic.py) for news a few times a second and says when photos arrive."""
import os
import time

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ..features.livefolder.filing import is_under
from ..features.livefolder.logic import LiveWatch

POLL_MS = 700   # a photo shows about two polls after its file stops growing


def _key(folder: str) -> str:
    return os.path.normcase(os.path.abspath(folder))


def outermost(folders: list[str]) -> list[str]:
    """The folders that are not inside another of them (watching an outer folder covers the ones in it), each once."""
    keep: list[str] = []
    for f in folders:
        if f and not any(g != f and is_under(f, g) for g in folders) and _key(f) not in {_key(k) for k in keep}:
            keep.append(f)
    return keep


class LiveFolder(QObject):
    arrived = pyqtSignal(list)   # the paths of photos that have just landed and are complete, oldest first

    def __init__(self, parent: QObject | None = None, interval_ms: int = POLL_MS):
        super().__init__(parent)
        self._interval = interval_ms
        self._wanted: list[str] = []
        self._watches: dict[str, LiveWatch] = {}
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.poll)

    def set_folders(self, folders: list[str]) -> None:
        """Watch exactly these folders (the hotstack ones). A folder that is watched already keeps its watch; a new one starts from what is in it now, so what is there is not news. A
        folder that is not there (a drive that is unplugged) is watched as soon as it is."""
        self._wanted = outermost(list(folders))
        keys = {_key(f) for f in self._wanted}
        self._watches = {k: w for k, w in self._watches.items() if k in keys}
        self._connect_missing()
        if self._wanted:
            self._timer.start(self._interval)
        else:
            self._timer.stop()

    def _connect_missing(self) -> None:
        for folder in self._wanted:
            if _key(folder) not in self._watches and os.path.isdir(folder):
                self._watches[_key(folder)] = LiveWatch(folder)

    def running(self) -> bool:
        """Whether any folder is marked to be watched."""
        return bool(self._wanted)

    def folders(self) -> list[str]:
        return list(self._wanted)

    def folder_of(self, path: str) -> str:
        """The watched folder a photo is in, or an empty string."""
        return next((f for f in self._wanted if is_under(path, f)), "")

    def ignore(self, paths: list[str]) -> None:
        """Files the editor itself put in a folder (a set-aside retake) are not news."""
        for watch in self._watches.values():
            watch.ignore(paths)

    def poll(self) -> list[str]:
        """Look now (the timer does this; the tests do it too). A big folder that is slow to read is looked at less often."""
        if not self._wanted:
            return []
        started = time.perf_counter()
        self._connect_missing()
        paths: list[str] = []
        for watch in self._watches.values():
            paths += watch.poll()
        self._timer.setInterval(max(self._interval, int((time.perf_counter() - started) * 4000)))
        if paths:
            self.arrived.emit(paths)
        return paths
