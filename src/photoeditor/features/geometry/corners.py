"""Straightening a picture from its four corners - numpy only, no Qt/UI imports.

The person clicks the four corners of the photo (of the frame, not of the scan around it). From those four points this works out the Angle (fine rotation) and the
Keystone (vertical and horizontal) that make the picture a true rectangle, and the crop that fits inside it - the same controls the sliders drive, so the result can
be adjusted by hand afterwards.

The pipeline turns the picture by the angle, undoes lens distortion, then applies the keystone; so the clicked points are first taken back to the scan as it was
before any of that (undoing the picture's current corrections), and the three numbers are solved for from there, in a few Gauss-Newton steps, so that the four
points land on the corners of an upright rectangle. The keystone controls are two numbers, so four arbitrary points cannot always be made exactly rectangular; the
residual says how close it got.
"""
import math
from dataclasses import dataclass, field

import numpy as np

from .logic import FINE_ROTATION_LIMIT, _fine_matrix, _keystone_matrix, map_display_to_raw, map_raw_to_display

_KEYSTONE_EPS = 1e-4
_ITERATIONS = 40
MIN_CROP = 8  # pixels
STRONG_KEYSTONE = 0.6  # a correction this big is usually a mis-click


@dataclass(frozen=True)
class CornerResult:
    fine_rotation: float  # degrees, positive clockwise (the Angle slider)
    keystone_v: float
    keystone_h: float
    crop_rect: tuple[int, int, int, int] | None  # x1, y1, x2, y2 in pixels of the picture before the crop
    residual: float  # how far (in pixels, rms) the corners are from a perfect rectangle after the correction
    notes: tuple[str, ...] = field(default_factory=tuple)


def order_corners(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Four points in any order -> top-left, top-right, bottom-right, bottom-left (as seen on screen, y down)."""
    pts = [(float(x), float(y)) for x, y in points]
    top_left = min(pts, key=lambda p: p[0] + p[1])
    bottom_right = max(pts, key=lambda p: p[0] + p[1])
    top_right = max(pts, key=lambda p: p[0] - p[1])
    bottom_left = min(pts, key=lambda p: p[0] - p[1])
    return [top_left, top_right, bottom_right, bottom_left]


def _forward(raw: np.ndarray, theta: float, v: float, h: float, dist: float, w: int, hgt: int) -> np.ndarray:
    """Points of the raw frame (0..1 fractions, N x 2) -> where the angle, lens correction and keystone put them (0..1 fractions of the same frame)."""
    if dist:
        return np.array([map_raw_to_display(float(x), float(y), None, (hgt, w), 0, False, False, theta, dist, v, h) for x, y in raw])
    pts = np.column_stack([raw[:, 0] * w, raw[:, 1] * hgt, np.ones(len(raw))])
    pts = (_fine_matrix(theta, w, hgt) @ pts.T).T
    out = np.column_stack([pts[:, 0] / w, pts[:, 1] / hgt])
    if abs(v) >= _KEYSTONE_EPS or abs(h) >= _KEYSTONE_EPS:
        hom = np.column_stack([out[:, 0] * (w - 1), out[:, 1] * (hgt - 1), np.ones(len(out))])
        res = (_keystone_matrix(v, h, w, hgt) @ hom.T).T
        out = np.column_stack([res[:, 0] / res[:, 2] / (w - 1), res[:, 1] / res[:, 2] / (hgt - 1)])
    return out


def _to_display(frac: np.ndarray, frame: tuple[int, int], turns: int, flip_h: bool, flip_v: bool) -> np.ndarray:
    """Fractions of the corrected frame in raw orientation -> pixels of the picture as it is shown (turned and flipped), before the crop."""
    h, w = frame
    dh, dw = (w, h) if turns % 2 else (h, w)
    out = np.array([map_raw_to_display(float(x), float(y), None, (dh, dw), turns, flip_h, flip_v) for x, y in frac])
    return np.column_stack([out[:, 0] * dw, out[:, 1] * dh])


def _residuals(raw, params, frame, turns, flip_h, flip_v, dist):
    h, w = frame
    p = _to_display(_forward(raw, params[0], params[1], params[2], dist, w, h), frame, turns, flip_h, flip_v)
    tl, tr, br, bl = p
    return np.array([bl[0] - tl[0], br[0] - tr[0], tr[1] - tl[1], br[1] - bl[1]]), p


def _initial_angle(display: list[tuple[float, float]]) -> float:
    (tlx, tly), (trx, try_), (brx, bry), (blx, bly) = display
    top = math.degrees(math.atan2(try_ - tly, trx - tlx))
    bottom = math.degrees(math.atan2(bry - bly, brx - blx))
    left = math.degrees(math.atan2(bly - tly, blx - tlx)) - 90.0
    right = math.degrees(math.atan2(bry - try_, brx - trx)) - 90.0
    return (top + bottom + left + right) / 4.0


def straighten_from_corners(
    clicks: list[tuple[float, float]],
    frame_size: tuple[int, int],
    turns: int = 0,
    flip_h: bool = False,
    flip_v: bool = False,
    fine_rotation: float = 0.0,
    distortion: float = 0.0,
    keystone_v: float = 0.0,
    keystone_h: float = 0.0,
) -> CornerResult:
    """`clicks`: four corners as 0..1 fractions of the picture as shown before the crop (any order). `frame_size` is (height, width) of that picture; the
    rest are the picture's current geometry. Returns the angle, keystone and crop that make the clicked shape an upright rectangle."""
    if len(clicks) != 4:
        raise ValueError("Four corners are needed.")
    display_h, display_w = frame_size
    ordered = order_corners(clicks)
    notes: list[str] = []
    area = 0.5 * abs(sum(ordered[i][0] * ordered[(i + 1) % 4][1] - ordered[(i + 1) % 4][0] * ordered[i][1] for i in range(4)))
    if area < 0.02:
        raise ValueError("Those four points are too close together: click the four corners of the photo.")
    # back to the scan before the picture's own angle, lens correction and keystone
    raw = np.array([map_display_to_raw(u, v, None, frame_size, turns, flip_h, flip_v, fine_rotation, distortion, keystone_v, keystone_h) for u, v in ordered])
    # the corrected frame is in the scan's own orientation; with odd quarter turns its width and height swap
    raw_h, raw_w = (display_w, display_h) if turns % 2 else (display_h, display_w)
    raw_frame = (raw_h, raw_w)
    pixel_clicks = [(u * display_w, v * display_h) for u, v in ordered]
    base = _initial_angle(pixel_clicks)

    best = None
    for sign in (1.0, -1.0):
        params = np.array([max(-FINE_ROTATION_LIMIT, min(FINE_ROTATION_LIMIT, sign * base)), 0.0, 0.0])
        damping = 1e-3
        r, _ = _residuals(raw, params, raw_frame, turns, flip_h, flip_v, distortion)
        cost = float(r @ r)
        for _ in range(_ITERATIONS):
            jac = np.zeros((4, 3))
            for k, eps in enumerate((1e-3, 1e-4, 1e-4)):
                step = params.copy()
                step[k] += eps
                jac[:, k] = (_residuals(raw, step, raw_frame, turns, flip_h, flip_v, distortion)[0] - r) / eps
            lhs = jac.T @ jac + damping * np.eye(3)
            try:
                delta = np.linalg.solve(lhs, -jac.T @ r)
            except np.linalg.LinAlgError:
                break
            trial = params + delta
            trial[0] = max(-FINE_ROTATION_LIMIT, min(FINE_ROTATION_LIMIT, trial[0]))
            trial[1:] = np.clip(trial[1:], -1.0, 1.0)
            new_r, _ = _residuals(raw, trial, raw_frame, turns, flip_h, flip_v, distortion)
            new_cost = float(new_r @ new_r)
            if new_cost < cost:
                improved = cost - new_cost
                params, r, cost = trial, new_r, new_cost
                damping = max(damping / 3, 1e-9)
                if improved < 1e-10 or cost < 1e-10:
                    break
            else:
                damping *= 5
                if damping > 1e8:
                    break
        if best is None or cost < best[0]:
            best = (cost, params)
    _, params = best
    theta, v, h = round(float(params[0]), 2), round(float(params[1]), 3), round(float(params[2]), 3)
    r, shown = _residuals(raw, np.array([theta, v, h]), raw_frame, turns, flip_h, flip_v, distortion)
    residual = float(math.sqrt(np.mean(r ** 2)))
    if residual > 0.02 * max(display_w, display_h):
        notes.append("The four points are not quite a rectangle seen in perspective (the keystone controls cannot make them exactly square); this is the closest fit.")
    if abs(v) > STRONG_KEYSTONE or abs(h) > STRONG_KEYSTONE:
        notes.append("That is a very strong keystone correction: check that the four points are on the photo's own corners, and that none is missing or in the wrong place.")
    tl, tr, br, bl = shown
    x1, x2 = max(tl[0], bl[0], 0.0), min(tr[0], br[0], float(display_w))
    y1, y2 = max(tl[1], tr[1], 0.0), min(bl[1], br[1], float(display_h))
    rect = None
    if x2 - x1 >= MIN_CROP and y2 - y1 >= MIN_CROP:
        rect = (int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2)))
    else:
        notes.append("Nothing was left to crop to: check that you clicked the four corners.")
    return CornerResult(theta, v, h, rect, residual, tuple(notes))
