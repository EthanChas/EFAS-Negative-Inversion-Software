"""Downloading an AI model, because the person asked for it (desktop/view/ai_models_dialog.py): one file, in the background, with progress, kept in EFAS's own folder.

This is the only thing EFAS downloads for the AI mask, it does so only after being asked, and it says where from. The package is checked before it is kept (features/aimask/models.py)."""

import os
import urllib.request

from PyQt6.QtCore import QThread, pyqtSignal

from ..features.aimask import models

CHUNK = 1 << 20


class ModelDownload(QThread):
    progress = pyqtSignal(int, int)        # bytes so far, bytes in all (0 when not told)
    done = pyqtSignal(str)                 # the id of the model that was installed
    failed = pyqtSignal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url
        self._stop = False

    def cancel(self) -> None:
        self._stop = True

    def run(self) -> None:
        os.makedirs(models.models_dir(), exist_ok=True)
        part = os.path.join(models.models_dir(), "download.part")
        try:
            request = urllib.request.Request(self._url, headers={"User-Agent": "EFAS Negative Inversion Software (model download)"})
            with urllib.request.urlopen(request, timeout=30) as response, open(part, "wb") as out:
                total = int(response.headers.get("Content-Length") or 0)
                got = 0
                while True:
                    if self._stop:
                        self.failed.emit("Cancelled.")
                        return
                    block = response.read(CHUNK)
                    if not block:
                        break
                    out.write(block)
                    got += len(block)
                    self.progress.emit(got, total)
            if total and got != total:
                self.failed.emit(f"The download stopped early ({got} of {total} bytes). Try again.")
                return
            self.done.emit(models.install_package(part))
        except ValueError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"The download failed: {exc}")
        finally:
            try:
                os.remove(part)
            except OSError:
                pass
