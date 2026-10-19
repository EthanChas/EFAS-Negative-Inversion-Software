"""Watermarks that are not the canister - a block of text, a logo (SVG or picture) and the camera/lens text on its own, laid over the finished picture."""

import dataclasses
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping

import numpy as np

from . import fonts, library, logoimage
from . import variables as wmvars
from .logic import CREDIT, MARGIN, POSITIONS, Part, _blend

CUSTOM = "custom"
PLACES = {**POSITIONS, CUSTOM: "Custom"}
DEFAULT_TEXT_POSITION = "bottom_right"
DEFAULT_LOGO_POSITION = "bottom_left"
DEFAULT_INFO_POSITION = "bottom_left"
TEXT_SIZE_RANGE = (0.01, 0.15)
LOGO_SIZE_RANGE = (0.03, 0.80)
INFO_SIZE_RANGE = (0.01, 0.10)
CANISTER_SIZE_RANGE = (0.05, 0.95)
LINE_SPACING_RANGE = (0.0, 1.0)
LETTER_SPACING_RANGE = (-0.1, 0.6)
ROTATION_RANGE = (-180.0, 180.0)
OUTLINE_RANGE = (0.0, 1.0)
COLORS = {"white": "White", "black": "Black"}
ALIGNS = {"auto": "Automatic", "left": "Left", "center": "Centre", "right": "Right"}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_OUTLINE_SHARE = 0.12  # an outline of 1.0 is this share of the letter height thick
TEXT_MAX = 300
MARKER_TEXT_MAX = 511    # the text an SVG marker takes (darktable's limit too)


def _num(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return default if number != number else max(low, min(high, number))


def _choice(value: Any, allowed, default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def _color(value: Any, default: str) -> str:
    """white, black or #rrggbb (lower-cased)."""
    if isinstance(value, str):
        if value in COLORS:
            return value
        if _HEX.match(value):
            return value.lower()
    return default


def color_rgb(value: str) -> tuple[int, int, int]:
    if value == "black":
        return 0, 0, 0
    if isinstance(value, str) and _HEX.match(value):
        return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)
    return 255, 255, 255


def _text(value: Any, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


@dataclass(frozen=True)
class Marks:
    # a block of text
    text: str = ""
    text_size: float = 0.04
    text_opacity: float = 0.85
    text_color: str = "white"
    text_position: str = DEFAULT_TEXT_POSITION
    text_shadow: bool = True
    text_font: str = ""
    text_bold: bool = False
    text_italic: bool = False
    text_align: str = "auto"
    text_line_spacing: float = 0.25
    text_letter_spacing: float = 0.0
    text_rotation: float = 0.0
    text_outline: float = 0.0
    text_x: float = 0.5
    text_y: float = 0.9
    # a logo (SVG or picture)
    logo: str = ""
    logo_size: float = 0.18
    logo_opacity: float = 0.9
    logo_position: str = DEFAULT_LOGO_POSITION
    logo_x: float = 0.15
    logo_y: float = 0.9
    logo_rotation: float = 0.0
    logo_scale_on: str = logoimage.DEFAULT_SCALE_ON   # what the size is a share of (logoimage.SCALE_ON)
    # what an SVG marker takes for its $(WATERMARK_TEXT), $(WATERMARK_COLOR), $(WATERMARK_FONT_FAMILY), $(WATERMARK_FONT_STYLE) and $(WATERMARK_FONT_WEIGHT) (darktable's variables)
    logo_text: str = ""
    logo_color: str = "white"
    logo_font: str = ""
    logo_bold: bool = False
    logo_italic: bool = False
    # the canister, once it has been dragged or resized on the picture (-1 / 0 = still where its menus put it)
    canister_x: float = -1.0
    canister_y: float = -1.0
    canister_size: float = 0.0
    # the camera and lens text, on its own (or still beside the canister)
    info_beside: bool = True
    info_credit: bool = True
    info_position: str = DEFAULT_INFO_POSITION
    info_size: float = 0.028
    info_opacity: float = 0.9
    info_color: str = "white"
    info_font: str = ""
    info_bold: bool = False
    info_shadow: bool = True
    info_x: float = 0.15
    info_y: float = 0.93

    def has_text(self) -> bool:
        return bool(self.text.strip())

    def has_logo(self) -> bool:
        return library.resolve(self.logo) is not None

    def has_custom_canister(self) -> bool:
        return self.canister_x >= 0 and self.canister_y >= 0

    def info_alone(self, info: bool, camera: str, lens: str, canister_on: bool) -> bool:
        """Is the camera/lens text drawn by itself (not beside the canister)?"""
        return bool(info and (camera.strip() or lens.strip()) and (not canister_on or not self.info_beside))

    def active(self) -> bool:
        return self.has_text() or self.has_logo()

    def wanted(self, info: bool = False, camera: str = "", lens: str = "", canister_on: bool = False) -> bool:
        """Does anything here need drawing?"""
        return self.active() or self.info_alone(info, camera, lens, canister_on)

    def to_dict(self) -> dict[str, Any]:
        """Only what differs from the defaults, so a photo without marks stores {}."""
        base = Marks()
        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self) if getattr(self, f.name) != getattr(base, f.name)}

    @classmethod
    def from_dict(cls, data: Any) -> "Marks":
        """Always valid: unknown keys are ignored, bad values fall back to the default, numbers are pulled into range."""
        if isinstance(data, Marks):
            return data
        if not isinstance(data, dict):
            return cls()
        d = cls()
        kw: dict[str, Any] = {}
        for f in dataclasses.fields(cls):
            name, default, raw = f.name, getattr(d, f.name), data.get(f.name)
            if name in _RANGES:
                kw[name] = _num(raw, *_RANGES[name], default)
            elif name in _PLACE_FIELDS:
                kw[name] = _choice(raw, PLACES, default)
            elif name in _COLOR_FIELDS:
                kw[name] = _color(raw, default)
            elif name == "text_align":
                kw[name] = _choice(raw, ALIGNS, default)
            elif name == "text":
                kw[name] = _text(raw, TEXT_MAX)
            elif name == "logo_text":
                kw[name] = _text(raw, MARKER_TEXT_MAX)
            elif name == "logo_scale_on":
                kw[name] = _choice(raw, logoimage.SCALE_ON, default)
            elif name in ("logo", "text_font", "info_font", "logo_font"):
                kw[name] = _text(raw, 260)
            elif isinstance(default, bool):
                kw[name] = bool(raw) if raw is not None else default
        out = cls(**kw)
        if out.canister_x < 0 or out.canister_y < 0:
            out = dataclasses.replace(out, canister_x=-1.0, canister_y=-1.0)
        if 0 < out.canister_size < CANISTER_SIZE_RANGE[0]:
            out = dataclasses.replace(out, canister_size=CANISTER_SIZE_RANGE[0])
        return out


_RANGES = {
    "text_size": TEXT_SIZE_RANGE, "text_opacity": (0.0, 1.0), "text_line_spacing": LINE_SPACING_RANGE, "text_letter_spacing": LETTER_SPACING_RANGE,
    "text_rotation": ROTATION_RANGE, "text_outline": OUTLINE_RANGE, "text_x": (0.0, 1.0), "text_y": (0.0, 1.0),
    "logo_size": LOGO_SIZE_RANGE, "logo_opacity": (0.0, 1.0), "logo_x": (0.0, 1.0), "logo_y": (0.0, 1.0), "logo_rotation": ROTATION_RANGE,
    "canister_x": (-1.0, 1.0), "canister_y": (-1.0, 1.0), "canister_size": (0.0, CANISTER_SIZE_RANGE[1]),
    "info_size": INFO_SIZE_RANGE, "info_opacity": (0.0, 1.0), "info_x": (0.0, 1.0), "info_y": (0.0, 1.0),
}
_PLACE_FIELDS = ("text_position", "logo_position", "info_position")
_COLOR_FIELDS = ("text_color", "info_color", "logo_color")


@dataclass(frozen=True)
class TextSpec:
    """Everything that decides how a block of text looks (hashable, so a drawn block can be cached)."""

    text: str
    height_px: int
    font: str = ""
    bold: bool = False
    italic: bool = False
    color: str = "white"
    opacity: float = 1.0
    shadow: bool = True
    align: str = "left"
    line_spacing: float = 0.25
    letter_spacing: float = 0.0
    rotation: float = 0.0
    outline: float = 0.0
    credit: str = ""


def _line_width(probe, text: str, font, spacing_px: float) -> float:
    if not spacing_px:
        return probe.textlength(text, font=font)
    return sum(probe.textlength(ch, font=font) for ch in text) + spacing_px * max(0, len(text) - 1)


def _draw_line(draw, x: float, y: float, text: str, font, spacing_px: float, fill, stroke: int, stroke_fill) -> None:
    if not spacing_px:
        draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
        return
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
        x += draw.textlength(ch, font=font) + spacing_px


def _rotate(rgb: np.ndarray, alpha: np.ndarray, degrees: float) -> tuple[np.ndarray, np.ndarray]:
    """Turn a premultiplied sprite clockwise by `degrees`, on a canvas big enough to hold it."""
    import cv2

    h, w = alpha.shape
    rad = math.radians(degrees)
    c, s = abs(math.cos(rad)), abs(math.sin(rad))
    nw, nh = int(math.ceil(w * c + h * s)), int(math.ceil(w * s + h * c))
    m = cv2.getRotationMatrix2D((w / 2, h / 2), -degrees, 1.0)
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    stacked = np.dstack([rgb, alpha[:, :, None] * 255.0]).astype(np.float32)
    turned = cv2.warpAffine(stacked, m, (nw, nh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return np.ascontiguousarray(turned[:, :, :3]), np.ascontiguousarray(turned[:, :, 3] / 255.0)


@lru_cache(maxsize=24)
def text_sprite(spec: TextSpec) -> tuple[np.ndarray, np.ndarray]:
    """The text as a (premultiplied RGB float32 0-255, alpha float32 0-1) sprite."""
    from PIL import Image, ImageDraw

    path, fake_bold, fake_italic = fonts.resolve(spec.font, spec.bold, spec.italic)
    size = max(6, spec.height_px)
    font = fonts.load(path, size)
    rows = [(t, font) for t in spec.text.split("\n")]
    if spec.credit:
        rows.append((spec.credit, fonts.load(path, max(6, round(size * 0.55)))))
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    spacing_px = spec.letter_spacing * size
    widths = [_line_width(probe, t, f, spacing_px if f is font else 0.0) for t, f in rows]
    tops = [f.getbbox("Hgy")[1] for _t, f in rows]
    heights = [max(1, f.getbbox("Hgy")[3] - top) for (_t, f), top in zip(rows, tops)]
    gap = max(0, round(size * spec.line_spacing))
    bold_px = max(1, round(size / 28)) if fake_bold else 0
    outline_px = round(spec.outline * _OUTLINE_SHARE * size)
    off = max(1, round(size / 14)) if spec.shadow else 0
    pad = outline_px + bold_px + 2
    inner_w = int(math.ceil(max(widths)))
    w = inner_w + 2 * pad + off
    h = sum(heights) + gap * (len(rows) - 1) + 2 * pad + off
    ink = color_rgb(spec.color)
    contrast = (0, 0, 0) if (0.299 * ink[0] + 0.587 * ink[1] + 0.114 * ink[2]) > 140 else (255, 255, 255)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d, ds = ImageDraw.Draw(layer), ImageDraw.Draw(shade)
    y = pad
    for (t, f), tw, top, th in zip(rows, widths, tops, heights):
        free = inner_w - tw
        align = spec.align
        x = pad + (0 if align == "left" else free if align == "right" else free / 2)
        sp = spacing_px if f is font else 0.0
        if spec.shadow:
            _draw_line(ds, x + off, y - top + off, t, f, sp, contrast + (140,), outline_px + bold_px, contrast + (140,))
        if outline_px:
            _draw_line(d, x, y - top, t, f, sp, contrast + (255,), outline_px + bold_px, contrast + (255,))
        _draw_line(d, x, y - top, t, f, sp, ink + (255,), bold_px, ink + (255,))
        y += th + gap
    shade.alpha_composite(layer)
    if fake_italic:
        k = 0.2
        extra = int(math.ceil(k * h))
        shade = shade.transform((w + extra, h), Image.Transform.AFFINE, (1, k, -k * h, 0, 1, 0), resample=Image.Resampling.BICUBIC)
    f32 = np.asarray(shade, dtype=np.float32).copy()
    f32[:, :, 3] *= float(spec.opacity)
    f32[:, :, :3] *= f32[:, :, 3:4] / 255.0
    rgb, alpha = np.ascontiguousarray(f32[:, :, :3]), np.ascontiguousarray(f32[:, :, 3] / 255.0)
    if spec.rotation:
        rgb, alpha = _rotate(rgb, alpha, spec.rotation)
    return rgb, alpha


def _place(position: str, iw: int, ih: int, sw: int, sh: int, margin: int) -> tuple[int, int]:
    vert, horiz = position.split("_") if position != "center" else ("middle", "center")
    x = margin if horiz == "left" else iw - sw - margin if horiz == "right" else (iw - sw) // 2
    y = margin if vert == "top" else ih - sh - margin if vert == "bottom" else (ih - sh) // 2
    return x, y


def _where(position: str, cx: float, cy: float, iw: int, ih: int, sw: int, sh: int, margin: int) -> tuple[int, int]:
    """Top-left corner of a sprite: from the menu's position, or centred on a dragged-to spot (fractions of the picture)."""
    if position == CUSTOM:
        return round(cx * iw - sw / 2), round(cy * ih - sh / 2)
    return _place(position, iw, ih, sw, sh, margin)


def _auto_align(position: str) -> str:
    horiz = position.split("_")[-1] if position not in ("center", CUSTOM) else "center"
    return {"left": "left", "right": "right"}.get(horiz, "center")


def marker_variables(marks: Marks, variables: Mapping[str, str] | None = None) -> dict[str, str]:
    """What an SVG marker is drawn with: the photo's variables, and the marker's own text, colour and font as darktable's $(WATERMARK_...) variables. The text may hold variables of its
    own ("(c) $(EXIF.YEAR) $(CAMERA)"); they are filled in here, once, so what an SVG gets is plain text."""
    base = dict(variables or {})
    r, g, b = color_rgb(marks.logo_color)
    base.update({
        "WATERMARK_TEXT": wmvars.expand(marks.logo_text, base),
        "WATERMARK_COLOR": f"#{r:02x}{g:02x}{b:02x}",
        "WATERMARK_FONT_FAMILY": logoimage.svg_font_family(marks.logo_font),
        "WATERMARK_FONT_STYLE": "italic" if marks.logo_italic else "normal",
        "WATERMARK_FONT_WEIGHT": "700" if marks.logo_bold else "400",
    })
    return base


def _logo_request(marks: Marks, iw: int, ih: int) -> tuple[str, int]:
    """(how the size is read, the pixels) for the marker - see logoimage.SCALE_ON."""
    if marks.logo_scale_on == "long":
        return "long", max(4, round(max(iw, ih) * marks.logo_size))
    if marks.logo_scale_on == "width":
        return "width", max(4, round(iw * marks.logo_size))
    if marks.logo_scale_on == "height":
        return "height", max(4, round(ih * marks.logo_size))
    return "long", max(4, round(min(iw, ih) * marks.logo_size))


def mark_parts(shape, marks: Marks, info: bool = False, camera: str = "", lens: str = "", canister_on: bool = False, variables: Mapping[str, str] | None = None) -> list[Part]:
    """The logo ("logo"), the text ("text") and the camera/lens text on its own ("info"), laid out on a picture of this shape. `variables` are the photo's $(NAME) values (wmvars.build)."""
    ih, iw = shape[:2]
    short = min(ih, iw)
    margin = round(short * MARGIN)
    parts: list[Part] = []
    marker = library.resolve(marks.logo)
    if marker is not None:
        try:
            mode, px = _logo_request(marks, iw, ih)
            rgb, alpha = logoimage.marker_sprite(marker, mode, px, marks.logo_opacity, marker_variables(marks, variables))
            if marks.logo_rotation:
                rgb, alpha = _rotate(rgb, alpha, marks.logo_rotation)
        except Exception:
            rgb = alpha = None
        if alpha is not None:
            x, y = _where(marks.logo_position, marks.logo_x, marks.logo_y, iw, ih, alpha.shape[1], alpha.shape[0], margin)
            parts.append(Part("logo", rgb, alpha, x, y))
    text = wmvars.expand(marks.text, variables or {}) if marks.has_text() else ""
    if text.strip():
        align = _auto_align(marks.text_position) if marks.text_align == "auto" else marks.text_align
        rgb, alpha = text_sprite(TextSpec(
            text.strip(), max(6, round(short * marks.text_size)), marks.text_font, marks.text_bold, marks.text_italic, marks.text_color,
            marks.text_opacity, marks.text_shadow, align, marks.text_line_spacing, marks.text_letter_spacing, marks.text_rotation, marks.text_outline,
        ))
        x, y = _where(marks.text_position, marks.text_x, marks.text_y, iw, ih, alpha.shape[1], alpha.shape[0], margin)
        parts.append(Part("text", rgb, alpha, x, y))
    if marks.info_alone(info, camera, lens, canister_on):
        lines = "\n".join(t.strip() for t in (camera, lens) if t.strip())
        rgb, alpha = text_sprite(TextSpec(
            lines, max(6, round(short * marks.info_size)), marks.info_font, marks.info_bold, False, marks.info_color, marks.info_opacity,
            marks.info_shadow, _auto_align(marks.info_position), 0.3, 0.0, 0.0, 0.0, CREDIT if marks.info_credit else "",
        ))
        x, y = _where(marks.info_position, marks.info_x, marks.info_y, iw, ih, alpha.shape[1], alpha.shape[0], margin)
        parts.append(Part("info", rgb, alpha, x, y))
    return parts


def apply_marks(image: np.ndarray, marks: Marks, info: bool = False, camera: str = "", lens: str = "", canister_on: bool = False, variables: Mapping[str, str] | None = None) -> np.ndarray:
    """uint8 RGB in, uint8 RGB out (the input is never modified): the logo, then the text, then the camera/lens text."""
    parts = mark_parts(image.shape, marks, info, camera, lens, canister_on, variables)
    if not parts:
        return image
    out = image.copy()
    for part in parts:
        _blend(out, part.rgb, part.alpha, part.x, part.y)
    return out
