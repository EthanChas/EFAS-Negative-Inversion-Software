"""Pure saturation / temperature-tint adjustments - numpy only, no Qt/UI imports."""

import numpy as np

from ..lut.strips import run_strips

_LUMA_WEIGHTS = (0.299, 0.587, 0.114)
_LUMA_VEC = np.array(_LUMA_WEIGHTS, dtype=np.float32)
_TEMP_TINT_STRENGTH = 50.0


def adjust_saturation(pixels: np.ndarray, amount: float) -> np.ndarray:
    """amount in [-1, 1]: -1 fully desaturates (grayscale), 0 is unchanged,
    +1 doubles each pixel's color distance from its own perceived-brightness
    gray point."""
    if amount == 0.0:
        return pixels
    return run_strips(lambda strip: _saturate(strip, amount), pixels)


def _saturate(pixels: np.ndarray, amount: float) -> np.ndarray:
    h, w, _ = pixels.shape
    out = pixels.astype(np.float32)
    gray = (out.reshape(-1, 3) @ _LUMA_VEC).reshape(h, w, 1)
    out -= gray
    out *= 1.0 + amount
    out += gray
    np.clip(out, 0, 255, out=out)
    return out.astype(np.uint8)


def adjust_temperature_tint(pixels: np.ndarray, temperature: float, tint: float) -> np.ndarray:
    """temperature, tint in [-1, 1] - a simple per-channel offset model, not
    a physically-based Kelvin one: positive temperature warms the image
    (more red, less blue); positive tint shifts toward magenta (more red
    and blue, less green)."""
    if temperature == 0.0 and tint == 0.0:
        return pixels
    out = pixels.astype(np.float32)
    out[:, :, 0] += temperature * _TEMP_TINT_STRENGTH + tint * _TEMP_TINT_STRENGTH * 0.5
    out[:, :, 1] -= tint * _TEMP_TINT_STRENGTH
    out[:, :, 2] += -temperature * _TEMP_TINT_STRENGTH + tint * _TEMP_TINT_STRENGTH * 0.5
    if pixels.dtype == np.float32:
        return np.clip(out, 0, 255)
    return np.clip(out, 0, 255).astype(np.uint8)
