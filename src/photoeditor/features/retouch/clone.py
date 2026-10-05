"""Clone strokes - copy film from one place over a defect. numpy + OpenCV, no Qt imports. After NegPy's clone tool.

A stroke is (points, size, dx, dy, strength, feather, match_tone):
- points: the brush path as 0-1 [x, y] pairs of the raw frame; size: the brush diameter at HEAL_SIZE_REF (like a heal brush, so it means the
  same on a preview and on a full-size export);
- dx, dy: where the source lies relative to the brush, as a fraction of the frame - fixed by the first stroke after the source is picked,
  and the same for the strokes after it;
- strength 0-1 scales the blend; feather 0-1 fades the brush edge inward as a share of its radius (0 is a hard edge);
- match_tone: the patch keeps the source's texture but takes the brightness and color of the surroundings of the place it lands, read
  only from outside the brush so the defect never tints its own patch.

Strokes are applied in order on the linear scan, so a later stroke can copy from an earlier one."""

from typing import Iterable, Tuple

import cv2
import numpy as np

from .logic import HEAL_SIZE_REF, smooth_polyline

_MATCH_GAIN_MIN = 1.0 / 64.0  # tone match: six stops either way
_MATCH_GAIN_MAX = 64.0
_EPS = 1e-6


def _cover(points, radius: float, x0: int, y0: int, shape: Tuple[int, int], w: int, h: int) -> np.ndarray:
    chain = [(float(p[0]) * w, float(p[1]) * h) for p in points]
    if len(chain) >= 3:
        chain = smooth_polyline(chain, closed=False)
    local = np.round(np.array(chain, dtype=np.float32) - (x0, y0)).astype(np.int32)
    cover = np.zeros(shape, dtype=np.uint8)
    r = max(1, int(round(radius)))
    if len(local) > 1:
        cv2.polylines(cover, [local], False, 1, thickness=2 * r)
    for cx, cy in local:
        cv2.circle(cover, (int(cx), int(cy)), r, 1, -1)
    return cover


def _local_mean(plane: np.ndarray, weight: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian mean of plane over only the pixels weight admits (a normalized convolution)."""
    num = cv2.GaussianBlur(plane * weight[..., None], (0, 0), sigma)
    den = cv2.GaussianBlur(weight, (0, 0), sigma)[..., None]
    return num / np.maximum(den, _EPS)


def apply_clone_stroke(out: np.ndarray, stroke) -> None:
    """Paint one stroke into out (float32 HxWx3, linear), in place."""
    points, size, dx, dy, strength, feather, match_tone = stroke
    if not points or strength <= 0.0:
        return
    h, w = out.shape[:2]
    radius = max(1.0, float(size) * max(w, h) / HEAL_SIZE_REF * 0.5)
    sx, sy = int(round(float(dx) * w)), int(round(float(dy) * h))
    if sx == 0 and sy == 0:
        return
    sigma = max(2.0, radius)
    pad = int(radius + 3.0 * sigma) + 2
    xs = [float(p[0]) * w for p in points]
    ys = [float(p[1]) * h for p in points]
    x0, y0 = max(0, int(min(xs)) - pad), max(0, int(min(ys)) - pad)
    x1, y1 = min(w, int(max(xs)) + pad + 1), min(h, int(max(ys)) + pad + 1)
    if x1 <= x0 or y1 <= y0:
        return

    cover = _cover(points, radius, x0, y0, (y1 - y0, x1 - x0), w, h)
    if not cover.any():
        return
    yy = np.arange(y0, y1) + sy
    xx = np.arange(x0, x1) + sx
    valid = ((yy >= 0) & (yy < h))[:, None] & ((xx >= 0) & (xx < w))[None, :]  # source off the frame clamps to the edge and counts for nothing
    src = out[np.clip(yy, 0, h - 1)[:, None], np.clip(xx, 0, w - 1)[None, :]].astype(np.float32)
    dst = out[y0:y1, x0:x1].astype(np.float32)

    if feather > 0.0:
        depth = cv2.distanceTransform(cover, cv2.DIST_L2, 3)  # distance in from the brush edge
        alpha = np.clip(depth / max(float(feather) * min(radius, float(depth.max())), _EPS), 0.0, 1.0)
    else:
        alpha = cover.astype(np.float32)
    alpha *= float(strength) * valid

    patch = src
    if match_tone:
        ring = ((cover == 0) & valid).astype(np.float32)  # the surroundings of both places, never the brush itself
        if ring.any():
            gain = _local_mean(dst, ring, sigma) / np.maximum(_local_mean(src, ring, sigma), _EPS)
            patch = src * np.clip(gain, _MATCH_GAIN_MIN, _MATCH_GAIN_MAX)

    a = alpha[..., None]
    out[y0:y1, x0:x1] = dst * (1.0 - a) + patch * a


def apply_clone_strokes(img: np.ndarray, strokes: Iterable) -> np.ndarray:
    """A new buffer with every stroke applied in order (the input is not touched)."""
    out = np.array(img, dtype=np.float32, copy=True)
    for stroke in strokes:
        apply_clone_stroke(out, stroke)
    return out
