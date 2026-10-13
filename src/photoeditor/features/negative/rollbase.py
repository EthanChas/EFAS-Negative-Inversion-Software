"""A film base for a whole roll, read from the clear border around its frames - numpy + OpenCV, no Qt.

Measuring each picture on its own is thrown off by what is in it: a snow scene or a sunset moves the percentile the inversion falls back on. The unexposed border
around a frame is the same film on every frame of a roll, so reading it from several frames gives one steady film base for all of them. Only frames with a clear
border count, and the roll is only given a base when enough of them agree."""

from dataclasses import dataclass

import numpy as np

from ..geometry.autocrop import detect_frame

MAX_SPREAD = 10.0      # how uneven one frame's border may be (grey levels) before it is not trusted
MAX_DISAGREE = 14.0    # how far a frame's border may be from the roll's median (grey levels, any channel) and still count
MIN_FRAMES = 2
_RING = 0.02


@dataclass(frozen=True)
class RollBase:
    rgb: tuple[int, int, int]
    frames: int          # how many frames the base was read from
    checked: int         # how many frames were looked at
    spread: float        # how far apart the frames' borders were, in grey levels


def frame_border(rgb8: np.ndarray) -> tuple[tuple[float, float, float], float] | None:
    """(border colour, unevenness) of one frame as it looks in the picture, or None when the frame has no clear border around it."""
    if detect_frame(rgb8) is None:
        return None
    h, w = rgb8.shape[:2]
    t = max(2, int(min(h, w) * _RING))
    ring = np.concatenate([rgb8[:t].reshape(-1, 3), rgb8[-t:].reshape(-1, 3), rgb8[t:-t, :t].reshape(-1, 3), rgb8[t:-t, -t:].reshape(-1, 3)]).astype(np.float64)
    med = np.median(ring, axis=0)
    spread = float(np.median(np.abs(ring - med), axis=0).max() * 1.4826)
    return (float(med[0]), float(med[1]), float(med[2])), spread


def estimate(frames: list[np.ndarray]) -> RollBase | None:
    """The roll's film base from 8-bit RGB pictures of its frames, or None when too few have a clear, even border or they do not agree."""
    found = []
    for f in frames:
        border = frame_border(f)
        if border is not None and border[1] <= MAX_SPREAD:
            found.append(border[0])
    if len(found) < MIN_FRAMES:
        return None
    colours = np.array(found)
    centre = np.median(colours, axis=0)
    agree = colours[np.abs(colours - centre).max(axis=1) <= MAX_DISAGREE]
    if len(agree) < MIN_FRAMES or len(agree) * 2 < len(found):
        return None
    base = np.median(agree, axis=0)
    rgb = tuple(int(max(1, min(254, round(v)))) for v in base)
    return RollBase(rgb, len(agree), len(frames), float(np.abs(agree - base).max()))
