"""Background thread for the light check, so reading a few dozen RAW files never freezes the window."""

from PyQt6.QtCore import QThread, pyqtSignal

from ..features.lightcheck import bare, capture, film


class LightCheckWorker(QThread):
    progress = pyqtSignal(int, int, str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    stopped = pyqtSignal()

    def __init__(self, mode: str, paths: list[str], reference: str = ""):
        super().__init__()
        self._mode, self._paths, self._reference = mode, paths, reference
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        # the readers are looked up here, not bound as defaults, so a test can stand in for the camera files
        common = dict(progress=self.progress.emit, cancelled=lambda: self._cancel, loader=capture.load_planes, exif_reader=capture.read_exif)
        try:
            result = film.analyse(self._paths, self._reference, **common) if self._mode == "film" else bare.analyse(self._paths, **common)
        except capture.Cancelled:
            self.stopped.emit()
            return
        except capture.CaptureError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.done.emit(result)
