"""Loading a watermark logo: an SVG (drawn sharp at whatever size it is needed) or a raster picture (PNG, JPEG, WebP...). Premultiplied sprites out."""

import os
import sys
from functools import lru_cache

import numpy as np

LOGO_EXTENSIONS = (".svg", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")
DIALOG_FILTER = "Logos (*.svg *.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;SVG (*.svg);;Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)"
MAX_SVG_BYTES = 5_000_000
MAX_SIDE = 4096
_FALLBACK_SIZE = 512
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


def _svg_renderer(path: str):
    from PyQt6.QtSvg import QSvgRenderer

    if os.path.getsize(path) > MAX_SVG_BYTES:
        raise ValueError("That SVG is larger than 5 MB.")
    _ensure_qt()
    renderer = QSvgRenderer(path)
    if not renderer.isValid():
        raise ValueError("That SVG could not be read.")
    return renderer


def svg_aspect(path: str) -> float:
    """Width over height of an SVG's drawing."""
    size = _svg_renderer(path).defaultSize()
    return size.width() / size.height() if size.width() > 0 and size.height() > 0 else 1.0


@lru_cache(maxsize=8)
def _svg_sprite(path: str, mtime: float, long_side: int) -> tuple[np.ndarray, np.ndarray]:
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage, QPainter

    renderer = _svg_renderer(path)
    base = renderer.defaultSize()
    bw, bh = (base.width(), base.height()) if base.width() > 0 and base.height() > 0 else (_FALLBACK_SIZE, _FALLBACK_SIZE)
    k = min(long_side, MAX_SIDE) / max(bw, bh)
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


def logo_sprite(path: str, long_side: int, opacity: float) -> tuple[np.ndarray, np.ndarray]:
    """The logo with its longer side `long_side` pixels, as (premultiplied RGB float32 0-255, alpha float32 0-1), faded by `opacity`."""
    mtime = os.path.getmtime(path)
    long_side = max(4, int(long_side))
    rgb, alpha = (_svg_sprite if is_svg(path) else _raster_sprite)(path, mtime, long_side)
    return rgb * np.float32(opacity), alpha * np.float32(opacity)


def check(path: str) -> str | None:
    """Why this file cannot be used as a logo, in words for the user; None if it can."""
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
