"""Finding the picture inside a scan - numpy + OpenCV, no Qt/UI imports.

A film scan has the frame in the middle and a border around it: the film's own rebate, sprocket holes, the holder, the light beyond the
film. On the inverted (positive) image all of that is close to one flat colour, so the frame is whatever is not that colour. The border
colour is read from the outer ring of the picture, the pixels that differ from it are gathered into one blob, and its tilt and
bounding box are measured."""

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

_WORK_SIZE = 800          # the longest side the detection runs at
_RING = 0.025             # width of the outer ring (fraction of the shorter side) the border colour is read from
_MIN_AREA = 0.15          # a frame smaller than this share of the scan is not believable
_FULL_FRAME = 0.985       # a "frame" this close to the whole scan means there is no border to crop
AUTO_STRAIGHTEN_MIN = 0.2  # degrees: a frame tilted less than this is level enough
AUTO_STRAIGHTEN_MAX = 6.0  # more than this is more likely a mis-detection than a crooked scan, so it is left alone


@dataclass(frozen=True)
class FrameDetection:
    rect: tuple[int, int, int, int]  # x1, y1, x2, y2 of the frame (the tilt is measured separately), in the image's own pixels
    skew_deg: float                  # how far the frame's long edge is rotated clockwise from level, -45..45
    coverage: float                  # the frame's share of the whole picture


def detect_frame(rgb: np.ndarray, inset: float = 0.004) -> Optional[FrameDetection]:
    """The frame in an uint8 RGB image, or None when there is no clear border (the picture runs to the edges, or the scan is blank).
    inset pulls the rectangle in by that fraction of the picture so the crop sits inside the frame's own edge."""
    import cv2

    h, w = rgb.shape[:2]
    if h < 32 or w < 32:
        return None
    k = min(1.0, _WORK_SIZE / max(h, w))
    small = cv2.resize(rgb, (max(8, round(w * k)), max(8, round(h * k))), interpolation=cv2.INTER_AREA) if k < 1.0 else rgb
    sh, sw = small.shape[:2]
    f = small.astype(np.float32)

    ring_w = max(2, int(min(sh, sw) * _RING))
    ring = np.zeros((sh, sw), dtype=bool)
    ring[:ring_w, :] = ring[-ring_w:, :] = True
    ring[:, :ring_w] = ring[:, -ring_w:] = True
    border = np.median(f[ring], axis=0)
    diff = cv2.GaussianBlur(np.abs(f - border).max(axis=2), (0, 0), 2.0)
    # Well above the ring's own noise (grain, dust), so the border itself is never taken for picture. The median and MAD ignore
    # what sits in the ring but is not border - sprocket holes, edge printing - however much of it there is, up to half.
    ring_diff = diff[ring]
    median = float(np.median(ring_diff))
    sigma = 1.4826 * float(np.median(np.abs(ring_diff - median)))
    threshold = max(14.0, median + 8.0 * sigma + 4.0)
    mask = (diff > threshold).astype(np.uint8) * 255

    # First drop everything small - sprocket holes, edge printing, dust - so that it cannot be bridged onto the frame; then close the
    # flat patches (sky, shadow) inside the frame itself.
    small_blob = max(5, int(min(sh, sw) * 0.06)) | 1
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (small_blob, small_blob)))
    gap = max(5, int(min(sh, sw) * 0.05)) | 1
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (gap, gap)))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < _MIN_AREA * sh * sw:
        return None

    x, y, bw, bh = cv2.boundingRect(contour)
    if bw >= _FULL_FRAME * sw and bh >= _FULL_FRAME * sh:
        return None

    # the tilt: the direction of the min-area rectangle's longer edge, folded into -45..45
    (_cx, _cy), (rw, rh), _a = cv2.minAreaRect(contour)
    box = cv2.boxPoints(((_cx, _cy), (rw, rh), _a))
    edges = [box[(i + 1) % 4] - box[i] for i in range(4)]
    long_edge = max(edges, key=lambda e: math.hypot(e[0], e[1]))
    skew = math.degrees(math.atan2(long_edge[1], long_edge[0]))
    skew = (skew + 45.0) % 90.0 - 45.0

    pad_x, pad_y = inset * sw, inset * sh
    x1, y1 = max(0.0, x + pad_x), max(0.0, y + pad_y)
    x2, y2 = min(float(sw), x + bw - pad_x), min(float(sh), y + bh - pad_y)
    if x2 - x1 < 8 or y2 - y1 < 8:
        return None
    inv = 1.0 / k
    rect = (round(x1 * inv), round(y1 * inv), round(x2 * inv), round(y2 * inv))
    return FrameDetection(rect=rect, skew_deg=round(skew, 2), coverage=float((x2 - x1) * (y2 - y1) / (sw * sh)))
