"""Sharpening that runs on the finished picture at its final size, after any resize (the editor's own sharpening runs at the working size, which a resize then softens).

An unsharp mask whose radius follows the picture's size, with a small threshold so grain and noise are not amplified. Works on 8-bit and 16-bit pictures. numpy + OpenCV only."""

import numpy as np

MAX_AMOUNT = 100


def radius_for(long_edge: int) -> float:
    """About 0.6 pixel for a web-size picture, growing gently with size so a large print is sharpened at the scale it is looked at."""
    return float(max(0.6, min(2.5, long_edge / 2600.0)))


def sharpen_output(pixels: np.ndarray, amount: float) -> np.ndarray:
    """`amount` runs from 0 (nothing) to 100 (strong). The picture keeps its type and size."""
    amount = max(0.0, min(float(MAX_AMOUNT), float(amount)))
    if amount <= 0 or pixels.size == 0:
        return pixels
    import cv2

    top = 65535.0 if pixels.dtype == np.uint16 else 255.0
    f = np.ascontiguousarray(pixels, dtype=np.float32) / np.float32(top)
    sigma = radius_for(max(pixels.shape[:2]))
    blur = cv2.GaussianBlur(f, (0, 0), sigma)
    detail = f - blur
    gain = np.float32(amount / MAX_AMOUNT * 1.6)
    threshold = np.float32(0.004)
    mask = np.abs(detail) > threshold
    out = f + gain * np.where(mask, detail - np.sign(detail) * threshold * 0.5, 0.0).astype(np.float32)
    return np.clip(np.rint(out * np.float32(top)), 0, top).astype(pixels.dtype)
