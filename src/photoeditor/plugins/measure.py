"""Figures about the picture on screen for plugins (efas.statistics, efas.sample_pixel, efas.image). Pure numpy: no Qt."""
import numpy as np

_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
SHADOWS_BELOW = 64
HIGHLIGHTS_FROM = 192
BLOCKED_AT = 3
BLOWN_AT = 252
_SAMPLE_PIXELS = 400_000  # a bigger picture is read on a grid of about this many pixels (the figures barely move)


def statistics(rgb: np.ndarray | None) -> dict | None:
    """mean/median/p1/p99 of the brightness (0-255), the share (0-100) in the shadows, midtones and highlights, the share blocked (<= 3) and blown (>= 252),
    the average colour saturation (0-1) and the average r, g, b. None for no picture."""
    if rgb is None or rgb.ndim != 3 or rgb.shape[2] < 3 or rgb.size == 0:
        return None
    step = max(1, int(np.sqrt(rgb.shape[0] * rgb.shape[1] / _SAMPLE_PIXELS)))
    pixels = rgb[::step, ::step, :3].astype(np.float32)
    luma = pixels @ _LUMA
    total = float(luma.size)
    peak, floor = pixels.max(axis=2), pixels.min(axis=2)
    saturation = np.where(peak > 0, (peak - floor) / np.maximum(peak, 1e-6), 0.0)
    p1, median, p99 = np.percentile(luma, (1, 50, 99))
    shadows = float((luma < SHADOWS_BELOW).sum()) / total * 100
    highlights = float((luma >= HIGHLIGHTS_FROM).sum()) / total * 100
    return {
        "mean": round(float(luma.mean()), 2), "median": round(float(median), 2), "p1": round(float(p1), 2), "p99": round(float(p99), 2),
        "shadows_pct": round(shadows, 2), "midtones_pct": round(100 - shadows - highlights, 2), "highlights_pct": round(highlights, 2),
        "blocked_pct": round(float((luma <= BLOCKED_AT).sum()) / total * 100, 2), "blown_pct": round(float((luma >= BLOWN_AT).sum()) / total * 100, 2),
        "saturation": round(float(saturation.mean()), 4),
        "r": round(float(pixels[:, :, 0].mean()), 2), "g": round(float(pixels[:, :, 1].mean()), 2), "b": round(float(pixels[:, :, 2].mean()), 2),
    }


def sample(rgb: np.ndarray | None, x: int, y: int) -> dict | None:
    if rgb is None or not (0 <= y < rgb.shape[0] and 0 <= x < rgb.shape[1]):
        return None
    r, g, b = (int(v) for v in rgb[y, x, :3])
    return {"r": r, "g": g, "b": b}


def scaled(rgb: np.ndarray | None, max_dim: int) -> np.ndarray | None:
    """A copy of the picture (uint8, height x width x 3) whose long side is at most max_dim (nearest-neighbour; for a plugin's own analysis)."""
    if rgb is None:
        return None
    height, width = rgb.shape[:2]
    factor = max(height, width) / max_dim
    if factor <= 1:
        return np.array(rgb[:, :, :3], dtype=np.uint8, copy=True)  # always a copy: a plugin must not be able to change the picture
    rows = np.minimum((np.arange(int(height / factor)) * factor).astype(int), height - 1)
    cols = np.minimum((np.arange(int(width / factor)) * factor).astype(int), width - 1)
    return np.ascontiguousarray(rgb[rows][:, cols][:, :, :3], dtype=np.uint8)
