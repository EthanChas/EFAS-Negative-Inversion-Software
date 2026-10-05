"""Chroma denoise - numpy + OpenCV, no Qt/UI imports.

Ported from NegPy's apply_chroma_denoise (negpy/features/lab/logic.py):
edge-aware smoothing of the a* and b* channels of CIELAB, which removes color
noise (the blotchy red/green/blue speckle of film grain scans and high ISO)
while leaving luminance - the actual detail - alone. The smoothing is a
bilateral filter weighted by chroma similarity as well as distance, so a
saturated object's color doesn't bleed into its surroundings. OpenCV is
imported lazily."""

import numpy as np

CHROMA_DENOISE_MAX = 5.0  # slider range, in pixels of smoothing at 1600 px
_CHROMA_SIGMA_R = 15.0  # a*/b* distance past which a neighbor is rejected
_MAX_WORKING_SIGMA = 2.0  # the bilateral is O(pixels x sigma^2): bigger radii are done on a shrunken copy

_cv2 = None


def _cv():
    global _cv2
    if _cv2 is None:
        import cv2

        _cv2 = cv2
    return _cv2


def apply_chroma_denoise(pixels: np.ndarray, radius: float, scale: float = 1.0) -> np.ndarray:
    """radius 0..CHROMA_DENOISE_MAX (0 is a no-op); scale is the image's size
    over the 1600 px preview, so the smoothing covers the same part of the
    picture at full resolution as it does in the preview. uint8 RGB in and out."""
    if radius <= 0:
        return pixels
    cv2 = _cv()
    rgb = pixels.astype(np.float32)
    rgb *= np.float32(1.0 / 255.0)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    l_chan, a, b = cv2.split(lab)

    sigma = max(0.5, radius * scale)
    ab = cv2.merge([a, b, np.zeros_like(a)])  # bilateralFilter takes 1 or 3 channels; the zero plane adds nothing
    h, w = ab.shape[:2]
    shrink = min(1.0, _MAX_WORKING_SIGMA / sigma)
    if shrink < 1.0:
        # Color noise is low-frequency, so filtering a smaller copy (sigma scaled to match)
        # and enlarging the result is visually the same and far cheaper.
        small = cv2.resize(ab, (max(1, round(w * shrink)), max(1, round(h * shrink))), interpolation=cv2.INTER_AREA)
        small = cv2.bilateralFilter(small, 0, np.float32(_CHROMA_SIGMA_R), np.float32(sigma * shrink), borderType=cv2.BORDER_REFLECT_101)
        smoothed = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    else:
        smoothed = cv2.bilateralFilter(ab, 0, np.float32(_CHROMA_SIGMA_R), np.float32(sigma), borderType=cv2.BORDER_REFLECT_101)

    out = cv2.cvtColor(cv2.merge([l_chan, smoothed[:, :, 0], smoothed[:, :, 1]]), cv2.COLOR_LAB2RGB)
    out *= np.float32(255.0)
    np.clip(out, 0, 255, out=out)
    return (out + np.float32(0.5)).astype(np.uint8)
