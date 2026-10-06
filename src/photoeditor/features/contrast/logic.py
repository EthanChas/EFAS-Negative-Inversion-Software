"""Pure contrast adjustment - numpy only, no Qt/UI imports."""

import numpy as np


def apply_contrast(pixels: np.ndarray, amount: float) -> np.ndarray:
    """amount in [-1, 1]: positive adds contrast with a smooth S-curve
    (darks get darker, lights lighter, the midpoint stays put, and the ends
    roll off instead of clipping hard); negative flattens toward the middle
    by running the same curve backwards; 0 is unchanged. Pointwise per
    channel, so it folds into the same lookup table as exposure and the
    tone curve."""
    if amount == 0.0:
        return pixels
    x = pixels.astype(np.float32) * np.float32(1.0 / 255.0)
    s = x * x * (np.float32(3.0) - np.float32(2.0) * x)  # smoothstep: an S-curve through (0,0), (.5,.5), (1,1)
    out = x + np.float32(amount) * (s - x)
    out *= np.float32(255.0)
    if pixels.dtype == np.float32:  # a wide ramp: keep every fraction
        return np.clip(out, 0, 255)
    return np.clip(out + np.float32(0.5), 0, 255).astype(np.uint8)
