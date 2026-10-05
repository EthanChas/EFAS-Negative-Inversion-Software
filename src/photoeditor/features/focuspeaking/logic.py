"""Focus peaking - numpy + OpenCV, no Qt imports. Follows darktable's method (src/common/focus_peaking.h):

1. luminance from the picture's pixels, sqrt(R^2.2 + G^2.2 + B^2.2) with the channels in 0-1;
2. an edge-preserving blur, so grain and noise do not read as detail (darktable's "surface blur"; here OpenCV's bilateral filter);
3. a sharpness measure per pixel: the gradient magnitude at distance 1 minus 0.67 x the one at distance 2 (less 1/256) - a fine edge scores
   high, a soft transition, which has the same gradient at both distances, scores low. Each gradient is the mean of the principal and the
   diagonal hypot(dx, dy);
4. thresholds from the picture itself, not fixed numbers: the mean of that measure plus 2.5, 5 and 10 times its mean absolute deviation;
5. the levels marked blue, green and yellow, each grown a little so scattered hits join into regions; a fourth level, red, is added for the
   very sharpest (20 deviations, twice darktable's top one). The caller picks the weakest level to show, so sliding up leaves only the
   sharper points.
"""

from typing import Optional

import cv2
import numpy as np

WORK_MAX = 2000                 # the longest side the analysis runs at; the result is stretched over the picture
SIGMA_LEVELS = (2.5, 5.0, 10.0, 20.0)  # darktable's three (mean + k x deviation), and red above them
FAR_WEIGHT = 0.67
FAR_OFFSET = 0.00390625          # 1/256
LUMA_EXPONENT = 2.2
COLORS = ((40, 120, 255), (60, 225, 90), (255, 225, 0), (255, 50, 50))  # blue (some detail), green (sharp), yellow (very sharp), red (the sharpest)
NAMES = ("Blue", "Green", "Yellow", "Red")
ALPHA = 235
_BORDER = 2                       # the measure needs two pixels on every side


def luma(rgb: np.ndarray) -> np.ndarray:
    f = rgb.astype(np.float32) / 255.0
    return np.sqrt(np.sum(np.power(f, LUMA_EXPONENT), axis=2))


def _smooth(img: np.ndarray, passes: int = 2) -> np.ndarray:
    for _ in range(passes):
        img = cv2.bilateralFilter(img, 5, 0.03, 3.0)  # the colour sigma is in luma units (0 - 1.73)
    return img


def _gradient(img: np.ndarray, d: int) -> np.ndarray:
    """The mean of the principal and the diagonal gradient magnitude at distance d, for every pixel at least 2 from the edge."""
    h, w = img.shape

    def shifted(dy: int, dx: int) -> np.ndarray:
        return img[_BORDER + dy * d: h - _BORDER + dy * d, _BORDER + dx * d: w - _BORDER + dx * d]

    principal = np.hypot(shifted(0, 1) - shifted(0, -1), shifted(1, 0) - shifted(-1, 0))
    diagonal = np.hypot(shifted(1, 1) - shifted(-1, -1), shifted(1, -1) - shifted(-1, 1))
    return (principal + diagonal) / 2.0


def sharpness_map(rgb: np.ndarray) -> np.ndarray:
    """The sharpness measure for the picture's interior (2 pixels smaller on each side)."""
    smooth = _smooth(luma(rgb))
    return _gradient(smooth, 1) - FAR_WEIGHT * (_gradient(smooth, 2) - FAR_OFFSET)


def thresholds(measure: np.ndarray) -> Optional[tuple[float, ...]]:
    mean = float(measure.mean())
    deviation = float(np.abs(measure - mean).mean())
    if deviation < 1e-7:  # a flat picture has nothing in focus to find
        return None
    return tuple(mean + k * deviation for k in SIGMA_LEVELS)


def level_map(rgb: np.ndarray) -> Optional[np.ndarray]:
    """How sharp each spot is, as a uint8 map: 0 nothing, 1 blue, 2 green, 3 yellow, 4 red. At most WORK_MAX on its longer side (meant to be
    stretched over the picture). None when nothing stands out. The slow part - the colors are chosen from it cheaply by overlay_from_levels."""
    h, w = rgb.shape[:2]
    if min(h, w) < 16:
        return None
    k = min(1.0, WORK_MAX / max(h, w))
    small = cv2.resize(rgb, (max(16, round(w * k)), max(16, round(h * k))), interpolation=cv2.INTER_AREA) if k < 1.0 else rgb
    measure = sharpness_map(small)
    levels = thresholds(measure)
    if levels is None:
        return None
    sh, sw = small.shape[:2]
    out = np.zeros((sh, sw), dtype=np.uint8)
    grow = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    inner = out[_BORDER:sh - _BORDER, _BORDER:sw - _BORDER]
    for number, threshold in enumerate(levels, start=1):  # weakest first, so a sharper level paints over it
        mask = cv2.dilate((measure > threshold).astype(np.uint8), grow).astype(bool)
        inner[mask] = number
    return out if out.any() else None


def overlay_from_levels(levels: Optional[np.ndarray], weakest: int = 0) -> Optional[np.ndarray]:
    """An RGBA overlay of the spots at level weakest (0 blue ... 3 red) or sharper, each in its own color; None when none remain."""
    if levels is None:
        return None
    keep = levels > max(0, min(len(COLORS) - 1, weakest))  # level numbers start at 1 for blue
    if not keep.any():
        return None
    out = np.zeros((*levels.shape, 4), dtype=np.uint8)
    for number, color in enumerate(COLORS, start=1):
        if number - 1 >= weakest:
            out[levels == number] = (*color, ALPHA)
    return out


def peaking_overlay(rgb: np.ndarray, weakest: int = 0) -> Optional[np.ndarray]:
    """An RGBA overlay marking what is in focus (level_map, then overlay_from_levels), or None when nothing stands out."""
    return overlay_from_levels(level_map(rgb), weakest)
