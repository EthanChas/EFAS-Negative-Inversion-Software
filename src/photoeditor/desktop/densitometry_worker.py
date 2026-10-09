"""Background thread that decodes the linear scan used for measurement, so opening the scientific panels never freezes the window."""

from PyQt6.QtCore import QThread, pyqtSignal

from ..features.densitometry import processor
from ..features.densitometry.linear import LinearScan
from ..features.open_image.processor import make_preview_rgb


class LinearScanWorker(QThread):
    done = pyqtSignal(str, object)
    failed = pyqtSignal(str, str)

    def __init__(self, path: str, picture, transfer: str):
        super().__init__()
        self._path = path
        self._picture = picture
        self._transfer = transfer

    def run(self) -> None:
        try:
            scan = processor.linear_scan(self._path, self._picture, self._transfer)
            self.done.emit(self._path, LinearScan(make_preview_rgb(scan.rgb), scan.info))
        except Exception as exc:
            self.failed.emit(self._path, str(exc))
