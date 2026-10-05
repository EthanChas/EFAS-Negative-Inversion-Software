"""Canister watermark - numpy + OpenCV, no Qt/UI imports.

Composites a pre-rendered 3D film canister (assets/canisters/<film>__<texture>.png,
RGBA, transparent background, rendered from Blender with soft matte shading and
no cast shadows or specular highlights) over the finished picture. Film picks the
label, Texture the canister's body material, Size how big it is relative to the
picture, Position which corner/edge it sits in. Optionally the camera and lens are
written beside it in white, with a tiny credit line underneath. OpenCV and PIL are
imported lazily."""

from functools import lru_cache
from pathlib import Path

import numpy as np

WATERMARK_OFF = "off"
ASSET_DIR = Path(__file__).resolve().parents[2] / "assets" / "canisters"

FILMS = {"fomapan_200": "Fomapan 200", "kodak_gold_200": "Kodak Gold 200", "ilford_delta_400": "Ilford Delta 400"}
TEXTURES = {"plastic": "Plastic", "aluminium": "Aluminium", "scuffed": "Scuffed plastic"}
# The canister's longer side as a fraction of the picture's shorter side.
SIZES = {"small": ("Small", 0.16), "medium": ("Medium", 0.26), "large": ("Large", 0.38), "huge": ("Extra large", 0.55)}
POSITIONS = {
    "top_left": "Top left", "top_center": "Top center", "top_right": "Top right",
    "middle_left": "Middle left", "center": "Center", "middle_right": "Middle right",
    "bottom_left": "Bottom left", "bottom_center": "Bottom center", "bottom_right": "Bottom right",
}
DEFAULT_TEXTURE = "plastic"
DEFAULT_SIZE = "medium"
DEFAULT_POSITION = "bottom_right"
MARGIN = 0.03  # gap to the picture's edge, as a fraction of its shorter side
CREDIT = "Edited with Ethans Negative Inversion App"
_FONT_FILES = ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf")


def asset_path(film: str, texture: str) -> Path:
    return ASSET_DIR / f"{film}__{texture}.png"


def is_active(film: str) -> bool:
    return film != WATERMARK_OFF and film in FILMS


@lru_cache(maxsize=4)
def _load(film: str, texture: str) -> np.ndarray:
    from PIL import Image

    with Image.open(asset_path(film, texture)) as im:
        return np.asarray(im.convert("RGBA"), dtype=np.uint8)


@lru_cache(maxsize=8)
def _sprite(film: str, texture: str, long_side: int) -> tuple[np.ndarray, np.ndarray]:
    """-> (premultiplied RGB float32 0..255, alpha float32 0..1), long side = long_side px."""
    import cv2

    rgba = _load(film, texture)
    h, w = rgba.shape[:2]
    k = long_side / max(h, w)
    size = (max(1, round(w * k)), max(1, round(h * k)))
    f = rgba.astype(np.float32)
    f[:, :, :3] *= f[:, :, 3:4] / 255.0  # premultiply first, so edges don't pick up the transparent pixels' color
    f = cv2.resize(f, size, interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_LINEAR)
    return np.ascontiguousarray(f[:, :, :3]), np.ascontiguousarray(f[:, :, 3] / 255.0)


def _font(size: int):
    from PIL import ImageFont

    for name in _FONT_FILES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


@lru_cache(maxsize=16)
def _text_block(camera: str, lens: str, sprite_h: int, max_w: int, align_right: bool) -> tuple[np.ndarray, np.ndarray]:
    """White camera/lens lines with the tiny credit underneath, as (premultiplied RGB, alpha) like _sprite.
    Sized from the canister's height; shrunk if the widest line would not fit in max_w."""
    from PIL import Image, ImageDraw

    lines = [t.strip() for t in (camera, lens) if t.strip()]
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    scale = 1.0
    for _ in range(3):  # shrink until the widest line fits (font sizes are integers, so it may take a pass or two)
        big, small = max(8, round(sprite_h * 0.075 * scale)), max(6, round(sprite_h * 0.040 * scale))
        rows = [(t, _font(big)) for t in lines] + [(CREDIT, _font(small))]
        widths = [probe.textlength(t, font=f) for t, f in rows]
        if max(widths) <= max_w or big <= 8:
            break
        scale *= max_w / max(widths) * 0.98
    gap = max(2, round(big * 0.35))
    heights = [f.getbbox("Hgy")[3] - f.getbbox("Hgy")[1] for _t, f in rows]
    shadow = max(1, big // 12)
    w = int(max(widths)) + shadow + 2
    h = sum(heights) + gap * (len(rows) - 1) + shadow + 2
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d, ds = ImageDraw.Draw(layer), ImageDraw.Draw(shade)
    y = 0
    for (t, f), tw, th in zip(rows, widths, heights):
        x = (w - shadow - 2 - tw) if align_right else 0
        top = y - f.getbbox("Hgy")[1]
        ds.text((x + shadow, top + shadow), t, font=f, fill=(0, 0, 0, 120))   # faint drop shadow, for legibility on bright pictures
        d.text((x, top), t, font=f, fill=(255, 255, 255, 255))
        y += th + gap
    shade.alpha_composite(layer)
    f32 = np.asarray(shade, dtype=np.float32).copy()
    f32[:, :, :3] *= f32[:, :, 3:4] / 255.0
    return np.ascontiguousarray(f32[:, :, :3]), np.ascontiguousarray(f32[:, :, 3] / 255.0)


def _blend(out: np.ndarray, rgb: np.ndarray, alpha: np.ndarray, x: int, y: int) -> None:
    """Composite a premultiplied sprite onto out in place, clipped to the picture."""
    ih, iw = out.shape[:2]
    sh, sw = alpha.shape
    x0, y0, x1, y1 = max(0, x), max(0, y), min(iw, x + sw), min(ih, y + sh)
    if x1 <= x0 or y1 <= y0:
        return
    sub = (slice(y0 - y, y1 - y), slice(x0 - x, x1 - x))
    a = alpha[sub][:, :, None]
    region = rgb[sub] + out[y0:y1, x0:x1].astype(np.float32) * (1.0 - a)
    out[y0:y1, x0:x1] = np.clip(region + 0.5, 0, 255).astype(np.uint8)


def apply_watermark(
    image: np.ndarray, film: str, texture: str, size: str, position: str,
    info: bool = False, camera: str = "", lens: str = "",
) -> np.ndarray:
    """uint8 RGB in, uint8 RGB out; the input is never modified. Unknown or 'off'
    settings return it untouched. With info on, the camera/lens text and the credit
    sit beside the canister: left of it when it is on the right, otherwise to its right."""
    if not is_active(film) or texture not in TEXTURES or size not in SIZES or position not in POSITIONS:
        return image
    if not asset_path(film, texture).exists():
        return image
    ih, iw = image.shape[:2]
    short = min(ih, iw)
    long_side = max(8, round(short * SIZES[size][1]))
    rgb, alpha = _sprite(film, texture, long_side)
    sh, sw = alpha.shape
    margin = round(short * MARGIN)
    vert, horiz = position.split("_") if position != "center" else ("middle", "center")

    text = None
    gap = 0
    if info:
        gap = round(sh * 0.05)
        text = _text_block(camera, lens, sh, max(40, iw - 2 * margin - sw - gap), horiz == "right")
    tw = text[1].shape[1] if text else 0
    group_w = sw + (gap + tw if text else 0)
    gx = margin if horiz == "left" else iw - group_w - margin if horiz == "right" else (iw - group_w) // 2
    y = margin if vert == "top" else ih - sh - margin if vert == "bottom" else (ih - sh) // 2
    if text and horiz == "right":                       # text on the canister's left
        text_x, x = gx, gx + tw + gap
    else:
        x, text_x = gx, gx + sw + gap
    out = image.copy()
    _blend(out, rgb, alpha, x, y)
    if text:
        _blend(out, text[0], text[1], text_x, y + (sh - text[1].shape[0]) // 2)
    return out
