"""Local contrast - CLAHE (contrast-limited adaptive histogram equalization) on lightness only."""

import cv2
import numpy as np

GRID = 8
BINS = 256
CLIP_SCALE = 2.5
_CHUNK_ROWS = 256


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


def _apply_wide(pixels: np.ndarray, strength: float) -> np.ndarray:
    """The same on a 16-bit picture. The lightness is kept as a float on the 8-bit path's 0-255 scale; each tile's curve is read between the two bins either side of it, so the
    result is smooth instead of 256 steps; and the picture is converted back once, at 16 bits."""
    rgb = pixels.astype(np.float32) * np.float32(1.0 / 65535.0)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    pos = np.clip(lab[..., 0] * np.float32(2.55), 0.0, 255.0)
    bins = np.rint(pos).astype(np.int32)
    h, w = bins.shape
    cdfs = _tile_cdfs(bins, strength * CLIP_SCALE).reshape(-1)
    y0, y1, fy = _axis(h)
    x0, x1, fx = _axis(w)
    below = np.minimum(pos.astype(np.int32), BINS - 2)
    above = pos - below
    out = np.empty((h, w), dtype=np.float32)
    for r0 in range(0, h, _CHUNK_ROWS):
        r1 = min(h, r0 + _CHUNK_ROWS)
        lo, share, here = below[r0:r1], above[r0:r1], pos[r0:r1]

        def curve(ty, tx):   # a tile's curve at each pixel's lightness
            base = (ty * GRID + tx) * BINS + lo
            return cdfs[base] + (cdfs[base + 1] - cdfs[base]) * share

        v00, v10 = curve(y0[r0:r1, None], x0[None, :]), curve(y0[r0:r1, None], x1[None, :])
        v01, v11 = curve(y1[r0:r1, None], x0[None, :]), curve(y1[r0:r1, None], x1[None, :])
        top = v00 + (v10 - v00) * fx[None, :]
        bottom = v01 + (v11 - v01) * fx[None, :]
        equalized = (top + (bottom - top) * fy[r0:r1, None]) * np.float32(255.0)
        out[r0:r1] = here + (equalized - here) * np.float32(strength)
    lab[..., 0] = np.clip(out, 0.0, 255.0) / np.float32(2.55)
    back = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    return np.clip(back * np.float32(65535.0) + np.float32(0.5), 0, 65535).astype(np.uint16)


def apply_local_contrast(pixels: np.ndarray, strength: float) -> np.ndarray:
    """pixels: uint8 RGB, or uint16 RGB (kept at 16 bits)."""
    if strength <= 0:
        return pixels
    if pixels.dtype == np.uint16:
        return _apply_wide(pixels, strength)
    lab = cv2.cvtColor(pixels, cv2.COLOR_RGB2LAB)
    lightness = lab[..., 0].astype(np.int32)
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
