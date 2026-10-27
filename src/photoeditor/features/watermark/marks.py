"""The watermarks that are not the canister, laid over the finished picture: the marker (an SVG or a picture - the Watermark module, darktable's: dtmark.py), and EFAS's own
text, camera/lens text and dragged-canister place (the Canister Watermark module).

`Marks` holds both, because both are kept, copied and drawn together. Each module owns some of its fields (`MARKER_FIELDS` for the Watermark module, the rest for Canister Watermark): a
module's preset, reset and on/off light touch only its own (`part`, `with_part`, `cleared`)."""

import dataclasses
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping

import numpy as np

from . import dtmark, fonts, library, logoimage
from . import variables as wmvars
from .logic import CREDIT, MARGIN, POSITIONS, Part, _blend

CUSTOM = "custom"
PLACES = {**POSITIONS, CUSTOM: "Custom"}
DEFAULT_TEXT_POSITION = "bottom_right"
DEFAULT_INFO_POSITION = "bottom_left"
TEXT_SIZE_RANGE = (0.01, 0.15)
INFO_SIZE_RANGE = (0.01, 0.10)
CANISTER_SIZE_RANGE = (0.05, 0.95)
LINE_SPACING_RANGE = (0.0, 1.0)
LETTER_SPACING_RANGE = (-0.1, 0.6)
ROTATION_RANGE = dtmark.ROTATE_RANGE
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
    # the marker (SVG or picture), with darktable's settings (dtmark.py)
    logo: str = ""
    logo_opacity: float = 1.0                  # 0-1 (darktable: 0-100%)
    logo_scale: float = 100.0                  # percent, 1-500
    logo_base: str = dtmark.DEFAULT_BASE       # Scale on (dtmark.BASES)
    logo_img: str = dtmark.DEFAULT_IMAGE_SIDE      # with Scale on "advanced": the picture's dimension (dtmark.IMAGE_SIDES) ...
    logo_svg: str = dtmark.DEFAULT_MARKER_SIDE     # ... and the marker's (dtmark.MARKER_SIDES)
    logo_align: int = dtmark.DEFAULT_ALIGNMENT     # 0-8, row by row from the top left
    logo_xoff: float = 0.0                     # -1 to 1: a share of the base width
    logo_yoff: float = 0.0                     # ... and of the base height
    logo_rotation: float = 0.0                 # degrees, clockwise
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

    def part(self, module: str) -> dict[str, Any]:
        """What one module owns of this, as a dict of what differs from the defaults (the Watermark module: the marker; Canister Watermark: the rest)."""
        keep = _owned(module)
        return {k: v for k, v in self.to_dict().items() if k in keep}

    def with_part(self, module: str, other: "Marks | dict | None") -> "Marks":
        """This, with the fields one module owns taken from `other` (whose other fields are ignored)."""
        other = Marks.from_dict(other)
        keep = _owned(module)
        return dataclasses.replace(self, **{f.name: getattr(other, f.name) for f in dataclasses.fields(self) if f.name in keep})

    def cleared(self, module: str) -> "Marks":
        """This, with the fields one module owns put back to the defaults."""
        return self.with_part(module, Marks())

    def info_alone(self, info: bool, camera: str, lens: str, canister_on: bool) -> bool:
        """Is the camera/lens text drawn by itself (not beside the canister)?"""
        return bool(info and (camera.strip() or lens.strip()) and (not canister_on or not self.info_beside))

    def active(self) -> bool:
        return self.has_text() or self.has_logo()

    def wanted(self, info: bool = False, camera: str = "", lens: str = "", canister_on: bool = False) -> bool:
        """Does anything here need drawing?"""
        return self.active() or self.info_alone(info, camera, lens, canister_on)

    def to_dict(self) -> dict[str, Any]:
        """Only what differs from the defaults, so a photo without marks stores {}. A marker also stores the version of its settings (`v`), which tells a marker set up by the Watermark
        module of this version (darktable's settings) from one an earlier version made (a share of the picture, a position and a margin): see _upgrade."""
        base = Marks()
        out = {f.name: getattr(self, f.name) for f in dataclasses.fields(self) if getattr(self, f.name) != getattr(base, f.name)}
        if self.logo:
            out["v"] = MARKER_VERSION
        return out

    @classmethod
    def from_dict(cls, data: Any) -> "Marks":
        """Always valid: unknown keys are ignored, bad values fall back to the default, numbers are pulled into range."""
        if isinstance(data, Marks):
            return data
        if not isinstance(data, dict):
            return cls()
        d = cls()
        data = _upgrade(data)
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
            elif name == "logo_base":
                kw[name] = _choice(raw, dtmark.BASES, default)
            elif name == "logo_img":
                kw[name] = _choice(raw, dtmark.IMAGE_SIDES, default)
            elif name == "logo_svg":
                kw[name] = _choice(raw, dtmark.MARKER_SIDES, default)
            elif name == "logo_align":
                kw[name] = int(_num(raw, 0, 8, default))
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
    "logo_opacity": (0.0, 1.0), "logo_scale": dtmark.SCALE_RANGE, "logo_xoff": dtmark.OFFSET_RANGE, "logo_yoff": dtmark.OFFSET_RANGE, "logo_rotation": ROTATION_RANGE,
    "canister_x": (-1.0, 1.0), "canister_y": (-1.0, 1.0), "canister_size": (0.0, CANISTER_SIZE_RANGE[1]),
    "info_size": INFO_SIZE_RANGE, "info_opacity": (0.0, 1.0), "info_x": (0.0, 1.0), "info_y": (0.0, 1.0),
}
_PLACE_FIELDS = ("text_position", "info_position")
_COLOR_FIELDS = ("text_color", "info_color", "logo_color")

MARKER_VERSION = 2   # 1: an earlier version's marker (size as a share, a position, a margin); 2: darktable's settings
WATERMARK, CANISTER = "watermark", "canisterwm"     # the two modules: darktable's Watermark (the marker) and EFAS's Canister Watermark (the rest)
MARKS_MODULES = (WATERMARK, CANISTER)
MARKER_FIELDS = frozenset({
    "logo", "logo_opacity", "logo_scale", "logo_base", "logo_img", "logo_svg", "logo_align", "logo_xoff", "logo_yoff", "logo_rotation",
    "logo_text", "logo_color", "logo_font", "logo_bold", "logo_italic",
})


def _owned(module: str) -> frozenset[str]:
    names = {f.name for f in dataclasses.fields(Marks)}
    if module == WATERMARK:
        return MARKER_FIELDS | {"v"}
    if module == CANISTER:
        return frozenset(names - MARKER_FIELDS)
    return frozenset()


_LEGACY_MARKER_KEYS = ("logo_size", "logo_position", "logo_x", "logo_y", "logo_dx", "logo_dy", "logo_scale_on")
_LEGACY_ALIGN = {"top_left": 0, "top_center": 1, "top_right": 2, "middle_left": 3, "center": 4, "middle_right": 5, "bottom_left": 6, "bottom_center": 7, "bottom_right": 8}


def place_as_darktable(position: str, cx: float, cy: float, dx: float, dy: float, base: str) -> tuple[int, float, float]:
    """(alignment, X offset, Y offset) for a place an earlier version described as a menu position (kept off the edge by a margin of 3% of the shorter side), or a centre (cx, cy) as
    shares of the picture, and a move (dx, dy) as shares of its width and height. Offsets are shares of the base width and height, which depend on the picture's shape: a 3:2 frame is
    assumed, so a place comes out right for the usual picture and close for any other."""
    wide = 1.5                                  # width over height of the picture assumed
    wb, hb = {"larger": (wide, wide), "smaller": (1.0, 1.0)}.get(base, (wide, 1.0))   # the base width and height, with the picture's height 1
    margin = 0.03                               # of the shorter side (the height)
    if position == "custom":
        align, x, y = 4, (cx - 0.5) * wide / wb, (cy - 0.5) / hb
    else:
        align = _LEGACY_ALIGN.get(position, 6)
        col, row = align % 3, align // 3
        x = (margin / wb if col == 0 else -margin / wb if col == 2 else 0.0)
        y = (margin / hb if row == 0 else -margin / hb if row == 2 else 0.0)
    x += dx * wide / wb
    y += dy / hb
    return align, round(max(-1.0, min(1.0, x)), 4), round(max(-1.0, min(1.0, y)), 4)


def _upgrade(data: dict) -> dict:
    """A marker an earlier version set up (no `v`, with a size as a share of the picture, a position, a margin) as the same marker with darktable's settings. The size's meaning carries
    over exactly: its shorter side is Smaller border, its longer side Larger border, fit the picture is Image, and width and height are Advanced with that dimension of the picture and the
    marker; the position and the move become an alignment and offsets (place_as_darktable)."""
    if not data.get("logo") or data.get("v") == MARKER_VERSION:
        return {k: v for k, v in data.items() if k not in _LEGACY_MARKER_KEYS}
    num = lambda key, default: _num(data.get(key), -1e9, 1e9, default)   # noqa: E731
    size = num("logo_size", 0.18)
    mode = data.get("logo_scale_on") if data.get("logo_scale_on") in ("fit", "short", "long", "width", "height") else "short"
    base, img, svg = {"fit": ("image", "larger", "width"), "short": ("smaller", "larger", "width"), "long": ("larger", "larger", "width"),
                      "width": ("advanced", "width", "width"), "height": ("advanced", "height", "height")}[mode]
    position = data.get("logo_position") if data.get("logo_position") in (*_LEGACY_ALIGN, "custom") else "bottom_left"
    align, x, y = place_as_darktable(position, num("logo_x", 0.15), num("logo_y", 0.9), num("logo_dx", 0.0), num("logo_dy", 0.0), base)
    out = {k: v for k, v in data.items() if k not in _LEGACY_MARKER_KEYS}
    out.update({"logo_scale": size * 100.0, "logo_base": base, "logo_img": img, "logo_svg": svg, "logo_align": align, "logo_xoff": x, "logo_yoff": y,
                "logo_opacity": num("logo_opacity", 0.9), "v": MARKER_VERSION})
    return out


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
    if sw >= iw - 2 * margin:   # as wide as the picture: there is no room for a margin, so it is centred (a strip that fits the width sits square to the edges)
        x = (iw - sw) // 2
    if sh >= ih - 2 * margin:
        y = (ih - sh) // 2
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


TEXT_MARKER = "simple-text.svg"   # the sample marker that writes a line of text


def text_as_marker(marks: Marks) -> Marks:
    """The old Text mark rewritten as the simple-text marker (an approximation: one line, its letters about as tall, the same colour, font, place and turn), so the text can be kept and edited
    in the Watermark module; the text mark itself is cleared."""
    size = max(dtmark.SCALE_RANGE[0], min(dtmark.SCALE_RANGE[1], marks.text_size * 13.2 * 100.0))   # that marker's letters are 76 of its 1000 units; its size is a share of the shorter side
    align, x, y = place_as_darktable(marks.text_position, marks.text_x, marks.text_y, 0.0, 0.0, "smaller")
    return dataclasses.replace(
        marks, text="", logo=TEXT_MARKER, logo_text=" ".join(marks.text.split())[:MARKER_TEXT_MAX], logo_color=marks.text_color, logo_font=marks.text_font, logo_bold=marks.text_bold,
        logo_italic=marks.text_italic, logo_scale=size, logo_base="smaller", logo_opacity=marks.text_opacity, logo_align=align, logo_xoff=x, logo_yoff=y, logo_rotation=marks.text_rotation,
    )


def _logo_part(marker: str, marks: Marks, iw: int, ih: int, svg_vars: Mapping[str, str]) -> Part:
    """The marker as a part of the watermark, laid out and drawn the way darktable's Watermark module does (dtmark.py)."""
    return dtmark.marker_part(
        marker, svg_vars, iw, ih, base=marks.logo_base, image_side=marks.logo_img, marker_side=marks.logo_svg, scale_percent=marks.logo_scale, alignment=marks.logo_align,
        xoffset=marks.logo_xoff, yoffset=marks.logo_yoff, rotate=marks.logo_rotation, opacity=marks.logo_opacity,
    )


def mark_parts(shape, marks: Marks, info: bool = False, camera: str = "", lens: str = "", canister_on: bool = False, variables: Mapping[str, str] | None = None) -> list[Part]:
    """The logo ("logo"), the text ("text") and the camera/lens text on its own ("info"), laid out on a picture of this shape. `variables` are the photo's $(NAME) values (wmvars.build)."""
    ih, iw = shape[:2]
    short = min(ih, iw)
    margin = round(short * MARGIN)
    parts: list[Part] = []
    marker = library.resolve(marks.logo)
    if marker is not None:
        try:
            parts.append(_logo_part(marker, marks, iw, ih, marker_variables(marks, variables)))
        except Exception:
            pass
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
