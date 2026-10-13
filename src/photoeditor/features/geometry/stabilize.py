"""Making the crops of a roll the same size - pure numpy, no Qt/UI imports.

Auto crop finds each frame's border on its own, so the crops of one roll come out a few pixels different from each other (a slightly different amount of border
caught each time). On a roll that was scanned in one holder, the frames are all the same size: this works out the size they share and re-centres each crop on
what was found, so a contact sheet or a slideshow does not jump from frame to frame.

Frames are grouped by orientation (landscape and portrait frames have their own size). A crop far from the group's usual size is not a normal frame (a
half-frame, a double exposure, a scan that only partly shows the border) and is left exactly as it was found.
"""
from dataclasses import dataclass

import numpy as np

Rect = tuple[int, int, int, int]  # x1, y1, x2, y2 in the pixels of the frame (the picture before the crop)

TOLERANCE = 0.12  # a crop within this fraction of the group's median size, in width and in height, counts as an ordinary frame
MIN_FRAMES = 2
LOWER_QUARTILE = 25.0  # the shared size: a crop at least as small as three quarters of the frames had, so no frame takes in more border than it was found with


@dataclass(frozen=True)
class Target:
    """The size a group of frames shares, and the size that was typical, as fractions of the frame's width and height."""
    width: float
    height: float
    median_width: float
    median_height: float


def orientation(frame_w: int, frame_h: int) -> str:
    return "landscape" if frame_w >= frame_h else "portrait"


def _fractions(rect: Rect, frame_w: int, frame_h: int) -> tuple[float, float]:
    return (rect[2] - rect[0]) / frame_w, (rect[3] - rect[1]) / frame_h


def _close(value: float, centre: float) -> bool:
    return centre > 0 and abs(value - centre) <= TOLERANCE * centre


def targets(found: list[tuple[int, int, Rect]]) -> dict[str, Target]:
    """For each orientation with at least two ordinary crops: the size they share. `found` is (frame width, frame height, crop) for every cropped frame."""
    groups: dict[str, list[tuple[float, float]]] = {}
    for frame_w, frame_h, rect in found:
        if frame_w > 0 and frame_h > 0 and rect[2] > rect[0] and rect[3] > rect[1]:
            groups.setdefault(orientation(frame_w, frame_h), []).append(_fractions(rect, frame_w, frame_h))
    out: dict[str, Target] = {}
    for name, sizes in groups.items():
        if len(sizes) < MIN_FRAMES:
            continue
        median_w = float(np.median([s[0] for s in sizes]))
        median_h = float(np.median([s[1] for s in sizes]))
        ordinary = [s for s in sizes if _close(s[0], median_w) and _close(s[1], median_h)]
        if len(ordinary) < MIN_FRAMES:
            continue
        out[name] = Target(
            float(np.percentile([s[0] for s in ordinary], LOWER_QUARTILE)), float(np.percentile([s[1] for s in ordinary], LOWER_QUARTILE)), median_w, median_h,
        )
    return out


def stabilize(rect: Rect, frame_w: int, frame_h: int, shared: dict[str, Target]) -> Rect:
    """The crop at the shared size of its group, centred where this frame's own crop was (moved inward if that would leave the frame). A frame whose crop is
    not an ordinary one for its group, or a group with no shared size, gets its crop back unchanged."""
    target = shared.get(orientation(frame_w, frame_h))
    if target is None or frame_w <= 0 or frame_h <= 0:
        return rect
    own_w, own_h = _fractions(rect, frame_w, frame_h)
    if not (_close(own_w, target.median_width) and _close(own_h, target.median_height)):
        return rect
    width = max(1, min(frame_w, round(target.width * frame_w)))
    height = max(1, min(frame_h, round(target.height * frame_h)))
    centre_x, centre_y = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    x1 = int(round(min(max(centre_x - width / 2, 0), frame_w - width)))
    y1 = int(round(min(max(centre_y - height / 2, 0), frame_h - height)))
    return (x1, y1, x1 + width, y1 + height)
