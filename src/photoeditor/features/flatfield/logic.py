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
    top = 65535.0 if pixels.dtype == np.uint16 else 255.0
    return np.power(pixels.astype(np.float32) * np.float32(1.0 / top), np.float32(_GAMMA))


def _shrink(frame: np.ndarray) -> np.ndarray:
    cv2 = _cv()
    h, w = frame.shape[:2]
    scale = min(1.0, _GAIN_WORK_SIZE / max(h, w))
    if scale < 1.0:
        frame = cv2.resize(frame, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
    return frame


METHODS = {"efas": "EFAS (original)", "negpy": "NegPy", "improved": "Improved"}
METHOD_DEFAULT = "improved"
METHOD_NOTES = {
    "efas": "EFAS's first method: a 5x5 median filter against dust on the light, then a blur of 1/16 of the long side. It smooths the steep falloff at the borders away, so the edges stay about 13% dark.",
    "negpy": "NegPy's method: the same blur of 1/16 of the long side, with no dust filter. It leaves the edges as dark as EFAS's original does.",
    "improved": "A 5x5 median filter against dust, then a blur of 1/64 of the long side with the edge pixels repeated outward rather than mirrored, so the falloff at the borders is kept. The edges come out within 1-3% of the middle.",
}
_SMOOTH_DIV = 16.0     # EFAS and NegPy blur with a sigma of the long side / 16
_IMPROVED_DIV = 64.0   # Improved with the long side / 64


def reference_map(reference_rgb: np.ndarray) -> np.ndarray:
    """The reference (a scan of the bare light) as the small linear map every method starts from. It is kept with the flat field, so the method can be changed later."""
    return _shrink(_to_linear(reference_rgb))


def gain_from_map(ref: np.ndarray, method: str = "efas") -> np.ndarray:
    """The per-channel gain (mean of the blurred map / the blurred map) from a small linear reference map, by one of METHODS."""
    cv2 = _cv()
    method = method if method in METHODS else "efas"
    ref = np.ascontiguousarray(ref, dtype=np.float32)
    if method != "negpy" and min(ref.shape[:2]) >= 8:
        ref = cv2.medianBlur(ref, 5)  # specks of dust on the light source or the lens must not become dark spots in the gain map
    sigma = max(ref.shape[:2]) / (_IMPROVED_DIV if method == "improved" else _SMOOTH_DIV)
    border = cv2.BORDER_REPLICATE if method == "improved" else cv2.BORDER_REFLECT_101
    blur = np.clip(cv2.GaussianBlur(ref, (0, 0), sigmaX=sigma, sigmaY=sigma, borderType=border), 1e-4, None)
    means = blur.reshape(-1, blur.shape[2]).mean(axis=0)
    gain = means[None, None, :] / blur
    return np.clip(gain, _GAIN_MIN, _GAIN_MAX).astype(np.float32)


def compute_gain(reference_rgb: np.ndarray, method: str = "efas") -> np.ndarray:
    """Per-channel gain from a uint8 or uint16 reference, on a downsampled copy, by one of METHODS."""
    return gain_from_map(reference_map(reference_rgb), method)


def _gain_from_linear(ref: np.ndarray, method: str = "efas") -> np.ndarray:
    return gain_from_map(ref, method)


def pool_reference_from_frames(frames: list[np.ndarray], percentile: float = _POOL_PERCENTILE) -> np.ndarray:
    """Roll-wide stand-in for a dedicated blank-light reference: a per-pixel,
    per-channel high percentile across many frames. Picture content varies
    frame to frame and pulls a given pixel down from clear film's own reading
    there; the light's falloff does not - so a high percentile across enough
    frames converges on the light itself. Frames are uint8 RGB of any size.
    Returns the small linear reference map (see reference_map)."""
    small = [_shrink(_to_linear(f)) for f in frames]
    h = min(s.shape[0] for s in small)
    w = min(s.shape[1] for s in small)
    stack = np.stack([s[:h, :w] for s in small], axis=0)
    return np.percentile(stack, percentile, axis=0).astype(np.float32)


def pool_gain_from_frames(frames: list[np.ndarray], percentile: float = _POOL_PERCENTILE, method: str = "efas") -> np.ndarray:
    """The gain map of the pooled reference (see pool_reference_from_frames)."""
    return gain_from_map(pool_reference_from_frames(frames, percentile), method)


def gain_token(gain: np.ndarray) -> str:
    """A short content id for a gain map, for render-cache keys."""
    import hashlib

    return hashlib.blake2b(np.ascontiguousarray(gain, dtype=np.float32).tobytes(), digest_size=8).hexdigest()


def apply_flatfield(pixels: np.ndarray, gain: np.ndarray) -> np.ndarray:
    """Multiply the scan (uint8 or uint16 sRGB) by the gain map in linear light and return the same depth again - a 16-bit scan stays 16-bit, so a
    negative's narrow range is not squeezed into 256 levels before it is stretched."""
    cv2 = _cv()
    h, w = pixels.shape[:2]
    if gain.shape[:2] != (h, w):
        gain = cv2.resize(gain, (w, h), interpolation=cv2.INTER_LINEAR)
    lin = _to_linear(pixels)
    lin *= gain
    np.clip(lin, 0.0, 1.0, out=lin)
    out = np.power(lin, np.float32(1.0 / _GAMMA))
    if pixels.dtype == np.uint16:
        out *= np.float32(65535.0)
        return (out + np.float32(0.5)).astype(np.uint16)
    out *= np.float32(255.0)
    return (out + np.float32(0.5)).astype(np.uint8)
