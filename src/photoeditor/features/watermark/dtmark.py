"""darktable's Watermark module: how big a marker is, where it goes and how it is drawn. Ported from darktable's iop/watermark.c (process()) and common/utility.c (the marker's size).

Everything is measured on the picture the module is given - here the cropped picture, before any border - as darktable does:

  * the marker's own size (`dimension`) is a whole number of pixels: the SVG's width and height rounded (or, when the file states none, its viewBox fitted into a 32767 pixel square), or
    the PNG's pixel size;
  * Scale on picks a base: the image (the marker's longer side against the picture's width or height, by which of the marker's sides is longer), the larger or the smaller border of the
    picture, the picture's height, or - Advanced - any picture dimension against either marker dimension. The Scale slider (a percentage, 1-500) multiplies that;
  * the marker is placed by its 3 x 3 Alignment, which keeps the box round it clear of the edge when it is turned, and then moved by the X and Y offset, which are shares of the base width
    and height;
  * it is turned about the middle of its box, clockwise for a positive Rotation;
  * an SVG is drawn from its viewBox into the marker's size (kept in proportion, centred), with 3 units of room round it for text that runs outside; a picture is scaled and turned smoothly;
  * the result is blended as darktable does: alpha = marker alpha x opacity, out = (1 - alpha) x picture + opacity x marker colour.

No Qt UI imports (an SVG is drawn with Qt's SVG renderer, started on its own when there is no application).
"""

import math
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Mapping

import numpy as np

from . import logoimage, variables
from .logic import Part

BASES = {"image": "image", "larger": "larger border", "smaller": "smaller border", "height": "height", "advanced": "advanced options"}   # Scale on (darktable's "scale on")
IMAGE_SIDES = {"width": "image width", "height": "image height", "larger": "larger image border", "smaller": "smaller image border"}     # "scale marker to"
MARKER_SIDES = {"width": "marker width", "height": "marker height"}                                                                     # "scale marker reference"
ALIGNMENTS = ("top left", "top", "top right", "left", "centre", "right", "bottom left", "bottom", "bottom right")                       # index 0-8, row by row
DEFAULT_BASE, DEFAULT_IMAGE_SIDE, DEFAULT_MARKER_SIDE, DEFAULT_ALIGNMENT = "image", "larger", "width", 4
SCALE_RANGE = (1.0, 500.0)      # percent
OFFSET_RANGE = (-1.0, 1.0)
ROTATE_RANGE = (-180.0, 180.0)
_PAD_UNITS = 3.0                # the room round an SVG for text that runs outside its box (darktable: 3 x the scale, in pixels)
_FALLBACK_SIZE = 32767          # the square a marker without a stated size is fitted into
_UNITS = {"": 1.0, "px": 1.0, "pt": 4.0 / 3.0, "pc": 16.0, "mm": 96.0 / 25.4, "cm": 96.0 / 2.54, "in": 96.0}   # librsvg's 96 dpi
_LENGTH = re.compile(r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*([a-zA-Z%]*)\s*$")
_ROOT = re.compile(r"<svg\b[^>]*>", re.S | re.I)
_ATTR = re.compile(r"""\b([a-zA-Z:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def _length(value: str | None) -> float | None:
    """An absolute SVG length in pixels; None when there is none (missing, a percentage, or not a length)."""
    if not value:
        return None
    m = _LENGTH.match(value)
    if not m:
        return None
    unit = m.group(2).lower()
    if unit not in _UNITS:
        return None
    number = float(m.group(1)) * _UNITS[unit]
    return number if number > 0 else None


def _root_attributes(text: str) -> dict[str, str]:
    m = _ROOT.search(text)
    if not m:
        return {}
    return {name: double or single for name, double, single in _ATTR.findall(m.group(0))}


def _view_box(attrs: Mapping[str, str]) -> tuple[float, float, float, float] | None:
    raw = attrs.get("viewBox") or attrs.get("viewbox")
    if not raw:
        return None
    try:
        x, y, w, h = (float(p) for p in re.split(r"[\s,]+", raw.strip()))
    except ValueError:
        return None
    return (x, y, w, h) if w > 0 and h > 0 else None


@lru_cache(maxsize=64)
def svg_dimension(text: str) -> tuple[int, int]:
    """The marker's size in pixels, as darktable counts it (dt_get_svg_dimension): the stated width and height, rounded; one of them and the viewBox's shape; or, without a size, the
    viewBox fitted into a 32767 pixel square. A drawing with neither is 512 pixels square."""
    attrs = _root_attributes(text)
    width, height = _length(attrs.get("width")), _length(attrs.get("height"))
    box = _view_box(attrs)
    if width and height:
        return max(1, _round_half_up(width)), max(1, _round_half_up(height))
    if box and (width or height):
        aspect = box[2] / box[3]
        if width:
            height = width / aspect
        else:
            width = height * aspect
        return max(1, _round_half_up(width)), max(1, _round_half_up(height))
    if box:
        k = _FALLBACK_SIZE / max(box[2], box[3])
        return max(1, _round_half_up(box[2] * k)), max(1, _round_half_up(box[3] * k))
    return 512, 512


def raster_dimension(path: str) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as im:
        return im.size


def dimension(path: str, svg_vars: Mapping[str, str] | None = None) -> tuple[int, int]:
    """The marker's size (darktable's `dimension`; 0 counts as 1)."""
    if logoimage.is_svg(path):
        w, h = svg_dimension(_svg_text(path, svg_vars))
    else:
        w, h = raster_dimension(path)
    return max(1, int(w)), max(1, int(h))


def _svg_text(path: str, svg_vars: Mapping[str, str] | None) -> str:
    text = logoimage.read_svg(path)
    if svg_vars is not None and "$(" in text:
        text = variables.expand(text, svg_vars, variables.xml_escape)
    return text


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# the layout: the numbers of process()


@dataclass(frozen=True)
class Layout:
    scale: float        # the marker's pixels per unit of its own size
    wbase: float        # what a whole X offset is a share of (pixels)
    hbase: float        # ... and a whole Y offset
    width: float        # the marker's size on the picture, for placing it (not the same as dimension x scale only when the sides are not in proportion)
    height: float
    tx: float           # the box's top-left corner on the picture, offsets included
    ty: float
    angle: float        # radians, clockwise
    bb_width: float     # the box round the turned marker
    bb_height: float

    @property
    def centre(self) -> tuple[float, float]:
        """Where the marker turns: the middle of its box, on the picture."""
        return self.tx + self.width / 2.0, self.ty + self.height / 2.0

    def box(self) -> tuple[int, int, int, int]:
        """(x, y, width, height) of the box round the marker as it is turned - what is dragged on the picture."""
        cx, cy = self.centre
        return _round_half_up(cx - self.bb_width / 2.0), _round_half_up(cy - self.bb_height / 2.0), max(1, _round_half_up(self.bb_width)), max(1, _round_half_up(self.bb_height))


def offset_bases(base: str, iw: float, ih: float) -> tuple[float, float]:
    """(wbase, hbase): the sizes the X and Y offsets are shares of. The picture's width and height, except on the larger and smaller border, where both are that border."""
    if base == "larger":
        return (max(iw, ih),) * 2
    if base == "smaller":
        return (min(iw, ih),) * 2
    return float(iw), float(ih)


def layout(dim: tuple[int, int], iw: float, ih: float, *, base: str = DEFAULT_BASE, image_side: str = DEFAULT_IMAGE_SIDE, marker_side: str = DEFAULT_MARKER_SIDE,
           scale_percent: float = 100.0, alignment: int = DEFAULT_ALIGNMENT, xoffset: float = 0.0, yoffset: float = 0.0, rotate: float = 0.0) -> Layout:
    """Where and how big a marker of size `dim` is on a picture iw by ih, with darktable's settings. See the module's text."""
    dw, dh = float(max(1, dim[0])), float(max(1, dim[1]))
    uscale = scale_percent / 100.0
    larger = max(dw, dh)
    wbase, hbase = offset_bases(base, iw, ih)
    from_width = marker_side != "height"

    # the scale: the marker's pixels per unit
    if base == "larger":
        scale = max(iw, ih) / larger
    elif base == "smaller":
        scale = min(iw, ih) / larger
    elif base == "height":
        scale = ih / dh
    elif base == "advanced":
        sbase = {"width": iw, "height": ih, "larger": max(iw, ih)}.get(image_side, min(iw, ih))
        scale = sbase / dw if from_width else sbase / dh
    else:
        scale = iw / dw if dw > dh else ih / dh
    scale *= uscale

    # the marker's size on the picture, for laying it out: one side from the base, the other in proportion
    if base == "larger":
        calc, height_from_width = max(iw, ih) * uscale, dw > dh
    elif base == "smaller":
        calc, height_from_width = min(iw, ih) * uscale, dw > dh
    elif base == "height":
        calc, height_from_width = ih * uscale, False
    elif base == "advanced":
        calc = {"width": iw, "height": ih, "larger": max(iw, ih)}.get(image_side, min(iw, ih)) * uscale
        height_from_width = from_width
    elif dw > dh:
        calc, height_from_width = iw * uscale, True
    else:
        calc, height_from_width = ih * uscale, False
    if height_from_width:
        width, height = calc, dh * (calc / dw)
    else:
        height, width = calc, dw * (calc / dh)

    # the box round the turned marker, and the corner or edge it is aligned to
    angle = math.radians(rotate)
    bb_w = abs(width * math.cos(angle)) + abs(height * math.sin(angle))
    bb_h = abs(width * math.sin(angle)) + abs(height * math.cos(angle))
    bx, by = bb_w / 2.0 - width / 2.0, bb_h / 2.0 - height / 2.0
    alignment = int(alignment) if 0 <= int(alignment) < 9 else DEFAULT_ALIGNMENT
    row, col = divmod(alignment, 3)
    ty = by if row == 0 else (ih / 2.0 - height / 2.0) if row == 1 else ih - height - by
    tx = bx if col == 0 else (iw / 2.0 - width / 2.0) if col == 1 else iw - width - bx
    tx += xoffset * wbase
    ty += yoffset * hbase
    return Layout(scale, wbase, hbase, width, height, tx, ty, angle, bb_w, bb_h)


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# drawing


def _matrix(lay: Layout, x0: int, y0: int) -> np.ndarray:
    """The 3 x 3 matrix from the marker's own units to the window whose top-left corner is (x0, y0) on the picture: the box's place, the turn about its middle, then the scale."""
    def move(dx: float, dy: float) -> np.ndarray:
        return np.array([[1.0, 0.0, dx], [0.0, 1.0, dy], [0.0, 0.0, 1.0]])

    c, s = math.cos(lay.angle), math.sin(lay.angle)
    turn = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    grow = np.array([[lay.scale, 0.0, 0.0], [0.0, lay.scale, 0.0], [0.0, 0.0, 1.0]])
    cx, cy = lay.width / 2.0, lay.height / 2.0
    return move(-x0, -y0) @ move(lay.tx, lay.ty) @ move(cx, cy) @ turn @ move(-cx, -cy) @ grow


def _window(lay: Layout, dim: tuple[int, int], iw: int, ih: int, room: float) -> tuple[int, int, int, int] | None:
    """The part of the picture the drawn marker (with `room` units round it) can touch: (x0, y0, x1, y1), None when none of it is on the picture."""
    m = _matrix(lay, 0, 0)
    corners = np.array([[-room, -room, 1.0], [dim[0] + room, -room, 1.0], [dim[0] + room, dim[1] + room, 1.0], [-room, dim[1] + room, 1.0]]).T
    xs, ys = (m @ corners)[0], (m @ corners)[1]
    x0, y0 = max(0, int(math.floor(xs.min()))), max(0, int(math.floor(ys.min())))
    x1, y1 = min(iw, int(math.ceil(xs.max()))), min(ih, int(math.ceil(ys.max())))
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def _draw_svg(text: str, dim: tuple[int, int], lay: Layout, window: tuple[int, int, int, int]) -> np.ndarray:
    """RGBA float32 (premultiplied, 0-255) of the SVG in the window."""
    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import QImage, QPainter, QTransform

    x0, y0, x1, y1 = window
    w, h = x1 - x0, y1 - y0
    renderer = logoimage._renderer_from_text(text)
    box = renderer.viewBoxF()
    vw, vh = (box.width(), box.height()) if box.width() > 0 and box.height() > 0 else (float(dim[0]), float(dim[1]))
    fit = min(dim[0] / vw, dim[1] / vh)           # the viewBox into the marker's size, in proportion and centred (rsvg_handle_render_document)
    ox, oy = (dim[0] - vw * fit) / 2.0, (dim[1] - vh * fit) / 2.0
    image = QImage(w, h, QImage.Format.Format_RGBA8888_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    m = _matrix(lay, x0, y0)
    painter.setTransform(QTransform(m[0, 0], m[1, 0], m[0, 1], m[1, 1], m[0, 2], m[1, 2]))
    renderer.render(painter, QRectF(ox, oy, vw * fit, vh * fit))
    painter.end()
    stride = image.bytesPerLine()
    raw = np.frombuffer(image.constBits().asstring(stride * h), dtype=np.uint8).reshape(h, stride)[:, : w * 4].reshape(h, w, 4)
    return raw.astype(np.float32)


@lru_cache(maxsize=2)
def _raster_source(path: str, mtime: float) -> np.ndarray:
    from PIL import Image

    with Image.open(path) as im:
        rgba = np.asarray(im.convert("RGBA"), dtype=np.float32).copy()
    rgba[:, :, :3] *= rgba[:, :, 3:4] / 255.0
    return rgba


def _draw_picture(path: str, lay: Layout, window: tuple[int, int, int, int]) -> np.ndarray:
    import cv2

    x0, y0, x1, y1 = window
    source = _raster_source(path, os.path.getmtime(path))
    sh, sw = source.shape[:2]
    m = _matrix(lay, x0, y0)
    if lay.scale < 1.0:   # a picture made much smaller is first averaged down (a plain warp would skip pixels)
        nw, nh = max(1, round(sw * lay.scale)), max(1, round(sh * lay.scale))
        source = cv2.resize(source, (nw, nh), interpolation=cv2.INTER_AREA)
        m = m @ np.diag([sw / nw, sh / nh, 1.0])
    return cv2.warpAffine(source, m[:2], (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))


def marker_part(path: str, svg_vars: Mapping[str, str] | None, iw: int, ih: int, *, base: str = DEFAULT_BASE, image_side: str = DEFAULT_IMAGE_SIDE, marker_side: str = DEFAULT_MARKER_SIDE,
                scale_percent: float = 100.0, alignment: int = DEFAULT_ALIGNMENT, xoffset: float = 0.0, yoffset: float = 0.0, rotate: float = 0.0, opacity: float = 1.0) -> Part:
    """The marker as a part of the watermark, laid out and drawn on an iw by ih picture the way darktable's Watermark module does; the part's box is the whole marker, on or off the picture.
    ValueError / OSError when the file cannot be read."""
    svg = logoimage.is_svg(path)
    text = _svg_text(path, svg_vars) if svg else ""
    dim = svg_dimension(text) if svg else raster_dimension(path)
    dim = (max(1, dim[0]), max(1, dim[1]))
    lay = layout(dim, iw, ih, base=base, image_side=image_side, marker_side=marker_side, scale_percent=scale_percent, alignment=alignment, xoffset=xoffset, yoffset=yoffset, rotate=rotate)
    whole = lay.box()
    window = _window(lay, dim, iw, ih, _PAD_UNITS if svg else 0.0)
    if window is None:
        return Part("logo", np.zeros((1, 1, 3), np.float32), np.zeros((1, 1), np.float32), max(0, min(iw - 1, whole[0])), max(0, min(ih - 1, whole[1])), whole)
    arr = _draw_svg(text, dim, lay, window) if svg else _draw_picture(path, lay, window)
    k = np.float32(max(0.0, min(1.0, opacity)))
    return Part("logo", np.ascontiguousarray(arr[:, :, :3]) * k, np.ascontiguousarray(arr[:, :, 3] / 255.0) * k, window[0], window[1], whole)
