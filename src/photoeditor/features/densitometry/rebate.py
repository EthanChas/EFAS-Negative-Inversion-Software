"""Finding the film's clear border (the rebate) in a scan, so the film base can be sampled without clicking: a suggestion for the user to confirm.

The film base is the thinnest, most uniform part of the negative, usually a strip along an edge. The bare backlight beyond the film edge is also uniform and
bright, so the finder looks along each edge for two levels: a lighter outer strip (bare light) with a slightly darker uniform strip inside it (the base).
Numpy and OpenCV only, no Qt/UI imports.
"""

from dataclasses import dataclass

import numpy as np

MAX_DIM = 400
EDGE_BAND = 0.16
RUN_TOLERANCE = 0.02
MIN_STEP = 0.05
UNIFORM = 0.02
GOOD_UNIFORM = 0.012
MIN_RATIO = 0.8
MAX_RATIO = 8.0
CLIP = 0.999
SIDES = ("left", "right", "top", "bottom")
SPREAD_NORMAL = 2.563


@dataclass(frozen=True)
class Rebate:
    rect: tuple[int, int, int, int]
    v: tuple[float, float, float]
    spread: float
    side: str
    confidence: str
    reasons: tuple[str, ...]
    ratio: float


def _density(v: np.ndarray, floor) -> np.ndarray:
    return -np.log10(np.maximum(v, np.maximum(np.asarray(floor, dtype=np.float64), 1e-9)))


def _shrink(v: np.ndarray, max_dim: int) -> tuple[np.ndarray, float]:
    import cv2

    h, w = v.shape[:2]
    scale = min(1.0, max_dim / max(h, w))
    if scale >= 1.0:
        return v.astype(np.float64), 1.0
    small = cv2.resize(np.ascontiguousarray(v, dtype=np.float32), (max(8, round(w * scale)), max(8, round(h * scale))), interpolation=cv2.INTER_AREA)
    return small.astype(np.float64), scale


def runs(profile: np.ndarray, tolerance: float = RUN_TOLERANCE, min_len: int = 4) -> list[tuple[int, int, float]]:
    """Plateaus of a 1D profile: (start, end exclusive, median) for each stretch that stays within `tolerance` of its own median and lasts `min_len` points."""
    out = []
    n = profile.size
    i = 0
    while i < n:
        j = i + 1
        while j < n and abs(profile[j] - np.median(profile[i:j + 1])) <= tolerance:
            j += 1
        if j - i >= min_len:
            out.append((i, j, float(np.median(profile[i:j]))))
        i = j if j > i + 1 else i + 1
    return out


def _side_profile(g: np.ndarray, side: str, depth: int, margin: float = 0.2) -> tuple[np.ndarray, slice]:
    """Median density along the line running from the image edge inward, over the middle of the side (corners and sprocket zones left out)."""
    h, w = g.shape
    if side in ("left", "right"):
        rows = slice(int(h * margin), int(h * (1 - margin)))
        band = g[rows, :depth] if side == "left" else g[rows, w - depth:][:, ::-1]
        return np.median(band, axis=0), rows
    cols = slice(int(w * margin), int(w * (1 - margin)))
    band = g[:depth, cols].T if side == "top" else g[h - depth:, cols][::-1].T
    return np.median(band, axis=0), cols


def _window_spread(patch_d: np.ndarray) -> float:
    return float(((np.percentile(patch_d, 90, axis=(0, 1)) - np.percentile(patch_d, 10, axis=(0, 1))) / SPREAD_NORMAL).max())


def find_rebate(v: np.ndarray, floor=(0.0, 0.0, 0.0), edge: float = EDGE_BAND, max_dim: int = MAX_DIM) -> Rebate | None:
    """The best candidate for the film's clear border in the linear scan `v` (HxWx3), or None. The rectangle is in the coordinates of `v`."""
    v = np.asarray(v)
    if v.ndim != 3 or v.shape[2] != 3 or min(v.shape[:2]) < 16:
        return None
    small, scale = _shrink(v, max_dim)
    h, w = small.shape[:2]
    d = _density(small, floor)
    g = d.mean(axis=2)
    ref = np.percentile(small[int(h * 0.25):int(h * 0.75), int(w * 0.25):int(w * 0.75)].reshape(-1, 3), 99, axis=0)
    best = None
    for side in SIDES:
        depth = max(8, int((w if side in ("left", "right") else h) * edge))
        profile, span = _side_profile(g, side, depth)
        found = runs(profile, min_len=max(3, depth // 10))
        if not found:
            continue
        outer = found[0] if found[0][0] <= 1 else None
        options = []
        if outer is not None and len(found) > 1:
            nxt = found[1]
            if nxt[0] - outer[1] <= max(3, depth // 8) and nxt[2] - outer[2] >= MIN_STEP and nxt[1] - nxt[0] >= max(4, depth // 6):
                options.append((nxt, True, nxt[2] - outer[2]))
        options.append((outer or found[0], False, 0.0))
        for strip, two_level, step in options:
            result = _evaluate(small, d, ref, side, span, strip, two_level, step, depth, scale)
            if result is not None:
                score = ({"high": 3, "medium": 2, "low": 1}[result.confidence], -result.spread)
                if best is None or score > best[0]:
                    best = (score, result)
                break
    return None if best is None else best[1]


def _evaluate(small, d, ref, side, span, strip, two_level, step, depth, scale) -> Rebate | None:
    """The cleanest window along one strip, accepted only if it is uniform, not clipped and plausibly film base; with how sure that makes us."""
    h, w = small.shape[:2]
    reaches_limit = strip[1] >= depth - 1
    a, b = strip[0] + max(1, (strip[1] - strip[0]) // 6), strip[1] - max(1, (strip[1] - strip[0]) // 6)
    if b - a < 2:
        return None
    along = np.arange(span.start, span.stop)
    win = max(6, int(0.05 * min(h, w)))
    cand = None
    for s0 in range(0, max(1, along.size - win), max(1, win // 2)):
        lo, hi = along[s0], along[min(s0 + win, along.size) - 1] + 1
        if side == "left":
            y1, y2, x1, x2 = lo, hi, a, b
        elif side == "right":
            y1, y2, x1, x2 = lo, hi, w - b, w - a
        elif side == "top":
            y1, y2, x1, x2 = a, b, lo, hi
        else:
            y1, y2, x1, x2 = h - b, h - a, lo, hi
        patch = small[y1:y2, x1:x2]
        if patch.size == 0:
            continue
        spread = _window_spread(d[y1:y2, x1:x2])
        med = np.median(patch.reshape(-1, 3), axis=0)
        if cand is None or spread < cand[0]:
            cand = (spread, med, (x1, y1, x2, y2))
    if cand is None:
        return None
    spread, med, rect = cand
    if spread > UNIFORM or np.any(med >= CLIP):
        return None
    ratio = float(np.min(med / np.maximum(ref, 1e-9)))
    ratio_hi = float(np.max(med / np.maximum(ref, 1e-9)))
    if ratio < MIN_RATIO or ratio_hi > MAX_RATIO:
        return None
    reasons = []
    if two_level:
        reasons.append(f"A uniform strip sits inside a lighter outer strip (a step of {step:.2f} density), which is how a film border looks next to the bare backlight.")
        conf = "high" if spread <= GOOD_UNIFORM and step >= 0.08 else "medium"
    else:
        reasons.append("A uniform strip runs along this edge, but no lighter bare-backlight strip lies outside it, so it could be the film border or the backlight itself.")
        conf = "medium" if spread <= GOOD_UNIFORM and not reaches_limit else "low"
    if reaches_limit and not two_level:
        reasons.append("The strip reaches the edge of the area searched, so it may be wider than a film border.")
    return Rebate(tuple(int(round(c / scale)) for c in rect), tuple(float(x) for x in med), float(spread), side, conf, tuple(reasons), ratio)
