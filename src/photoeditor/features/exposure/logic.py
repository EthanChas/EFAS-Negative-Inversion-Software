"""Pure exposure adjustment - numpy only, no Qt/UI imports."""

import numpy as np

EV_RANGE = 2.0


def apply_exposure(pixels: np.ndarray, ev: float) -> np.ndarray:
    """Scale pixel brightness by 2**ev (each EV stop doubles or halves it)
    and clip back to a valid 0-255 uint8 image. Operates directly on the
    already gamma-encoded pixels rather than in scene-linear light - a
    simplification, not a scene-referred exposure model."""
    if ev == 0.0:
        return pixels
    adjusted = pixels.astype(np.float32) * (2.0**ev)
    if pixels.dtype == np.float32:
        return np.clip(adjusted, 0, 255)
    return np.clip(adjusted, 0, 255).astype(np.uint8)
