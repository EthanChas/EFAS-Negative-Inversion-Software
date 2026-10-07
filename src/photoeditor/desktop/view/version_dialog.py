import platform
import sys

from PyQt6.QtCore import QT_VERSION_STR, PYQT_VERSION_STR, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget

from ... import __version__
from ...features.updates import logic, processor
from ...theme.tokens import THEME
from ..update_worker import UpdateCheckWorker, UpdateDownloadWorker

_PRIVACY = ("The editor works offline and sends no data out. The only request it makes is to the GitHub releases page, to see whether a newer "
            "version exists. Your privacy is a right, and it is respected.")

_running: list = []


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


class VersionDialog(QDialog):
    """Info > Version: what is installed, a check for a newer one, and the update itself (download, swap the .exe, restart)."""

    def __init__(self, parent: QWidget | None = None, release=None, auto_start: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Version")
        self.setMinimumWidth(480)
        self.restart_requested = False
        self._release = None
        self._check: UpdateCheckWorker | None = None
        self._download: UpdateDownloadWorker | None = None
        self._staged = ""

        outer = QVBoxLayout(self)
        outer.setSpacing(THEME.space_lg)
        title = QLabel(f"<b>EFAS Negative Inversion Software</b><br>Version {__version__}")
        outer.addWidget(title)
        system = f"{platform.system()} {platform.release()}, Python {platform.python_version()}, Qt {QT_VERSION_STR}, PyQt {PYQT_VERSION_STR}"
        detail = QLabel(system + ("" if getattr(sys, "frozen", False) else " (running from source)"))
        detail.setStyleSheet(f"color: {THEME.text_secondary};")
        outer.addWidget(detail)
        privacy = QLabel(_PRIVACY)
        privacy.setWordWrap(True)
        privacy.setStyleSheet(f"color: {THEME.text_secondary};")
        outer.addWidget(privacy)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        outer.addWidget(self._status)
        self._notes = QPlainTextEdit()
        self._notes.setReadOnly(True)
        self._notes.setMaximumHeight(160)
        self._notes.hide()
        outer.addWidget(self._notes)
        self._bar = QProgressBar()
        self._bar.hide()
        outer.addWidget(self._bar)

        row = QHBoxLayout()
        row.addStretch(1)
        self._check_btn = QPushButton("Check for Updates")
        self._check_btn.clicked.connect(self._start_check)
        row.addWidget(self._check_btn)
        self._update_btn = QPushButton("Update and Restart")
        self._update_btn.clicked.connect(self._on_update)
        self._update_btn.hide()
        row.addWidget(self._update_btn)
        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.reject)
        row.addWidget(self._close_btn)
        outer.addLayout(row)

        if release is not None:
            self._show_release(release)
            if auto_start and processor.can_self_update():
                self._on_update()

    def _busy(self) -> bool:
        return self._download is not None and self._download.isRunning()

    def _start_check(self) -> None:
        self._status.setText("Checking GitHub for a newer version...")
        self._check_btn.setEnabled(False)
        self._check = UpdateCheckWorker()
        self._check.found.connect(self._on_checked)
        self._check.failed.connect(self._on_check_failed)
        self._check.start()

    def _on_check_failed(self, message: str) -> None:
        self._check_btn.setEnabled(True)
        self._status.setText(message)

    def _on_checked(self, release) -> None:
        self._check_btn.setEnabled(True)
        if release is None or not logic.is_newer(release.version, logic.parse_version(__version__)):
            self._status.setText(f"You are up to date (version {__version__}).")
            return
        self._show_release(release)

    def _show_release(self, release) -> None:
        self._release = release
        self._status.setText(f"Version {logic.version_text(release.version)} is available. You have {__version__}.")
        if release.notes:
            self._notes.setPlainText(release.notes)
            self._notes.show()
        self._check_btn.hide()
        if processor.can_self_update() and release.asset_url:
            size = f" ({human_size(release.asset_size)})" if release.asset_size else ""
            self._update_btn.setText(f"Update and Restart{size}")
        else:
            self._update_btn.setText("Open the Download Page")
        self._update_btn.show()

    def _on_update(self) -> None:
        release = self._release
        if release is None:
            return
        if not (processor.can_self_update() and release.asset_url):
            QDesktopServices.openUrl(QUrl(release.page_url))
            return
        self._update_btn.setEnabled(False)
        self._close_btn.setText("Cancel")
        self._status.setText("Downloading the update...")
        self._bar.setRange(0, 0)
        self._bar.show()
        self._staged = processor.staging_path(release)
        self._download = UpdateDownloadWorker(release, self._staged)
        self._download.progress.connect(self._on_progress)
        self._download.done.connect(self._on_downloaded)
        self._download.failed.connect(self._on_download_failed)
        self._download.start()

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self._bar.setRange(0, 1000)
            self._bar.setValue(int(done * 1000 / total))
            self._status.setText(f"Downloading the update... {human_size(done)} of {human_size(total)}")

    def _on_download_failed(self, message: str) -> None:
        self._bar.hide()
        self._update_btn.setEnabled(True)
        self._close_btn.setText("Close")
        self._status.setText(message)

    def _on_downloaded(self, path: str) -> None:
        self._status.setText("Update downloaded. Restarting...")
        try:
            processor.start_swap(path)
        except Exception as exc:
            self._on_download_failed(f"The update could not be started: {exc}")
            return
        self.restart_requested = True
        self.accept()

    def reject(self) -> None:
        if self._busy():
            self._download.cancel()
        super().reject()

    def done(self, result: int) -> None:
        for worker in (self._check, self._download):
            if worker is not None and worker.isRunning():
                for name in ("found", "failed", "progress", "done"):
                    signal = getattr(worker, name, None)
                    if signal is not None:
                        signal.disconnect()
                _running.append(worker)
                worker.finished.connect(lambda w=worker: _running.remove(w))
        super().done(result)
