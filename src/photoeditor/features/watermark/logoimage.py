"""Reading a watermark marker: an SVG (drawn sharp at whatever size it is needed) or a raster picture (PNG, JPEG, WebP...). How a marker is sized, placed and drawn is dtmark.py.

An SVG is read as text first, so its $(NAME) variables can be filled in before it is drawn (see variables.py): the text, colour and font chosen for the marker, the film's details, the date."""

import os
import sys

from . import variables

LOGO_EXTENSIONS = (".svg", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")
DIALOG_FILTER = "Markers (*.svg *.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;SVG (*.svg);;Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)"
MAX_SVG_BYTES = 5_000_000
_app = None


def is_svg(path: str) -> bool:
    return path.lower().endswith(".svg")


def usable(path: str) -> bool:
    return bool(path) and path.lower().endswith(LOGO_EXTENSIONS) and os.path.isfile(path)


def _ensure_qt() -> None:
    """Drawing an SVG needs Qt's graphics classes. In the app they exist already; from the command line, make a headless one."""
    global _app
    from PyQt6.QtGui import QGuiApplication

    if QGuiApplication.instance() is None:
        if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _app = QGuiApplication([])


def read_svg(path: str) -> str:
    """The SVG file's text. ValueError (a message for the person) when it is too big or is not text."""
    if os.path.getsize(path) > MAX_SVG_BYTES:
        raise ValueError("That SVG is larger than 5 MB.")
    with open(path, "rb") as f:
        raw = f.read()
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("That SVG could not be read.")


def _renderer_from_text(text: str):
    from PyQt6.QtCore import QByteArray
    from PyQt6.QtSvg import QSvgRenderer

    _ensure_qt()
    renderer = QSvgRenderer(QByteArray(text.encode("utf-8")))
    if not renderer.isValid():
        raise ValueError("That SVG could not be read.")
    return renderer


def _svg_renderer(path: str):
    return _renderer_from_text(read_svg(path))


def svg_variables(path: str) -> set[str]:
    """Which of the marker variables an SVG file uses ({"WATERMARK_TEXT", "WATERMARK_COLOR", ...}): what the Marker controls of the panel are for. Empty for a picture or an unreadable file."""
    if not is_svg(path):
        return set()
    try:
        text = read_svg(path)
    except (OSError, ValueError):
        return set()
    return {name for name in MARKER_VARIABLES if variables.uses(text, name)}


MARKER_VARIABLES = ("WATERMARK_TEXT", "WATERMARK_COLOR", "WATERMARK_FONT_FAMILY", "WATERMARK_FONT_STYLE", "WATERMARK_FONT_WEIGHT")


_font_files: dict[str, str] = {}


def svg_font_family(font: str) -> str:
    """The font family name to write into an SVG for a stored font choice: "" is the generic sans-serif, a family name is used as it is, and a font file the person picked is given to
    Qt (once) so its family can be drawn."""
    if not font:
        return "sans-serif"
    from . import fonts

    if not fonts.is_font_file(font):
        return font
    if font not in _font_files:
        family = ""
        try:
            from PyQt6.QtGui import QFontDatabase

            _ensure_qt()
            found = QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(font))
            family = found[0] if found else ""
        except Exception:
            family = ""
        _font_files[font] = family or (fonts._read_name(font) or ("sans-serif", ""))[0]
    return _font_files[font]


def check(path: str) -> str | None:
    """Why this file cannot be used as a marker, in words for the user; None if it can."""
    if not os.path.isfile(path):
        return "That file does not exist."
    if not path.lower().endswith(LOGO_EXTENSIONS):
        return "Choose an SVG, PNG, JPEG, WebP, BMP or TIFF picture."
    try:
        if is_svg(path):
            _svg_renderer(path)
        else:
            from PIL import Image

            with Image.open(path) as im:
                im.verify()
    except ValueError as e:
        return str(e)
    except Exception:
        return "That file could not be read as a picture."
    return None
