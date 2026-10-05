"""Local contrast - CLAHE (contrast-limited adaptive histogram equalization) on lightness only. numpy + OpenCV, no Qt imports.

The method follows NegPy's: the frame is cut into a fixed 8 x 8 grid of tiles at any size, each tile gets a histogram of its lightness that is
clipped (the clip limit is strength x 2.5 x the tile's pixels / 256, the clipped excess shared out over all bins) and turned into a
cumulative curve, and every pixel is mapped through the bilinear blend of the four nearest tiles' curves (smoothstepped, so tile borders do
not show). The result is mixed back in by `strength`: L' = L + (equalized - L) x strength. Color is left alone."""

import cv2
import numpy as np

GRID = 8
BINS = 256
CLIP_SCALE = 2.5
_CHUNK_ROWS = 256  # rows blended at a time, so a 26 MP export does not need four full-frame float arrays at once


def _tile_cdfs(lightness: np.ndarray, clip_limit: float) -> np.ndarray:
    """The clipped cumulative curve of every tile, (GRID x GRID, BINS) float32 in 0-1."""
    h, w = lightness.shape
    tile_h, tile_w = (h + GRID - 1) // GRID, (w + GRID - 1) // GRID
    ty = (np.arange(h) // tile_h).astype(np.int32)
    tx = (np.arange(w) // tile_w).astype(np.int32)
    combined = (ty[:, None] * GRID + tx[None, :]) * BINS + lightness
    hist = np.bincount(combined.ravel(), minlength=GRID * GRID * BINS).reshape(GRID * GRID, BINS)
    total = hist.sum(axis=1)
    limit = np.maximum(1, (np.float32(clip_limit) * total.astype(np.float32) / np.float32(BINS)).astype(np.int64))
    clipped = np.minimum(hist, limit[:, None])
    excess = (hist - clipped).sum(axis=1)
    share, remainder = excess // BINS, excess % BINS
    counts = clipped + share[:, None] + (np.arange(BINS)[None, :] < remainder[:, None])
    return np.cumsum(counts, axis=1).astype(np.float32) / np.maximum(total, 1)[:, None].astype(np.float32)


def _axis(n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For each of n positions: the two tiles to blend between and the (smoothstepped) weight of the second."""
    pos = np.arange(n, dtype=np.float32) / np.float32(n) * np.float32(GRID) - np.float32(0.5)
    floor = np.floor(pos)
    frac = pos - floor
    weight = frac * frac * (np.float32(3.0) - np.float32(2.0) * frac)
    lo = np.maximum(floor.astype(np.int32), 0)
    hi = np.minimum(floor.astype(np.int32) + 1, GRID - 1)
    return lo, hi, weight


def apply_local_contrast(pixels: np.ndarray, strength: float) -> np.ndarray:
    """pixels: uint8 RGB. strength 0-1; 0 returns the picture untouched."""
    if strength <= 0:
        return pixels
    lab = cv2.cvtColor(pixels, cv2.COLOR_RGB2LAB)
    lightness = lab[..., 0].astype(np.int32)  # OpenCV scales L* to 0-255
    h, w = lightness.shape
    cdfs = _tile_cdfs(lightness, strength * CLIP_SCALE).reshape(-1)
    y0, y1, fy = _axis(h)
    x0, x1, fx = _axis(w)
    out = np.empty((h, w), dtype=np.uint8)
    for r0 in range(0, h, _CHUNK_ROWS):
        r1 = min(h, r0 + _CHUNK_ROWS)
        bins = lightness[r0:r1]
        v00 = cdfs[(y0[r0:r1, None] * GRID + x0[None, :]) * BINS + bins]
        v10 = cdfs[(y0[r0:r1, None] * GRID + x1[None, :]) * BINS + bins]
        v01 = cdfs[(y1[r0:r1, None] * GRID + x0[None, :]) * BINS + bins]
        v11 = cdfs[(y1[r0:r1, None] * GRID + x1[None, :]) * BINS + bins]
        top = v00 + (v10 - v00) * fx[None, :]
        bottom = v01 + (v11 - v01) * fx[None, :]
        equalized = (top + (bottom - top) * fy[r0:r1, None]) * np.float32(255.0)
        mixed = bins + (equalized - bins) * np.float32(strength)
        out[r0:r1] = np.clip(mixed + 0.5, 0, 255).astype(np.uint8)
    lab[..., 0] = out
    return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
