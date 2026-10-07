"""Finding the picture inside a scan - numpy + OpenCV, no Qt/UI imports."""

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

_WORK_SIZE = 800
_RING = 0.025
_MIN_AREA = 0.15
_FULL_FRAME = 0.985
AUTO_STRAIGHTEN_MIN = 0.2
AUTO_STRAIGHTEN_MAX = 6.0


@dataclass(frozen=True)
class FrameDetection:
    rect: tuple[int, int, int, int]
    skew_deg: float
    coverage: float


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
    ring_diff = diff[ring]
    median = float(np.median(ring_diff))
    sigma = 1.4826 * float(np.median(np.abs(ring_diff - median)))
    threshold = max(14.0, median + 8.0 * sigma + 4.0)
    mask = (diff > threshold).astype(np.uint8) * 255

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
