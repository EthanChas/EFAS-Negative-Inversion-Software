"""Simple watermarks - a line of text and/or a logo image laid over the finished picture. numpy + PIL, no Qt imports.

Alongside the canister watermark (logic.py), these are the plain kind: type a copyright line and pick where it goes, how big it is, how
see-through, white or black with a faint shadow for legibility; and/or put a logo (a PNG with a transparent background works best) in a
corner. Sizes are fractions of the picture's shorter side, so a mark looks the same on a small export and a full-size one."""

import dataclasses
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np

from .logic import MARGIN, POSITIONS, _FONT_FILES, _blend

DEFAULT_TEXT_POSITION = "bottom_right"
DEFAULT_LOGO_POSITION = "bottom_left"
TEXT_SIZE_RANGE = (0.01, 0.15)   # font height / the picture's shorter side
LOGO_SIZE_RANGE = (0.03, 0.80)   # the logo's longer side / the picture's shorter side
COLORS = {"white": "White", "black": "Black"}


def _num(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return default if number != number else max(low, min(high, number))


def _choice(value: Any, allowed, default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


@dataclass(frozen=True)
class Marks:
    text: str = ""
    text_size: float = 0.04
    text_opacity: float = 0.85
    text_color: str = "white"
    text_position: str = DEFAULT_TEXT_POSITION
    text_shadow: bool = True
    logo: str = ""                    # path of an image file; "" for none
    logo_size: float = 0.18
    logo_opacity: float = 0.9
    logo_position: str = DEFAULT_LOGO_POSITION

    def has_text(self) -> bool:
        return bool(self.text.strip())

    def has_logo(self) -> bool:
        return bool(self.logo) and os.path.isfile(self.logo)

    def active(self) -> bool:
        return self.has_text() or self.has_logo()

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
        return cls(
            text=str(data.get("text", ""))[:200] if isinstance(data.get("text", ""), str) else "",
            text_size=_num(data.get("text_size"), *TEXT_SIZE_RANGE, d.text_size),
            text_opacity=_num(data.get("text_opacity"), 0.0, 1.0, d.text_opacity),
            text_color=_choice(data.get("text_color"), COLORS, d.text_color),
            text_position=_choice(data.get("text_position"), POSITIONS, d.text_position),
            text_shadow=bool(data.get("text_shadow", d.text_shadow)),
            logo=data.get("logo") if isinstance(data.get("logo"), str) else "",
            logo_size=_num(data.get("logo_size"), *LOGO_SIZE_RANGE, d.logo_size),
            logo_opacity=_num(data.get("logo_opacity"), 0.0, 1.0, d.logo_opacity),
            logo_position=_choice(data.get("logo_position"), POSITIONS, d.logo_position),
        )


def _font(size: int):
    from PIL import ImageFont

    for name in _FONT_FILES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


@lru_cache(maxsize=16)
def _text_sprite(text: str, height_px: int, color: str, opacity: float, shadow: bool, align: str) -> tuple[np.ndarray, np.ndarray]:
    """The text as a (premultiplied RGB float32 0-255, alpha float32 0-1) sprite. Several lines are kept as typed, aligned left, centre or
    right to match the side of the picture they sit on."""
    from PIL import Image, ImageDraw

    lines = text.split("\n")
    font = _font(max(6, height_px))
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    widths = [probe.textlength(t, font=font) for t in lines]
    line_h = max(1, font.getbbox("Hgy")[3] - font.getbbox("Hgy")[1])
    gap = max(2, round(height_px * 0.25))
    off = max(1, round(height_px / 14)) if shadow else 0
    w = int(max(widths)) + off + 2
    h = line_h * len(lines) + gap * (len(lines) - 1) + off + 2
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d, ds = ImageDraw.Draw(layer), ImageDraw.Draw(shade)
    ink = (255, 255, 255, 255) if color == "white" else (0, 0, 0, 255)
    halo = (0, 0, 0, 130) if color == "white" else (255, 255, 255, 130)
    y = 0
    for t, tw in zip(lines, widths):
        x = 0 if align == "left" else (w - off - 2 - tw) if align == "right" else (w - off - 2 - tw) / 2
        top = y - font.getbbox("Hgy")[1]
        if shadow:
            ds.text((x + off, top + off), t, font=font, fill=halo)
        d.text((x, top), t, font=font, fill=ink)
        y += line_h + gap
    shade.alpha_composite(layer)
    f32 = np.asarray(shade, dtype=np.float32).copy()
    f32[:, :, 3] *= float(opacity)
    f32[:, :, :3] *= f32[:, :, 3:4] / 255.0
    return np.ascontiguousarray(f32[:, :, :3]), np.ascontiguousarray(f32[:, :, 3] / 255.0)


@lru_cache(maxsize=8)
def _logo_sprite(path: str, mtime: float, long_side: int, opacity: float) -> tuple[np.ndarray, np.ndarray]:
    import cv2
    from PIL import Image

    with Image.open(path) as im:
        rgba = np.asarray(im.convert("RGBA"), dtype=np.float32)
    h, w = rgba.shape[:2]
    k = long_side / max(h, w)
    rgba[:, :, :3] *= rgba[:, :, 3:4] / 255.0  # premultiply before resizing, so the edges do not pick up the transparent pixels' color
    size = (max(1, round(w * k)), max(1, round(h * k)))
    rgba = cv2.resize(rgba, size, interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_LINEAR)
    alpha = rgba[:, :, 3] / 255.0 * float(opacity)
    rgb = rgba[:, :, :3] * float(opacity)
    return np.ascontiguousarray(rgb), np.ascontiguousarray(alpha)


def _place(position: str, iw: int, ih: int, sw: int, sh: int, margin: int) -> tuple[int, int]:
    vert, horiz = position.split("_") if position != "center" else ("middle", "center")
    x = margin if horiz == "left" else iw - sw - margin if horiz == "right" else (iw - sw) // 2
    y = margin if vert == "top" else ih - sh - margin if vert == "bottom" else (ih - sh) // 2
    return x, y


def apply_marks(image: np.ndarray, marks: Marks) -> np.ndarray:
    """uint8 RGB in, uint8 RGB out (the input is never modified): the logo, then the text over it. Nothing to draw returns the input."""
    if not marks.active():
        return image
    ih, iw = image.shape[:2]
    short = min(ih, iw)
    margin = round(short * MARGIN)
    out = image.copy()
    if marks.has_logo():
        try:
            rgb, alpha = _logo_sprite(marks.logo, os.path.getmtime(marks.logo), max(4, round(short * marks.logo_size)), marks.logo_opacity)
        except Exception:  # an unreadable file is skipped; it must not stop the export
            rgb = alpha = None
        if alpha is not None:
            x, y = _place(marks.logo_position, iw, ih, alpha.shape[1], alpha.shape[0], margin)
            _blend(out, rgb, alpha, x, y)
    if marks.has_text():
        horiz = marks.text_position.split("_")[-1] if marks.text_position != "center" else "center"
        rgb, alpha = _text_sprite(marks.text.strip(), max(6, round(short * marks.text_size)), marks.text_color, marks.text_opacity,
                                  marks.text_shadow, {"left": "left", "right": "right"}.get(horiz, "center"))
        x, y = _place(marks.text_position, iw, ih, alpha.shape[1], alpha.shape[0], margin)
        _blend(out, rgb, alpha, x, y)
    return out
