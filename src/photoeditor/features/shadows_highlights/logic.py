"""Pure shadows/highlights tonal adjustment - numpy only, no Qt/UI imports."""

import numpy as np

from ..lut.strips import run_strips

_LUMA_WEIGHTS = (0.299, 0.587, 0.114)
_LUMA_VEC = np.array(_LUMA_WEIGHTS, dtype=np.float32)
_STRENGTH = 120.0
_EPS = 1e-6


def adjust_shadows_highlights(pixels: np.ndarray, shadows: float, highlights: float) -> np.ndarray:
    """shadows, highlights in [-1, 1]: positive brightens that tonal range,
    negative darkens it - a consistent +/- direction for both, rather than
    Lightroom's inverted-feeling "negative highlights to recover them."
    Each pixel's own luminance builds two masks (shadow weight peaking at
    black and fading to 0 by the midpoint, highlight weight the mirror of
    that), so the adjustment concentrates on the dark or bright end of the
    tonal range and leaves midtones close to untouched."""
    if shadows == 0.0 and highlights == 0.0:
        return pixels
    x = np.arange(256, dtype=np.float32) / 255.0
    shadow_weight = np.clip(1.0 - x * 2.0, 0.0, 1.0)
    highlight_weight = np.clip(x * 2.0 - 1.0, 0.0, 1.0)
    table = np.round((shadows * shadow_weight + highlights * highlight_weight) * _STRENGTH).astype(np.int16)
    return run_strips(lambda strip: _apply_table(strip, table), pixels)


def _apply_table(pixels: np.ndarray, table: np.ndarray) -> np.ndarray:
    h, w, _ = pixels.shape
    luma = (pixels.reshape(-1, 3).astype(np.float32) @ _LUMA_VEC).reshape(h, w).astype(np.uint8)
    out = pixels.astype(np.int16)
    out += table[luma][:, :, None]
    np.clip(out, 0, 255, out=out)
    return out.astype(np.uint8)
