"""Where each watermark sits on the picture (for dragging and resizing them with the mouse), and what a drag changes. No Qt."""

import dataclasses

from .logic import SIZES, canister_parts, long_side_fraction
from .marks import CANISTER_SIZE_RANGE, CUSTOM, INFO_SIZE_RANGE, LOGO_SIZE_RANGE, TEXT_SIZE_RANGE, Marks, mark_parts

EDITABLE = ("canister", "logo", "text", "info")
LABELS = {"canister": "Canister", "logo": "Logo", "text": "Text", "info": "Camera and lens"}


def boxes(shape, canister: dict | None, marks: Marks, info: bool = False, camera: str = "", lens: str = "") -> dict[str, tuple[int, int, int, int]]:
    """(x, y, width, height) of every watermark that is showing, on a picture of this (cropped, before any border) shape.

    `canister` is {"film", "texture", "size", "position"} or None when the canister is off. The camera/lens text beside a canister moves with it
    and has no box of its own."""
    out: dict[str, tuple[int, int, int, int]] = {}
    on = canister is not None
    if on:
        custom = (marks.canister_x, marks.canister_y) if marks.has_custom_canister() else None
        for part in canister_parts(shape, canister["film"], canister["texture"], canister["size"], canister["position"], info, camera, lens, custom, marks.canister_size):
            if part.name == "canister":
                out["canister"] = part.box
    for part in mark_parts(shape, marks, info, camera, lens, on):
        out[part.name] = part.box
    return out


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def edit(marks: Marks, name: str, cx: float, cy: float, ratio: float = 1.0, canister_size: str = "medium") -> Marks:
    """The marks after a watermark was dragged so its centre is at (cx, cy) - fractions of the picture - and resized by `ratio` (1 = unchanged).

    The mark's position menu becomes Custom, and the canister's menus too (its size is remembered as a custom one)."""
    cx, cy = _clamp(cx, 0.0, 1.0), _clamp(cy, 0.0, 1.0)
    if abs(ratio - 1.0) < 0.005:
        ratio = 1.0
    if name == "text":
        return dataclasses.replace(marks, text_position=CUSTOM, text_x=cx, text_y=cy, text_size=_clamp(marks.text_size * ratio, *TEXT_SIZE_RANGE))
    if name == "logo":
        return dataclasses.replace(marks, logo_position=CUSTOM, logo_x=cx, logo_y=cy, logo_size=_clamp(marks.logo_size * ratio, *LOGO_SIZE_RANGE))
    if name == "info":
        return dataclasses.replace(marks, info_position=CUSTOM, info_x=cx, info_y=cy, info_size=_clamp(marks.info_size * ratio, *INFO_SIZE_RANGE))
    if name == "canister":
        size = marks.canister_size
        if ratio != 1.0 or size > 0:
            size = _clamp(long_side_fraction(canister_size if canister_size in SIZES else "medium", marks.canister_size) * ratio, *CANISTER_SIZE_RANGE)
        return dataclasses.replace(marks, canister_x=cx, canister_y=cy, canister_size=size)
    return marks


def unframe_shape(shape, border: float) -> tuple[int, int, int]:
    """(height, width, frame width) of the picture inside a frame, given the shape of the framed picture and the border setting.

    Inverts what Finishing's border adds: the frame is a share of the picture's shorter side, rounded to whole pixels."""
    from ..finishing.logic import border_pixels

    h, w = shape[:2]
    if border <= 0:
        return h, w, 0
    short = min(h, w)
    guess = round(short / (1.0 + 2.0 * border))
    for short_c in sorted(range(guess - 2, guess + 3), key=lambda v: abs(v - guess)):
        if short_c <= 0:
            continue
        b = border_pixels((short_c, short_c), border)
        if short_c + 2 * b == short:
            return h - 2 * b, w - 2 * b, b
    b = border_pixels((guess, guess), border)
    return max(1, h - 2 * b), max(1, w - 2 * b), b
