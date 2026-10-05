"""Finding the picture inside a scan by its edge's gradient - numpy + OpenCV, no Qt/UI imports.

autocrop.py asks "which pixels differ from the border colour?", which a dark sky against a dark rebate, or a vignetted corner, can fool: the
picture fades into the border and there is no clear difference to threshold. This looks instead for what is always there: the *transition*.
The border is a flat, solid colour, so its gradient is only grain; where the picture begins the colour starts to change, however softly,
and that change is a line of gradient running along the whole side of the frame.

  1. Gradient: the picture's Sobel gradient (per channel, the strongest wins). The noise floor is read from the outer ring, which is border.
  2. Tilt: a true frame edge is a long straight line of gradient. Turning the gradient map by the right angle puts each edge into one row (or
     column), so it is the angle at which the edge rows/columns are most concentrated.
  3. Sides: from each side inward, the first row (column) where a long run of gradient starts is the beginning of the picture; the crop goes
     where that gradient ramp ends, so none of the border colour is left in. Sprocket holes, edge printing and dust are short runs, and
     lines running the other way, so they do not count; the outer ring is skipped, because the film's own edge and the holder are there."""

import math
from typing import Optional

import numpy as np

from .autocrop import AUTO_STRAIGHTEN_MAX, AUTO_STRAIGHTEN_MIN, FrameDetection

_WORK_SIZE = 800          # the longest side the detection runs at
_RING = 0.025             # width of the outer ring (fraction of the shorter side): border only, read for the noise floor and skipped by the search
_LINE_SHARE = 0.4         # a side's gradient line has to run along at least this share of the picture's width (height)
_GAP = 0.02               # breaks in a line shorter than this share are bridged (a flat sky has no gradient to hold the line together)
_MIN_AREA = 0.15          # a frame smaller than this share of the scan is not believable
_FULL_FRAME = 0.985       # a frame this close to the whole scan means there is no border to crop
_MIN_SIDES = 2            # fewer sides than this found: the "border" is more likely an edge of the picture's own than a frame
_ANGLE_STEP = 0.5         # degrees: the coarse search; it is then refined to 0.1


def _longest_runs(mask: np.ndarray) -> np.ndarray:
    """For every row of a boolean mask, the length of its longest run of True."""
    padded = np.pad(mask.astype(np.int8), ((0, 0), (1, 1)))
    step = np.diff(padded, axis=1)
    rows_up, cols_up = np.nonzero(step == 1)
    rows_down, cols_down = np.nonzero(step == -1)
    runs = np.zeros(mask.shape[0], dtype=np.int32)
    np.maximum.at(runs, rows_up, cols_down - cols_up)  # np.nonzero lists both in row order, so the k-th start pairs with the k-th end
    return runs


def _edge_from_outside(runs: np.ndarray, strength: np.ndarray, start: int, stop: int, need: float, window: int) -> Optional[int]:
    """Scanning from `start` toward `stop` (either direction), where the first gradient ramp whose line is `need` long ends: the index of the
    first line inside the picture. The ramp begins where the line first appears; its steepest line (the peak of `strength`) is its middle, and a
    soft edge fades in and out evenly, so it ends as far past the peak as it began before it. (The picture's own texture, which can be
    gradient all the way in, never has a say in where the ramp ends.)"""
    step = 1 if stop > start else -1
    i = start
    while i != stop and runs[i] < need:
        i += step
    if i == stop:
        return None
    reach = [j for j in range(i, i + step * (window + 1), step) if 0 <= j < len(strength)]
    peak = max(reach, key=lambda j: strength[j])
    return peak + (peak - i) + step


def detect_gradient_frame(rgb: np.ndarray, inset: float = 0.002, max_skew: float = AUTO_STRAIGHTEN_MAX) -> Optional[FrameDetection]:
    """The frame in an uint8 RGB image, found by the gradient at its edge; None when no border is found. max_skew is how crooked (degrees, each
    way) the frame may be - 0 looks only for an upright one, and the rectangle is then exact; otherwise the rectangle returned is the bounding
    box of the tilted frame (straighten first, then ask again, to get the exact one). inset pulls the crop in by that share of the picture."""
    import cv2

    h, w = rgb.shape[:2]
    if h < 32 or w < 32:
        return None
    k = min(1.0, _WORK_SIZE / max(h, w))
    small = cv2.resize(rgb, (max(8, round(w * k)), max(8, round(h * k))), interpolation=cv2.INTER_AREA) if k < 1.0 else rgb
    sh, sw = small.shape[:2]
    blur = cv2.GaussianBlur(small.astype(np.float32), (0, 0), 1.2)
    ax = np.abs(cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=3)).max(axis=2)
    ay = np.abs(cv2.Sobel(blur, cv2.CV_32F, 0, 1, ksize=3)).max(axis=2)
    mag = np.hypot(ax, ay)

    ring_w = max(2, int(min(sh, sw) * _RING))
    ring = np.zeros((sh, sw), dtype=bool)
    ring[:ring_w, :] = ring[-ring_w:, :] = True
    ring[:, :ring_w] = ring[:, -ring_w:] = True
    floor = float(np.median(mag[ring]))
    sigma = 1.4826 * float(np.median(np.abs(mag[ring] - floor)))
    thr = max(5.0, floor + 5.0 * sigma + 1.5)  # above the border's own grain, but low enough for a soft, wide ramp

    active = (mag > thr).astype(np.uint8)
    horizontal = (ay > thr).astype(np.uint8)  # lines running along the top and bottom edges
    vertical = (ax > thr).astype(np.uint8)    # lines running along the left and right edges
    centre = (sw / 2.0, sh / 2.0)

    def turned(mask: np.ndarray, angle: float) -> np.ndarray:
        if angle == 0.0:
            return mask
        m = cv2.getRotationMatrix2D(centre, angle, 1.0)
        return cv2.warpAffine(mask, m, (sw, sh), flags=cv2.INTER_NEAREST, borderValue=0)

    def turned_float(values: np.ndarray, angle: float) -> np.ndarray:
        if angle == 0.0:
            return values
        return cv2.warpAffine(values, cv2.getRotationMatrix2D(centre, angle, 1.0), (sw, sh), flags=cv2.INTER_LINEAR, borderValue=0)

    def concentration(angle: float) -> float:
        """How much of each side's gradient piles into one line when the map is turned by `angle`: the steepest row of the top and bottom
        thirds and the steepest column of the left and right thirds, summed. A turned edge is smeared over many rows, a level one is not."""
        rows, cols = turned_float(ay, angle).mean(axis=1), turned_float(ax, angle).mean(axis=0)
        return float(rows[ring_w: sh // 3].max() + rows[2 * sh // 3: sh - ring_w].max() + cols[ring_w: sw // 3].max() + cols[2 * sw // 3: sw - ring_w].max())

    angle = 0.0
    if max_skew > 0:
        coarse = np.arange(-max_skew, max_skew + 1e-9, _ANGLE_STEP)
        scores = [concentration(float(a)) for a in coarse]
        best = float(coarse[int(np.argmax(scores))])
        fine = np.arange(best - _ANGLE_STEP, best + _ANGLE_STEP + 1e-9, 0.1)
        fine_scores = [concentration(float(a)) for a in fine]
        angle = round(float(fine[int(np.argmax(fine_scores))]), 1)
        if abs(angle) < AUTO_STRAIGHTEN_MIN or concentration(angle) < concentration(0.0) * 1.03:
            angle = 0.0  # level enough, or no better than level

    bridge_h = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(sw * _GAP)) | 1, 1))
    bridge_v = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(sh * _GAP)) | 1, 1))
    h_lines = cv2.morphologyEx(turned(horizontal, angle), cv2.MORPH_CLOSE, bridge_h) > 0
    v_lines = cv2.morphologyEx(turned(vertical, angle).T.copy(), cv2.MORPH_CLOSE, bridge_v) > 0  # columns, as rows
    run_h, run_v = _longest_runs(h_lines), _longest_runs(v_lines)
    strength_h = turned_float(ay, angle).mean(axis=1)  # how steep the gradient is along each row ...
    strength_v = turned_float(ax, angle).mean(axis=0)  # ... and each column
    win_h, win_v = max(4, int(sh * 0.05)), max(4, int(sw * 0.05))

    need_h, need_v = _LINE_SHARE * sw, _LINE_SHARE * sh
    top = _edge_from_outside(run_h, strength_h, ring_w, sh // 2, need_h, win_h)
    bottom = _edge_from_outside(run_h, strength_h, sh - 1 - ring_w, sh // 2, need_h, win_h)
    left = _edge_from_outside(run_v, strength_v, ring_w, sw // 2, need_v, win_v)
    right = _edge_from_outside(run_v, strength_v, sw - 1 - ring_w, sw // 2, need_v, win_v)
    if sum(edge is not None for edge in (top, bottom, left, right)) < _MIN_SIDES:
        return None
    x1 = float(left if left is not None else 0)
    y1 = float(top if top is not None else 0)
    x2 = float(right + 1 if right is not None else sw)  # the right/bottom edge index is the last line of the border; the crop starts after it
    y2 = float(bottom + 1 if bottom is not None else sh)
    pad_x, pad_y = inset * sw, inset * sh
    x1, y1, x2, y2 = x1 + pad_x, y1 + pad_y, x2 - pad_x, y2 - pad_y
    if x2 - x1 < 8 or y2 - y1 < 8:
        return None
    area = (x2 - x1) * (y2 - y1) / (sw * sh)
    if area < _MIN_AREA or ((x2 - x1) >= _FULL_FRAME * sw and (y2 - y1) >= _FULL_FRAME * sh):
        return None

    if angle != 0.0:  # the frame was found in the turned picture: its corners, back in the picture's own pixels
        inv = cv2.invertAffineTransform(cv2.getRotationMatrix2D(centre, angle, 1.0))
        corners = np.array([[x1, y1, 1.0], [x2, y1, 1.0], [x2, y2, 1.0], [x1, y2, 1.0]], dtype=np.float64) @ inv.T
        x1, y1 = max(0.0, float(corners[:, 0].min())), max(0.0, float(corners[:, 1].min()))
        x2, y2 = min(float(sw), float(corners[:, 0].max())), min(float(sh), float(corners[:, 1].max()))
    scale = 1.0 / k
    rect = (round(x1 * scale), round(y1 * scale), round(x2 * scale), round(y2 * scale))
    return FrameDetection(rect=rect, skew_deg=angle, coverage=float(area))
