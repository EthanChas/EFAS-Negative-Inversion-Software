"""The icons beside the panels' names: loaded from the .svg files in assets/icon (Lucide, ISC licence; see tools/import_icons.py), never drawn in code.

A file is an ordinary line icon with stroke="currentColor"; loading it swaps that for the colour wanted (so the icons follow the theme) and renders it at the screen's
pixel ratio. Each (icon, size, colour) is made once and kept."""

import os
from pathlib import Path

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QGuiApplication, QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from ...theme.tokens import THEME

ICON_DIR = Path(__file__).resolve().parents[2] / "assets" / "icon"

# a panel's title -> the icon file (without .svg)
BY_TITLE = {
    "Library": "library", "Tagging": "tags", "Tags": "tag", "Presets": "wand-sparkles", "Snapshots": "camera", "Versions": "copy", "History": "history",
    "Export": "download", "Exposure": "sun", "White Balance": "thermometer-sun", "Negative": "film", "Crop & Rotate": "crop", "Color": "palette",
    "Contrast": "contrast", "Dust & Scratches": "eraser", "AI Dust Detection": "bot", "Flat Field": "layout-grid", "Error marking": "triangle-alert",
    "Print Response": "chart-spline", "Shadows & Highlights": "sun-moon", "Sharpening": "focus", "Tone Curve": "spline", "Watermark": "stamp",
    "Local Contrast": "scan-line", "Lab Look": "printer", "Color Mixer": "swatch-book", "Color Toning": "droplets", "Masking": "venetian-mask", "Chroma Denoise": "audio-waveform", "Finishing": "frame",
}
# the tool rail's tabs -> the icon file
BY_TAB = {"negative": "film", "correction": "crop", "exposure": "sun", "color": "palette", "detail": "focus", "watermark": "stamp", "metadata": "id-card", "plugins": "puzzle"}
# icons used by name elsewhere
OTHER = {"dropper": "pipette"}
NAMES = frozenset(BY_TITLE.values()) | frozenset(BY_TAB.values()) | frozenset(OTHER.values())

_cache: dict[tuple, QImage] = {}   # images, not pixmaps: a pixmap that outlives the application crashes Qt on some platforms when the program exits


def _ratio() -> float:
    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    return max(1.0, min(3.0, screen.devicePixelRatio())) if screen is not None else 1.0


def _render(name: str, size: int, colour: str, ratio: float) -> QImage:
    image = QImage()
    try:
        data = (ICON_DIR / f"{name}.svg").read_text(encoding="utf-8").replace("currentColor", colour)
    except OSError:
        return image
    renderer = QSvgRenderer(QByteArray(data.encode("utf-8")))
    if not renderer.isValid():
        return image
    side = round(size * ratio)
    image = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    image.setDevicePixelRatio(ratio)
    return image


def pixmap(name: str | None, size: int = 16, colour: str | None = None) -> QPixmap:
    """The icon `name` as a pixmap `size` points square in `colour` (the theme's secondary text colour when None); a null pixmap when there is no such file."""
    if not name:
        return QPixmap()
    colour = colour or THEME.text_secondary
    ratio = _ratio()
    key = (name, size, colour, ratio)
    if key not in _cache:
        _cache[key] = _render(name, size, colour, ratio)
    image = _cache[key]
    return QPixmap() if image.isNull() else QPixmap.fromImage(image)


def for_title(title: str, size: int = 16, colour: str | None = None) -> QPixmap:
    return pixmap(BY_TITLE.get(title), size, colour)


def for_tab(key: str, size: int = 18, colour: str | None = None) -> QPixmap:
    return pixmap(BY_TAB.get(key), size, colour)
