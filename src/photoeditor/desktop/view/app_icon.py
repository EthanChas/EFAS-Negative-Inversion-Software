"""The EFAS logo as the app's icon: the window, the taskbar and the title bar."""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap

APP_NAME = "EFAS Negative Inversion Software"
_DIR = Path(__file__).resolve().parents[2] / "assets" / "icon"


def app_icon() -> QIcon:
    return QIcon(str(_DIR / "efas.ico")) if (_DIR / "efas.ico").exists() else QIcon()


def logo_pixmap(size: int) -> QPixmap:
    """The logo scaled to a square of `size` pixels (an empty pixmap if the file is missing)."""
    pix = QPixmap(str(_DIR / "efas-logo.png"))
    if pix.isNull():
        return pix
    return pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
