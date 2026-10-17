"""Background threads for the tether window: the live picture, and one-off jobs (connecting, a lens move, a capture), so the window never waits on the camera."""

import threading

from PyQt6.QtCore import QThread, pyqtSignal

from ..features.tether.backend import TetherError


def _message(exc: BaseException) -> str:
    return str(exc) if isinstance(exc, TetherError) else f"{type(exc).__name__}: {exc}"


class LiveWorker(QThread):
    """Takes each new live picture from the session, makes what is shown, and hands it to the window. It waits for the window to say it has drawn one (ack) before making the
    next, so a slow window drops pictures and never builds up a queue of old ones."""

    frame = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, session):
        super().__init__()
        self._session = session
        self._stop = False
        self._drawn = threading.Event()
        self._drawn.set()

    def stop(self) -> None:
        self._stop = True
        self._drawn.set()

    def ack(self) -> None:
        self._drawn.set()

    def run(self) -> None:
        last = -1
        try:
            while not self._stop:
                if not self._drawn.wait(0.25) or self._stop:
                    continue
                seq, picture = self._session.step(last)
                if picture is None:
                    self.msleep(4)
                    continue
                last = seq
                self._drawn.clear()
                self.frame.emit(picture)
        except BaseException as exc:   # the camera went away, or a frame could not be made: say so, and stop
            if not self._stop:
                self.failed.emit(_message(exc))


class JobWorker(QThread):
    """Runs one function off the window's thread and says how it went."""

    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            result = self._fn()
        except BaseException as exc:
            self.failed.emit(_message(exc))
            return
        self.done.emit(result)
