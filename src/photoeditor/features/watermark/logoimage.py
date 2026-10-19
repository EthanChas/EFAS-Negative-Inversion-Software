"""Loading a watermark marker: an SVG (drawn sharp at whatever size it is needed) or a raster picture (PNG, JPEG, WebP...). Premultiplied sprites out.

An SVG is read as text first, so its $(NAME) variables can be filled in before it is drawn (see variables.py): the text, colour and font chosen for the marker, the film's details, the date.
The drawn sprite is kept by the text it was made from, so a change of any variable draws it again and nothing else does."""

import os
import sys
from functools import lru_cache
from typing import Mapping

import numpy as np

from . import variables

LOGO_EXTENSIONS = (".svg", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")
DIALOG_FILTER = "Markers (*.svg *.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;SVG (*.svg);;Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)"
MAX_SVG_BYTES = 5_000_000
FULL_SPRITE_PIXELS = 12_000_000   # a marker (after its turn) with more pixels than this is not drawn whole: only the part that is on the picture is (marker_window)
MAX_DRAWN_SIDE = 2_000_000    # a marker is never drawn bigger than this many pixels along its longer side
_FALLBACK_SIZE = 512
_app = None

# how the size slider is read: the marker's longer side as a share of the picture's ...
SCALE_ON = {"fit": "Fit the picture", "short": "Shorter side", "long": "Longer side", "width": "Width", "height": "Height"}   # ... shorter side / longer side; or the marker's width / height as a share of the picture's width / height
DEFAULT_SCALE_ON = "short"


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


def _natural_size(renderer) -> tuple[float, float]:
    """The drawing's own width and height, exactly where Qt's whole-number size would round them (a strip that is 100 by 5.5 is not 100 by 5): the viewBox's size when it is the same shape as
    the size the file states (to within that rounding), otherwise the stated size."""
    base, box = renderer.defaultSize(), renderer.viewBoxF()
    stated = base.width() > 0 and base.height() > 0
    boxed = box.width() > 0 and box.height() > 0
    if stated and boxed:
        tolerance = 0.5 / base.width() + 0.5 / base.height() + 1e-6
        same_shape = abs((box.width() / box.height()) / (base.width() / base.height()) - 1.0) <= tolerance
        return (float(box.width()), float(box.height())) if same_shape else (float(base.width()), float(base.height()))
    if boxed:
        return float(box.width()), float(box.height())
    return (float(base.width()), float(base.height())) if stated else (float(_FALLBACK_SIZE), float(_FALLBACK_SIZE))


def svg_aspect(path: str) -> float:
    """Width over height of an SVG's drawing."""
    width, height = _natural_size(_svg_renderer(path))
    return width / height


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


@lru_cache(maxsize=32)
def _svg_size(text: str) -> tuple[float, float]:
    return _natural_size(_renderer_from_text(text))


@lru_cache(maxsize=8)
def _svg_sprite(text: str, long_side: int) -> tuple[np.ndarray, np.ndarray]:
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage, QPainter

    renderer = _renderer_from_text(text)
    bw, bh = _svg_size(text)
    k = long_side / max(bw, bh)
    w, h = max(1, round(bw * k)), max(1, round(bh * k))
    image = QImage(w, h, QImage.Format.Format_RGBA8888_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter)
    painter.end()
    stride = image.bytesPerLine()
    raw = np.frombuffer(image.constBits().asstring(stride * h), dtype=np.uint8).reshape(h, stride)[:, : w * 4].reshape(h, w, 4)
    arr = raw.astype(np.float32)
    return np.ascontiguousarray(arr[:, :, :3]), np.ascontiguousarray(arr[:, :, 3] / 255.0)


@lru_cache(maxsize=8)
def _raster_sprite(path: str, mtime: float, long_side: int) -> tuple[np.ndarray, np.ndarray]:
    import cv2
    from PIL import Image

    with Image.open(path) as im:
        rgba = np.asarray(im.convert("RGBA"), dtype=np.float32)
    h, w = rgba.shape[:2]
    k = long_side / max(h, w)
    rgba[:, :, :3] *= rgba[:, :, 3:4] / 255.0
    size = (max(1, round(w * k)), max(1, round(h * k)))
    rgba = cv2.resize(rgba, size, interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_LINEAR)
    return np.ascontiguousarray(rgba[:, :, :3]), np.ascontiguousarray(rgba[:, :, 3] / 255.0)


def _raster_size(path: str) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as im:
        return im.size


def _long_side(width: float, height: float, mode: str, px: int) -> int:
    """The marker's longer side in pixels, from the size asked for: `px` is that longer side itself ("long"), or the width or the height the marker is to have."""
    longer = max(width, height)
    if mode == "width":
        return max(1, round(px * longer / width))
    if mode == "height":
        return max(1, round(px * longer / height))
    return px


def marker_sprite(path: str, mode: str, px: int, opacity: float, svg_variables_: Mapping[str, str] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """The marker as (premultiplied RGB float32 0-255, alpha float32 0-1), faded by `opacity`. `px` is its longer side in pixels, or - with mode "width" or "height" - the width or height it is to
    have. An SVG has the variables in `svg_variables_` filled in first (None: its file is drawn as it is)."""
    px = max(4, int(px))
    if is_svg(path):
        text = read_svg(path)
        if svg_variables_ is not None and "$(" in text:
            text = variables.expand(text, svg_variables_, variables.xml_escape)
        width, height = _svg_size(text)
        rgb, alpha = _svg_sprite(text, max(4, _long_side(width, height, mode, px)))
    else:
        width, height = _raster_size(path)
        rgb, alpha = _raster_sprite(path, os.path.getmtime(path), max(4, _long_side(width, height, mode, px)))
    return rgb * np.float32(opacity), alpha * np.float32(opacity)


def natural_size(path: str, svg_variables_: Mapping[str, str] | None = None) -> tuple[float, float]:
    """The marker's own width and height (an SVG after its variables are filled in)."""
    if is_svg(path):
        text = read_svg(path)
        if svg_variables_ is not None and "$(" in text:
            text = variables.expand(text, svg_variables_, variables.xml_escape)
        return _svg_size(text)
    width, height = _raster_size(path)
    return float(width), float(height)


def drawn_size(natural: tuple[float, float], mode: str, px: int) -> tuple[int, int]:
    """(width, height) in pixels of a marker of this natural size asked for in this way (see marker_sprite), as whole pixels."""
    width, height = natural
    k = min(_long_side(width, height, mode, max(4, int(px))), MAX_DRAWN_SIDE) / max(width, height)
    return max(1, round(width * k)), max(1, round(height * k))


def turned_size(width: int, height: int, degrees: float) -> tuple[int, int]:
    """The size of the box round a width by height marker turned clockwise by `degrees`."""
    import math

    rad = math.radians(degrees)
    c, s = abs(math.cos(rad)), abs(math.sin(rad))
    return int(math.ceil(width * c + height * s - 1e-9)), int(math.ceil(width * s + height * c - 1e-9))


@lru_cache(maxsize=2)
def _raster_source(path: str, mtime: float) -> np.ndarray:
    from PIL import Image

    with Image.open(path) as im:
        rgba = np.asarray(im.convert("RGBA"), dtype=np.float32).copy()
    rgba[:, :, :3] *= rgba[:, :, 3:4] / 255.0
    return rgba


def marker_window(path: str, svg_variables_: Mapping[str, str] | None, size: tuple[int, int], degrees: float, centre: tuple[float, float], window: tuple[int, int, int, int],
                  opacity: float) -> tuple[np.ndarray, np.ndarray]:
    """Only the part of a big marker that is on the picture, as (premultiplied RGB float32 0-255, alpha float32 0-1) the size of `window` (x0, y0, x1, y1 on the picture). The marker is
    `size` (width, height) pixels, turned clockwise by `degrees` about `centre` (on the picture). Nothing bigger than the window is ever made, so a marker many times the size of the
    picture costs no more than the picture does."""
    import math

    wx0, wy0, wx1, wy1 = window
    ww, wh = wx1 - wx0, wy1 - wy0
    width, height = size
    if is_svg(path):
        from PyQt6.QtCore import QRectF, Qt
        from PyQt6.QtGui import QImage, QPainter

        text = read_svg(path)
        if svg_variables_ is not None and "$(" in text:
            text = variables.expand(text, svg_variables_, variables.xml_escape)
        renderer = _renderer_from_text(text)
        image = QImage(ww, wh, QImage.Format.Format_RGBA8888_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.translate(centre[0] - wx0, centre[1] - wy0)
        painter.rotate(degrees)
        painter.translate(-width / 2.0, -height / 2.0)
        renderer.render(painter, QRectF(0.0, 0.0, float(width), float(height)))
        painter.end()
        stride = image.bytesPerLine()
        raw = np.frombuffer(image.constBits().asstring(stride * wh), dtype=np.uint8).reshape(wh, stride)[:, : ww * 4].reshape(wh, ww, 4)
        arr = raw.astype(np.float32)
    else:
        import cv2

        source = _raster_source(path, os.path.getmtime(path))
        sh, sw = source.shape[:2]
        sx, sy = width / sw, height / sh
        c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
        matrix = np.array([[c * sx, -s * sy, centre[0] - wx0 - (c * width / 2.0 - s * height / 2.0)],
                           [s * sx, c * sy, centre[1] - wy0 - (s * width / 2.0 + c * height / 2.0)]], dtype=np.float64)
        arr = cv2.warpAffine(source, matrix, (ww, wh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    return np.ascontiguousarray(arr[:, :, :3]) * np.float32(opacity), np.ascontiguousarray(arr[:, :, 3] / 255.0) * np.float32(opacity)


def logo_sprite(path: str, long_side: int, opacity: float) -> tuple[np.ndarray, np.ndarray]:
    """The logo with its longer side `long_side` pixels, as (premultiplied RGB float32 0-255, alpha float32 0-1), faded by `opacity`."""
    return marker_sprite(path, "long", long_side, opacity)


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
