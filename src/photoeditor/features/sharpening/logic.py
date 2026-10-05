"""Pure sharpening - numpy + OpenCV only, no Qt/UI imports.

Ported from NegPy's four sharpening methods (negpy/features/lab/logic.py):
Unsharp Mask, Deconvolution (Richardson-Lucy), Surface Blur (bilateral) and
Wavelet (multi-scale). All but Deconvolution work on the L* channel of
CIELAB - OpenCV's sRGB<->Lab here, where NegPy has its own working-space
conversion - with the same soft noise gate, shadow-gain rolloff, optional
edge mask and local-range overshoot clamp as the original, so the constants
carry over unchanged. OpenCV is imported lazily on first use."""

import math
from enum import Enum

import numpy as np

from ..lut.strips import run_strips


class SharpenMethod(Enum):
    USM = "usm"
    DECONVOLUTION = "rl"
    SURFACE_BLUR = "surface_blur"
    WAVELET = "wavelet"


METHOD_LABELS = {
    SharpenMethod.USM: "Unsharp Mask",
    SharpenMethod.DECONVOLUTION: "Deconvolution",
    SharpenMethod.SURFACE_BLUR: "Surface Blur",
    SharpenMethod.WAVELET: "Wavelet",
}

DEFAULT_METHOD = SharpenMethod.USM.value

SHARPEN_GATE_LO = 0.25
SHARPEN_GATE_HI = 0.33
SHARPEN_OVERSHOOT_LIGHT = 1.0
SHARPEN_OVERSHOOT_DARK = 2.0
SHARPEN_MASK_T_HI = 10.0
SHARPEN_SHADOW_FLOOR = 1.0 / 3.0
SHARPEN_SHADOW_L_HI = 35.0
SURFACE_BLUR_COLOR_SIGMA = 8.0
WAVELET_SIGMA_RATIOS = (2.0, 8.0, 32.0)
_WAVELET_MEDIUM_WEIGHT = 1.0
_WAVELET_LARGE_WEIGHT = 0.6
_GAUSSIAN_MAX_KERNEL_R = 32
_BILATERAL_MAX_DIM = 1600  # same cap NegPy uses (its PREVIEW_SIZE_DEFAULT)
_BILATERAL_MAX_SIGMA = 4.0  # working sigma_space ceiling after downscaling
RL_EPS = 1e-6
_SRGB_GAMMA = 2.2  # decode/encode approximation for the Deconvolution ratio

_cv2 = None


def _cv():
    global _cv2
    if _cv2 is None:
        import cv2

        _cv2 = cv2
    return _cv2


def gaussian_kernel_1d(sigma: float) -> np.ndarray:
    r = max(1, min(255, int(math.ceil(2.5 * sigma))))
    x = np.arange(-r, r + 1, dtype=np.float32)
    k = np.exp(-(x * x) / np.float32(2.0 * sigma * sigma)).astype(np.float32)
    return k / np.float32(k.sum())


def _smoothstep(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - np.float32(e0)) / np.float32(e1 - e0), 0.0, 1.0)
    return t * t * (np.float32(3.0) - np.float32(2.0) * t)


def _blur(chan: np.ndarray, k: np.ndarray) -> np.ndarray:
    cv2 = _cv()
    return cv2.sepFilter2D(chan, -1, k, k, borderType=cv2.BORDER_REFLECT_101)


def _edge_mask(l_chan: np.ndarray, masking: float) -> np.ndarray:
    cv2 = _cv()
    lp = np.pad(l_chan, 1, mode="edge")
    gx = (lp[1:-1, 2:] - lp[1:-1, :-2]) * np.float32(0.5)
    gy = (lp[2:, 1:-1] - lp[:-2, 1:-1]) * np.float32(0.5)
    grad = cv2.blur(np.hypot(gx, gy).astype(np.float32), (3, 3), borderType=cv2.BORDER_REPLICATE)
    t = SHARPEN_MASK_T_HI * masking
    return _smoothstep(0.5 * t, t, grad)


def _shadow_gain(l_chan: np.ndarray) -> np.ndarray:
    f = np.float32(SHARPEN_SHADOW_FLOOR)
    return f + (np.float32(1.0) - f) * _smoothstep(0.0, SHARPEN_SHADOW_L_HI, l_chan)


def _rl_iterations(radius: float) -> int:
    return int(np.clip(int(round(10.0 * radius)), 5, 20))


def _to_lab(pixels: np.ndarray):
    cv2 = _cv()
    rgb = pixels.astype(np.float32)
    rgb *= np.float32(1.0 / 255.0)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    return cv2.split(lab)


def _from_lab(l_new: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    cv2 = _cv()
    rgb = cv2.cvtColor(cv2.merge([l_new.astype(np.float32), a, b]), cv2.COLOR_LAB2RGB)
    rgb *= np.float32(255.0)
    np.clip(rgb, 0, 255, out=rgb)
    return (rgb + np.float32(0.5)).astype(np.uint8)


def _clamp_to_local_range(l_chan: np.ndarray, l_new: np.ndarray) -> np.ndarray:
    cv2 = _cv()
    kern3 = np.ones((3, 3), np.uint8)
    l_min = cv2.erode(l_chan, kern3, borderType=cv2.BORDER_REPLICATE)
    l_max = cv2.dilate(l_chan, kern3, borderType=cv2.BORDER_REPLICATE)
    l_new = np.clip(l_new, l_min - np.float32(SHARPEN_OVERSHOOT_DARK), l_max + np.float32(SHARPEN_OVERSHOOT_LIGHT))
    return np.clip(l_new, 0.0, 100.0)


def _gated_usm(pixels, amount, masking, blur_fn, shadow_gain: bool):
    """The shared L* unsharp-mask body: USM and Surface Blur differ only in
    what the image is diffed against (Gaussian vs bilateral blur)."""
    l_chan, a, b = _to_lab(pixels)
    diff = l_chan - blur_fn(l_chan)
    gain = np.float32(amount * 2.5) * _smoothstep(SHARPEN_GATE_LO, SHARPEN_GATE_HI, np.abs(diff))
    if shadow_gain:
        gain = gain * _shadow_gain(l_chan)
    if masking > 0.0:
        gain = gain * _edge_mask(l_chan, masking)
    l_new = _clamp_to_local_range(l_chan, l_chan + diff * gain)
    return _from_lab(l_new, a, b)


def _usm(pixels, amount, radius, masking):
    k = gaussian_kernel_1d(radius)
    # Parallel strips overlapping by more than the blur + edge-mask + 3x3
    # clamp reach, so seams match a single full-image pass.
    overlap = len(k) // 2 + 6
    return run_strips(
        lambda strip: _gated_usm(strip, amount, masking, lambda l: _blur(l, k), shadow_gain=True), pixels, overlap=overlap
    )


def _bounded_bilateral(chan: np.ndarray, sigma_color: float, sigma_space: float) -> np.ndarray:
    cv2 = _cv()
    h, w = chan.shape[:2]
    # Cost grows with the square of sigma_space, so the working size shrinks
    # with it as well as being capped at _BILATERAL_MAX_DIM: the bilateral
    # result is only a smooth reference to diff against, so a downscaled
    # one (sigma scaled to match) is visually equivalent and far cheaper.
    scale = min(1.0, _BILATERAL_MAX_DIM / max(h, w), _BILATERAL_MAX_SIGMA / sigma_space)
    if scale >= 1.0:
        return cv2.bilateralFilter(chan, 0, np.float32(sigma_color), np.float32(sigma_space), borderType=cv2.BORDER_REFLECT_101)
    small = cv2.resize(chan, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
    small_blur = cv2.bilateralFilter(small, 0, np.float32(sigma_color), np.float32(sigma_space * scale), borderType=cv2.BORDER_REFLECT_101)
    return cv2.resize(small_blur, (w, h), interpolation=cv2.INTER_LINEAR)


def _surface_blur(pixels, amount, radius, masking):
    sigma_space = max(1.0, radius * 8.0)
    return _gated_usm(
        pixels, amount, masking, lambda l: _bounded_bilateral(l, SURFACE_BLUR_COLOR_SIGMA, sigma_space), shadow_gain=False
    )


def _bounded_gaussian(chan: np.ndarray, sigma: float) -> np.ndarray:
    cv2 = _cv()
    r = max(1, min(255, int(math.ceil(2.5 * sigma))))
    if r <= _GAUSSIAN_MAX_KERNEL_R:
        return _blur(chan, gaussian_kernel_1d(sigma))
    h, w = chan.shape[:2]
    scale = _GAUSSIAN_MAX_KERNEL_R / r
    small = cv2.resize(chan, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
    small_blur = _blur(small, gaussian_kernel_1d(sigma * scale))
    return cv2.resize(small_blur, (w, h), interpolation=cv2.INTER_LINEAR)


def _wavelet(pixels, amount, radius, masking):
    l_chan, a, b = _to_lab(pixels)
    s1, s2, s3 = (radius * ratio for ratio in WAVELET_SIGMA_RATIOS)
    blur1 = _bounded_gaussian(l_chan, s1)
    blur2 = _bounded_gaussian(blur1, s2)
    blur3 = _bounded_gaussian(blur2, s3)
    medium = blur1 - blur2
    large = blur2 - blur3

    mask = _edge_mask(l_chan, masking) if masking > 0.0 else np.float32(1.0)
    medium_gain = _smoothstep(SHARPEN_GATE_LO, SHARPEN_GATE_HI, np.abs(medium))
    large_gain = _smoothstep(SHARPEN_GATE_LO, SHARPEN_GATE_HI, np.abs(large))
    boost = (
        medium * medium_gain * np.float32(_WAVELET_MEDIUM_WEIGHT) + large * large_gain * np.float32(_WAVELET_LARGE_WEIGHT)
    ) * np.float32(amount * 2.5) * mask
    return _from_lab(_clamp_to_local_range(l_chan, l_chan + boost), a, b)


def _deconvolution(pixels, amount, radius, masking):
    """Richardson-Lucy on luminance with a Gaussian PSF, applied as an RGB
    ratio so chroma is preserved. NegPy runs this on linear luminance; here
    the sRGB pixels are linearized with a plain 2.2 gamma for the luminance
    and the ratio is carried back through the inverse gamma."""
    rgb = pixels.astype(np.float32) * np.float32(1.0 / 255.0)
    lin = np.power(rgb, np.float32(_SRGB_GAMMA))
    obs = (lin[..., 0] * np.float32(0.2126) + lin[..., 1] * np.float32(0.7152) + lin[..., 2] * np.float32(0.0722)).astype(np.float32)

    k = gaussian_kernel_1d(radius)
    est = obs.copy()
    for _ in range(_rl_iterations(radius)):
        blurred = _blur(est, k)
        est = est * _blur(obs / np.maximum(blurred, np.float32(RL_EPS)), k)

    ratio = est / np.maximum(obs, np.float32(RL_EPS))
    # L* from linear Y, for the shadow-gain/mask inputs.
    l_obs = np.float32(116.0) * np.cbrt(np.maximum(obs, 0.0)) - np.float32(16.0)
    gain = np.float32(amount) * _shadow_gain(l_obs)
    if masking > 0.0:
        gain = gain * _edge_mask(l_obs, masking)

    factor = np.maximum(np.float32(1.0) + (ratio - np.float32(1.0)) * gain, 0.0)
    factor = np.power(factor, np.float32(1.0 / _SRGB_GAMMA))
    out = rgb * factor[..., np.newaxis]
    out *= np.float32(255.0)
    np.clip(out, 0, 255, out=out)
    return (out + np.float32(0.5)).astype(np.uint8)


_METHODS = {
    SharpenMethod.USM.value: _usm,
    SharpenMethod.DECONVOLUTION.value: _deconvolution,
    SharpenMethod.SURFACE_BLUR.value: _surface_blur,
    SharpenMethod.WAVELET.value: _wavelet,
}


def apply_sharpening(
    pixels: np.ndarray,
    amount: float,
    radius: float = 1.0,
    masking: float = 0.0,
    method: str = DEFAULT_METHOD,
) -> np.ndarray:
    """amount in [0, 1] (0 is a no-op); radius in pixels; masking in [0, 1]
    protects flat/noisy areas via a local-gradient mask; method is a
    SharpenMethod value."""
    if amount <= 0:
        return pixels
    return _METHODS.get(method, _usm)(pixels, amount, radius, masking)


# Which methods are cheap enough to render per interactive preview tick: while
# dragging the Sharpening sliders themselves (OWN), and while dragging any other
# tool with sharpening already set (OTHER). Slower ones (Richardson-Lucy takes
# 400-600 ms) apply once the edit settles instead - see
# Renderer.render.
LIVE_OWN_METHODS = frozenset(
    {SharpenMethod.USM.value, SharpenMethod.WAVELET.value, SharpenMethod.SURFACE_BLUR.value}
)
LIVE_OTHER_METHODS = frozenset({SharpenMethod.USM.value})
