"""Halation: a soft, reddish glow round the brightest parts of the picture - numpy and OpenCV only, no Qt.

Real film has halation: light that passes through the emulsion bounces off the film's back and exposes it a second time, round bright highlights, as a red-orange glow. **A scan of a
negative already contains the film's own halation**, so this module does not recover anything: it makes a *simulated* extra glow, for a stronger look or for a scan whose capture
lost some of it. It is off at Amount 0, and nothing in EFAS turns it on for you.

    Amount     how strong the glow is (0 = off)
    Radius     how far it spreads, as a share of the picture's shorter side
    Threshold  how bright a part must be (display luminance) to glow; lower lets more of the picture glow
    Warmth     0 = a neutral glow, 1 = the red-orange of film's halation

It works on the finished, cropped picture (8-bit), by screening a blurred, tinted copy of the highlights over it, so it can only brighten, never darken."""
import numpy as np

KEYS = ("hal_amount", "hal_radius", "hal_threshold", "hal_warmth")
DEFAULTS = {"hal_amount": 0.0, "hal_radius": 0.4, "hal_threshold": 0.7, "hal_warmth": 0.8}
THRESHOLD_RANGE = (0.3, 0.98)
RADIUS_MIN_SHARE = 0.003     # the glow's blur (sigma) as a share of the shorter side at Radius 0 ...
RADIUS_SPAN_SHARE = 0.05     # ... and what Radius adds up to at 1
WARM_TINT = (1.0, 0.30, 0.08)   # the colour of film's halation, relative to red
GAIN = 1.0
_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
_WORK_SIGMA = 6.0            # the blur is made on a copy shrunk until its sigma is about this many pixels (it is smooth, so nothing is lost)


def is_neutral(values: dict | None) -> bool:
    return abs(float((values or {}).get("hal_amount", 0.0))) < 1e-9


def _smoothstep(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def glow_sigma(shape, radius: float) -> float:
    """The blur's sigma in pixels for a picture of this (height, width) at this Radius."""
    return max(1.0, min(shape[:2]) * (RADIUS_MIN_SHARE + RADIUS_SPAN_SHARE * float(np.clip(radius, 0.0, 1.0))))


def glow(pixels: np.ndarray, values: dict) -> np.ndarray:
    """The glow alone, float32 HxWx3 in 0..1 (before Amount): the picture's highlights, blurred and tinted."""
    import cv2

    img = pixels.astype(np.float32) / 255.0
    h, w = img.shape[:2]
    threshold = float(np.clip(values.get("hal_threshold", DEFAULTS["hal_threshold"]), *THRESHOLD_RANGE))
    luma = img @ _LUMA
    weight = _smoothstep((luma - threshold) / max(1.0 - threshold, 1e-3))
    sigma = glow_sigma((h, w), float(values.get("hal_radius", DEFAULTS["hal_radius"])))
    k = min(1.0, _WORK_SIGMA / sigma)
    src = img * weight[..., None]
    small = cv2.resize(src, (max(2, round(w * k)), max(2, round(h * k))), interpolation=cv2.INTER_AREA) if k < 1.0 else src
    blurred = cv2.GaussianBlur(small, (0, 0), sigma * k)
    full = cv2.resize(blurred, (w, h), interpolation=cv2.INTER_LINEAR) if k < 1.0 else blurred
    warm = float(np.clip(values.get("hal_warmth", DEFAULTS["hal_warmth"]), 0.0, 1.0))
    tint = (1.0 - warm) + warm * np.array(WARM_TINT, dtype=np.float32)   # neutral (1, 1, 1) to the red-orange
    return (full @ _LUMA)[..., None] * tint[None, None, :]


def apply_halation(pixels: np.ndarray, values: dict | None) -> np.ndarray:
    """The 8-bit RGB picture with the glow screened over it; Amount 0 returns it untouched."""
    v = values or {}
    if is_neutral(v) or pixels.ndim != 3 or pixels.shape[2] != 3:
        return pixels
    amount = float(np.clip(v.get("hal_amount", 0.0), 0.0, 1.0)) * GAIN
    img = pixels.astype(np.float32) / 255.0
    screened = 1.0 - (1.0 - img) * (1.0 - np.clip(amount * glow(pixels, v), 0.0, 1.0))
    return np.clip(screened * 255.0 + 0.5, 0, 255).astype(np.uint8)
