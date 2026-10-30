"""The icons beside the panels' names: loaded from the .svg files in assets/icon (Lucide, ISC licence; see tools/import_icons.py), never drawn in code.

A file is an ordinary line icon with stroke="currentColor"; loading it swaps that for the colour wanted (so the icons follow the theme) and renders it at the screen's
pixel ratio. Each (icon, size, colour) is made once and kept."""

import os
from pathlib import Path

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QGuiApplication, QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from ...theme import runtime
from ...theme.tokens import THEME

ICON_DIR = Path(__file__).resolve().parents[2] / "assets" / "icon"

# a panel's title -> the icon file (without .svg)
BY_TITLE = {
    "Library": "library", "Tagging": "tags", "Tags": "tag", "Presets": "wand-sparkles", "Snapshots": "camera", "Versions": "copy", "History": "history",
    "Export": "download", "Exposure": "sun", "White Balance": "thermometer-sun", "Negative": "film", "Crop & Rotate": "crop", "Color": "palette",
    "Contrast": "contrast", "Dust & Scratches": "eraser", "AI Dust Detection": "bot", "Flat Field": "layout-grid", "Error marking": "triangle-alert",
    "Print Response": "chart-spline", "Shadows & Highlights": "sun-moon", "Sharpening": "focus", "Tone Curve": "spline", "Watermark": "stamp",
    "Local Contrast": "scan-line", "Lab Look": "printer", "Color Mixer": "swatch-book", "Color Toning": "droplets", "Edge Bleed": "scan", "Edge Color": "circle", "Masks": "venetian-mask", "Chroma Denoise": "audio-waveform", "Finishing": "frame",
}
# the tool rail's tabs -> the icon file
BY_TAB = {"active": "power", "negative": "film", "correction": "crop", "exposure": "sun", "color": "palette", "detail": "focus", "watermark": "stamp", "metadata": "id-card", "plugins": "puzzle"}
# icons used by name elsewhere
OTHER = {"dropper": "pipette", "folder": "folder", "folder_open": "folder-open", "play": "play", "pause": "pause", "previous": "skip-back", "next": "skip-forward", "fullscreen": "maximize", "restart": "rotate-ccw", "search": "search"}
# EFAS's own icons for the masks and Retouch, in the same style (not part of the Lucide import)
OWN = frozenset({"mask-circle", "mask-ellipse", "mask-path", "mask-brush", "mask-gradient", "mask-group", "mask-eye", "mask-eye-off", "mask-edit", "mask-invert", "mask-trash", "mask-dust",
                 "mask-hair", "mask-scratch", "mask-manual", "mask-clone", "mask-heal", "mask-blur", "mask-fill", "mask-source", "mask-cut", "mask-paste", "mask-layers", "mask-levels", "mask-ai", "tone-equalizer", "color-balance", "diffuse", "canister"})
OWN_TITLES = {"Retouch": "mask-heal", "Tone Equalizer": "tone-equalizer", "Color Balance RGB": "color-balance", "Diffuse or Sharpen": "diffuse", "Canister Watermark": "canister"}
NAMES = frozenset(BY_TITLE.values()) | frozenset(BY_TAB.values()) | frozenset(OTHER.values())

_cache: dict[tuple, QImage] = {}   # images, not pixmaps: a pixmap that outlives the application crashes Qt on some platforms when the program exits


def _ratio() -> float:
    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    return max(1.0, min(3.0, screen.devicePixelRatio())) if screen is not None else 1.0


def _theme_file(name: str) -> Path | None:
    """The theme's own picture for this icon (an .svg, else a .png, named like the program's icon in the theme's icons folder), if it has one."""
    folder = THEME.icons_dir
    if not folder:
        return None
    for extension in (".svg", ".png"):
        path = Path(folder) / f"{name}{extension}"
        if path.is_file():
            return path
    return None


def _render(name: str, size: int, colour: str, ratio: float) -> QImage:
    image = QImage()
    own = _theme_file(name)
    side = round(size * ratio * THEME.get("icon_size_percent") / 100)
    if own is not None and own.suffix == ".png":
        picture = QImage(str(own))
        if picture.isNull():
            return image
        picture = picture.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        picture.setDevicePixelRatio(ratio)
        return picture
    try:
        data = (own or ICON_DIR / f"{name}.svg").read_text(encoding="utf-8").replace("currentColor", colour)
    except OSError:
        return image
    renderer = QSvgRenderer(QByteArray(data.encode("utf-8")))
    if not renderer.isValid():
        return image
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
    colour = THEME.get("icon_color") if THEME.get("icon_color_mode") == "all" else (colour or THEME.text_secondary)
    ratio = _ratio()
    key = (name, size, colour, ratio, THEME.icons_dir, THEME.get("icon_size_percent"))
    if key not in _cache:
        _cache[key] = _render(name, size, colour, ratio)
    image = _cache[key]
    return QPixmap() if image.isNull() else QPixmap.fromImage(image)


def refresh() -> None:
    """A theme was put in force: icons are made again (its own pictures, its colour)."""
    _cache.clear()


runtime.HOOKS.append(refresh)


def for_title(title: str, size: int = 16, colour: str | None = None) -> QPixmap:
    return pixmap(BY_TITLE.get(title) or OWN_TITLES.get(title), size, colour)


def for_tab(key: str, size: int = 18, colour: str | None = None) -> QPixmap:
    return pixmap(BY_TAB.get(key), size, colour)
