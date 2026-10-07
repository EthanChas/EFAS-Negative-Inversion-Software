"""Flat-field (illumination falloff) correction - numpy + OpenCV, no Qt/UI imports."""

import numpy as np

_GAMMA = 2.2
_GAIN_MIN = 0.25
_GAIN_MAX = 4.0
_GAIN_WORK_SIZE = 256
POOL_MIN_FRAMES = 5
_POOL_PERCENTILE = 90.0

_cv2 = None


def _cv():
    global _cv2
    if _cv2 is None:
        import cv2

        _cv2 = cv2
    return _cv2


def _to_linear(pixels: np.ndarray) -> np.ndarray:
    return np.power(pixels.astype(np.float32) * np.float32(1.0 / 255.0), np.float32(_GAMMA))


def _shrink(frame: np.ndarray) -> np.ndarray:
    cv2 = _cv()
    h, w = frame.shape[:2]
    scale = min(1.0, _GAIN_WORK_SIZE / max(h, w))
    if scale < 1.0:
        frame = cv2.resize(frame, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
    return frame


def compute_gain(reference_rgb: np.ndarray) -> np.ndarray:
    """Per-channel gain = mean(blur) / blur, from a uint8 reference, on a downsampled copy."""
    return _gain_from_linear(_shrink(_to_linear(reference_rgb)))


def _gain_from_linear(ref: np.ndarray) -> np.ndarray:
    cv2 = _cv()
    sigma = max(ref.shape[:2]) / 16.0
    blur = np.clip(cv2.GaussianBlur(ref, (0, 0), sigmaX=sigma, sigmaY=sigma), 1e-4, None)
    means = blur.reshape(-1, blur.shape[2]).mean(axis=0)
    gain = means[None, None, :] / blur
    return np.clip(gain, _GAIN_MIN, _GAIN_MAX).astype(np.float32)


def pool_gain_from_frames(frames: list[np.ndarray], percentile: float = _POOL_PERCENTILE) -> np.ndarray:
    """Roll-wide stand-in for a dedicated blank-light reference: a per-pixel,
    per-channel high percentile across many frames. Picture content varies
    frame to frame and pulls a given pixel down from clear film's own reading
    there; the light's falloff does not - so a high percentile across enough
    frames converges on the light itself. Frames are uint8 RGB of any size."""
    small = [_shrink(_to_linear(f)) for f in frames]
    h = min(s.shape[0] for s in small)
    w = min(s.shape[1] for s in small)
    stack = np.stack([s[:h, :w] for s in small], axis=0)
    pooled = np.percentile(stack, percentile, axis=0).astype(np.float32)
    return _gain_from_linear(pooled)


def gain_token(gain: np.ndarray) -> str:
    """A short content id for a gain map, for render-cache keys."""
    import hashlib

    return hashlib.blake2b(np.ascontiguousarray(gain, dtype=np.float32).tobytes(), digest_size=8).hexdigest()


def apply_flatfield(pixels: np.ndarray, gain: np.ndarray) -> np.ndarray:
    """Multiply the scan (uint8 sRGB) by the gain map in linear light and return uint8 again."""
    cv2 = _cv()
    h, w = pixels.shape[:2]
    if gain.shape[:2] != (h, w):
        gain = cv2.resize(gain, (w, h), interpolation=cv2.INTER_LINEAR)
    lin = _to_linear(pixels)
    lin *= gain
    np.clip(lin, 0.0, 1.0, out=lin)
    out = np.power(lin, np.float32(1.0 / _GAMMA))
    out *= np.float32(255.0)
    return (out + np.float32(0.5)).astype(np.uint8)
