"""Tone Equalizer, ported from darktable's module of that name (src/iop/toneequal.c, common/luminance_mask.h, common/fast_guided_filter.h and common/eigf.h, GPL-3.0) - numpy and OpenCV only.

darktable's tone equalizer, by Aurelien Pierre, relights the scene by an exposure correction chosen for each *octave* of brightness, the way an audio equalizer sets a gain for each octave of
sound. Nine nodes sit one EV apart from -8 EV to 0 EV (0 EV being white); the gain at any brightness is a smooth curve through them (a series of gaussians, solved by least squares - "curve
smoothing" sets how wide they are). The brightness of each pixel is not the pixel's own but that of a *mask*: a luminance estimate (one of seven norms of the RGB triplet) that is, by default,
blurred by an edge-aware guided filter (or darktable's "exposure-independent" version of it, EIGF) so that the gain follows the light of a region and the local contrast inside it is kept.
"exposure" and "contrast" compensation slide and spread the mask so that the picture uses all the nodes; "feathering" and "quantization" tune how closely the blur follows edges.

The picture is worked in linear light (darktable's module is scene-referred): the 8-bit sRGB picture is made linear, multiplied by the gain, clipped to white and brought back."""
import math

import numpy as np

from ..diffuse.logic import _from_linear, _to_linear

BANDS = tuple(f"teq_band{i}" for i in range(9))     # the nodes at -8 EV ... 0 EV
BAND_LABELS = ("-8 EV", "-7 EV", "-6 EV", "-5 EV", "-4 EV", "-3 EV", "-2 EV", "-1 EV", "+0 EV")
KEYS = (*BANDS, "teq_smoothing", "teq_exposure_boost", "teq_contrast_boost", "teq_method", "teq_details", "teq_iterations", "teq_blending", "teq_feathering", "teq_quantization")
DEFAULTS = {**{k: 0.0 for k in BANDS}, "teq_smoothing": 0.0, "teq_exposure_boost": 0.0, "teq_contrast_boost": 0.0, "teq_method": 4.0, "teq_details": 4.0,
            "teq_iterations": 1.0, "teq_blending": 5.0, "teq_feathering": 1.0, "teq_quantization": 0.0}
RANGES = {**{k: (-2.0, 2.0) for k in BANDS}, "teq_smoothing": (-2.33, 1.67), "teq_exposure_boost": (-16.0, 16.0), "teq_contrast_boost": (-16.0, 16.0), "teq_method": (0, 6),
          "teq_details": (0, 4), "teq_iterations": (1, 20), "teq_blending": (0.01, 100.0), "teq_feathering": (0.01, 10000.0), "teq_quantization": (0.0, 2.0)}
LIVE = "toneequalizer"

(MEAN, LIGHTNESS, VALUE, NORM_1, NORM_2, NORM_POWER, GEOMEAN) = range(7)
METHOD_LABELS = ("RGB average", "HSL lightness", "HSV value / RGB max", "RGB sum", "RGB euclidean norm", "RGB power norm", "RGB geometric mean")
(NONE, AVG_GUIDED, GUIDED, AVG_EIGF, EIGF) = range(5)
DETAILS_LABELS = ("no", "averaged guided filter", "guided filter", "averaged EIGF", "EIGF")

MIN_EV, MAX_EV = -8.0, 0.0
CONTRAST_FULCRUM = 2.0 ** -4
MIN_FLOAT = 2.0 ** -16
LUT_RESOLUTION = 10000
_CENTRES_OPS = np.array([-56.0 / 7, -48.0 / 7, -40.0 / 7, -32.0 / 7, -24.0 / 7, -16.0 / 7, -8.0 / 7, 0.0], dtype=np.float64)   # the 8 gaussians (8 EV split in 7 steps)
_CENTRES_PARAMS = np.arange(-8.0, 1.0, 1.0)                                                                                        # the 9 nodes


def is_neutral(values: dict | None) -> bool:
    v = values or {}
    return all(abs(float(v.get(k, 0.0))) <= 1e-9 for k in BANDS)


def sigma_of(smoothing: float) -> float:
    """The width of the gaussians from the "curve smoothing" slider (smoothing_callback: sqrt(2) ^ (1 + slider))."""
    return math.sqrt(2.0) ** (1.0 + float(smoothing))


# ---------------------------------------------------------------------------------------------------------------------------------------------- the curve
def channel_factors(values: dict) -> np.ndarray:
    """The 8 gaussian weights whose sum passes close to the 9 nodes (build_interpolation_matrix, pseudo_solve)."""
    sigma = sigma_of(values.get("teq_smoothing", 0.0))
    targets = np.exp2(np.array([float(values.get(k, 0.0)) for k in BANDS]))
    denom = 2.0 * sigma * sigma
    A = np.exp(-((_CENTRES_PARAMS[:, None] - _CENTRES_OPS[None, :]) ** 2) / denom)
    return np.linalg.lstsq(A, targets, rcond=None)[0]


def pixel_correction(exposure, factors: np.ndarray, sigma: float):
    """The gain at a brightness (in EV): the sum of the gaussians weighted by the factors, clamped to a quarter to four times."""
    e = np.clip(exposure, MIN_EV, MAX_EV)
    g = np.exp(-((np.asarray(e)[..., None] - _CENTRES_OPS) ** 2) / (2.0 * sigma * sigma))
    return np.clip((g * factors).sum(axis=-1), 0.25, 4.0)


def correction_curve(values: dict, points: int = 256) -> tuple[np.ndarray, np.ndarray]:
    """(the brightness in EV, the correction in EV) of the curve, to draw."""
    ev = np.linspace(MIN_EV, MAX_EV, points)
    return ev, np.log2(pixel_correction(ev, channel_factors(values), sigma_of(values.get("teq_smoothing", 0.0))))


def correction_lut(values: dict) -> np.ndarray:
    sigma = sigma_of(values.get("teq_smoothing", 0.0))
    ev = np.arange(LUT_RESOLUTION * 8 + 1, dtype=np.float64) / LUT_RESOLUTION + MIN_EV
    return pixel_correction(ev, channel_factors(values), sigma).astype(np.float32)


# ---------------------------------------------------------------------------------------------------------------------------------------------- the luminance mask
def luminance_mask(linear: np.ndarray, method: int, exposure_boost: float, fulcrum: float, contrast_boost: float) -> np.ndarray:
    """The luminance of each pixel by one of the seven norms, with the exposure compensation and the contrast about `fulcrum`, never below 2^-16."""
    r, g, b = linear[..., 0], linear[..., 1], linear[..., 2]
    if method == MEAN:
        lum = (r + g + b) / 3.0
    elif method == VALUE:
        lum = np.maximum(np.maximum(r, g), b)
    elif method == LIGHTNESS:
        lum = (np.maximum(np.maximum(r, g), b) + np.minimum(np.minimum(r, g), b)) / 2.0
    elif method == NORM_1:
        lum = np.abs(r) + np.abs(g) + np.abs(b)
    elif method == NORM_2:
        lum = np.sqrt(r * r + g * g + b * b)
    elif method == NORM_POWER:
        ar, ag, ab = np.abs(r), np.abs(g), np.abs(b)
        num = ar * ar * ar + ag * ag * ag + ab * ab * ab
        den = ar * ar + ag * ag + ab * ab
        lum = np.where(den > 0, num / np.where(den > 0, den, 1.0), 0.0)
    else:
        lum = np.cbrt(np.abs(r) * np.abs(g) * np.abs(b))
    lum = lum * np.float32(exposure_boost)
    return np.maximum((lum - np.float32(fulcrum)) * np.float32(contrast_boost) + np.float32(fulcrum), np.float32(MIN_FLOAT)).astype(np.float32)


def _resize(img: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    import cv2

    return cv2.resize(img, (size[1], size[0]), interpolation=cv2.INTER_LINEAR)


def _box_mean(img: np.ndarray, radius: int) -> np.ndarray:
    import cv2

    k = 2 * radius + 1
    return cv2.blur(img, (k, k), borderType=cv2.BORDER_REPLICATE)


def _quantize(img: np.ndarray, sampling: float, lo: float, hi: float) -> np.ndarray:
    if sampling == 0.0:
        return img.copy()
    lg = np.log2(img)
    q = np.floor(lg) if sampling == 1.0 else np.floor(lg / sampling) * sampling
    return np.clip(np.exp2(q), lo, hi).astype(np.float32)


def _fast_surface_blur(image: np.ndarray, radius: int, feathering: float, iterations: int, geomean: bool, quantization: float) -> np.ndarray:
    """fast_surface_blur: a guided filter of the mask by itself, on a picture a quarter of the size."""
    h, w = image.shape
    scaling = 4.0
    ds_radius = 1 if radius < 4 else int(radius / scaling)
    ds_h, ds_w = max(1, int(h / scaling)), max(1, int(w / scaling))
    ds_image = _resize(image, (ds_h, ds_w))
    ab = None
    for i in range(iterations):
        ds_mask = _quantize(ds_image, quantization, 2.0 ** -14, 4.0)
        # variance_analyse: the mean and variance of the guide (the quantised mask) and its covariance with the image
        mean_g = _box_mean(ds_mask, ds_radius)
        mean_i = _box_mean(ds_image, ds_radius)
        corr_gg = _box_mean(ds_mask * ds_mask, ds_radius)
        corr_gi = _box_mean(ds_mask * ds_image, ds_radius)
        d = np.maximum((corr_gg - mean_g * mean_g) + np.float32(feathering), 1e-15)
        a = (corr_gi - mean_g * mean_i) / d
        b = mean_i - a * mean_g
        a, b = _box_mean(a, ds_radius), _box_mean(b, ds_radius)
        ab = (a, b)
        if i != iterations - 1:
            ds_image = np.maximum(ds_image * a + b, np.float32(MIN_FLOAT))
    a_full, b_full = _resize(ab[0], (h, w)), _resize(ab[1], (h, w))
    out = np.maximum(image * a_full + b_full, np.float32(MIN_FLOAT))
    return np.sqrt(image * out) if geomean else out


def _gaussian(img: np.ndarray, sigma: float) -> np.ndarray:
    import cv2

    return cv2.GaussianBlur(img, (0, 0), sigma, borderType=cv2.BORDER_REPLICATE)


def _fast_eigf_surface_blur(image: np.ndarray, sigma: float, feathering: float, iterations: int, geomean: bool, quantization: float) -> np.ndarray:
    """fast_eigf_surface_blur: the exposure-independent guided filter (the variance is divided by the pixel's own brightness)."""
    h, w = image.shape
    scaling = max(min(sigma, 4.0), 1.0)
    ds_sigma = max(sigma / scaling, 1.0)
    ds_h, ds_w = max(1, int(h / scaling)), max(1, int(w / scaling))
    image = image.copy()
    for i in range(iterations):
        geo = geomean and i == iterations - 1
        ds_image = _resize(image, (ds_h, ds_w))
        if quantization != 0.0:
            mask = _quantize(image, quantization, 2.0 ** -14, 4.0)
            ds_mask = _resize(mask, (ds_h, ds_w))
            avg_g = _gaussian(ds_mask, ds_sigma)
            var_g = _gaussian(ds_mask * ds_mask, ds_sigma) - avg_g * avg_g
            avg_m = _gaussian(ds_image, ds_sigma)
            covar = _gaussian(ds_image * ds_mask, ds_sigma) - avg_g * avg_m
            avg_g, var_g, avg_m, covar = (_resize(x, (h, w)) for x in (avg_g, var_g, avg_m, covar))
            norm_g = np.maximum(avg_g * image, 1e-6)
            norm_m = np.maximum(avg_m * mask, 1e-6)
            nvar = var_g / norm_g
            ncov = covar / np.sqrt(norm_g * norm_m)
            a = ncov / (nvar + np.float32(feathering))
            b = avg_m - a * avg_g
        else:
            avg_g = _gaussian(ds_image, ds_sigma)
            var_g = _gaussian(ds_image * ds_image, ds_sigma) - avg_g * avg_g
            avg_g, var_g = _resize(avg_g, (h, w)), _resize(var_g, (h, w))
            norm_g = np.maximum(avg_g * image, 1e-6)
            nvar = var_g / norm_g
            a = nvar / (nvar + np.float32(feathering))
            b = avg_g - a * avg_g
        out = np.maximum(image * a + b, np.float32(MIN_FLOAT))
        image = np.sqrt(image * out) if geo else out
    return image.astype(np.float32)


def compute_mask(linear: np.ndarray, values: dict) -> np.ndarray:
    """compute_luminance_mask: the mask the gain is looked up from."""
    v = {**DEFAULTS, **values}
    method, details = int(round(v["teq_method"])), int(round(v["teq_details"]))
    exposure, contrast = 2.0 ** float(v["teq_exposure_boost"]), 2.0 ** float(v["teq_contrast_boost"])
    feathering = 1.0 / max(float(v["teq_feathering"]), 1e-6)
    iterations = max(1, int(round(v["teq_iterations"])))
    quant = float(v["teq_quantization"])
    h, w = linear.shape[:2]
    radius = int((float(v["teq_blending"]) / 100.0 * max(h, w) - 1.0) / 2.0)
    radius = max(radius, 0)
    if details in (NONE,):
        return luminance_mask(linear, method, exposure, 0.0, 1.0)
    if details == AVG_GUIDED:
        return _fast_surface_blur(luminance_mask(linear, method, exposure, 0.0, 1.0), radius, feathering, iterations, True, quant)
    if details == GUIDED:
        return _fast_surface_blur(luminance_mask(linear, method, exposure, CONTRAST_FULCRUM, contrast), radius, feathering, iterations, False, quant)
    if details == AVG_EIGF:
        return _fast_eigf_surface_blur(luminance_mask(linear, method, exposure, 0.0, 1.0), radius, feathering, iterations, True, quant)
    return _fast_eigf_surface_blur(luminance_mask(linear, method, exposure, CONTRAST_FULCRUM, contrast), radius, feathering, iterations, False, quant)


def apply_tone_equalizer(pixels: np.ndarray, values: dict | None) -> np.ndarray:
    """The picture (uint8 RGB) with each pixel's exposure corrected by the curve at the brightness of its mask."""
    if is_neutral(values):
        return pixels
    v = {**DEFAULTS, **{k: float(x) for k, x in (values or {}).items() if k in DEFAULTS}}
    linear = _to_linear(pixels)
    mask = compute_mask(linear, v)
    lut = correction_lut(v)
    exposure = np.clip(np.log2(mask), MIN_EV, MAX_EV)
    gain = lut[np.rint((exposure - MIN_EV) * LUT_RESOLUTION).astype(np.int32)]
    return _from_linear(linear * gain[..., None])


# ---------------------------------------------------------------------------------------------------------------------------------------------- the helpers of the panel
def mask_picture(pixels: np.ndarray, values: dict | None) -> np.ndarray:
    """The luminance mask as a grey picture (display_luminance_mask: its brightness between -8 EV and 0 EV, with a square root for legibility in the shadows)."""
    v = {**DEFAULTS, **{k: float(x) for k, x in (values or {}).items() if k in DEFAULTS}}
    mask = compute_mask(_to_linear(pixels), v)
    grey = np.sqrt(np.clip((mask - 0.00390625) / 0.99609375, 0.0, 1.0)).astype(np.float32)
    return _from_linear(np.repeat(grey[..., None], 3, axis=2))


def mask_stats(pixels: np.ndarray, values: dict) -> tuple[np.ndarray, float, float]:
    """(the histogram, the first and the last decile in EV) of the luminance mask of a picture (uint8 RGB) with these settings - what the graph shows and the wands read."""
    v = {**DEFAULTS, **{k: float(x) for k, x in (values or {}).items() if k in DEFAULTS}}
    return mask_histogram(compute_mask(_to_linear(pixels), v))


def mask_histogram(mask: np.ndarray, samples: int = 256) -> tuple[np.ndarray, float, float]:
    """(the histogram of the mask between -8 and 0 EV, and its first and last decile in EV) - compute_log_histogram_and_stats."""
    temp = 2 * samples
    ev = np.log2(np.maximum(mask, 1e-30))
    index = np.clip(((ev + 10.0) / 16.0 * temp).astype(np.int64), 0, temp - 1)
    temp_hist = np.bincount(index.ravel(), minlength=temp)
    n = mask.size
    first, last = int(n * 0.05), int(n * (1.0 - 0.95))
    cum = np.cumsum(temp_hist)
    first_pos = int(np.searchsorted(cum, first, side="left")) if first > 0 else 0
    rev = np.cumsum(temp_hist[::-1])
    last_pos = temp - 1 - (int(np.searchsorted(rev, last, side="left")) if last > 0 else 0)
    fd = 16.0 * first_pos / (temp - 1) - 10.0
    ld = 16.0 * last_pos / (temp - 1) - 10.0
    hist = np.zeros(samples, dtype=np.int64)
    evs = 16.0 * np.arange(temp) / (temp - 1) - 10.0
    idx = np.clip(((evs + 8.0) / 8.0 * samples).astype(np.int64), 0, samples - 1)
    np.add.at(hist, idx, temp_hist)
    return hist, float(fd), float(ld)


def auto_exposure_boost(deciles: tuple[float, float], values: dict) -> float:
    """The wand next to "mask exposure compensation": centre the mask's brightness on -4 EV (auto_adjust_exposure_boost)."""
    fd_new, ld_new = 2.0 ** deciles[0], 2.0 ** deciles[1]
    e, c = 2.0 ** float(values.get("teq_exposure_boost", 0.0)), 2.0 ** float(values.get("teq_contrast_boost", 0.0))
    fd_old = ((fd_new - CONTRAST_FULCRUM) / c + CONTRAST_FULCRUM) / e
    ld_old = ((ld_new - CONTRAST_FULCRUM) / c + CONTRAST_FULCRUM) / e
    s1, s2 = CONTRAST_FULCRUM - 2.0 ** -7, 2.0 ** -1 - CONTRAST_FULCRUM
    mix = fd_old * s2 + ld_old * s1
    return float(math.log2(CONTRAST_FULCRUM * (s1 + s2) / mix))


def auto_contrast_boost(deciles: tuple[float, float], values: dict) -> float:
    """The wand next to "mask contrast compensation": spread 90% of the mask over -7 to -1 EV (auto_adjust_contrast_boost)."""
    fd_new, ld_new = 2.0 ** deciles[0], 2.0 ** deciles[1]
    e, c = 2.0 ** float(values.get("teq_exposure_boost", 0.0)), 2.0 ** float(values.get("teq_contrast_boost", 0.0))
    fd_old = ((fd_new - CONTRAST_FULCRUM) / c + CONTRAST_FULCRUM) / e
    ld_old = ((ld_new - CONTRAST_FULCRUM) / c + CONTRAST_FULCRUM) / e
    s1, s2 = CONTRAST_FULCRUM - 2.0 ** -7, 2.0 ** -1 - CONTRAST_FULCRUM
    mix = fd_old * s2 + ld_old * s1
    step = math.log2(mix / (CONTRAST_FULCRUM * (ld_old - fd_old)) / c)
    details = int(round(float(values.get("teq_details", EIGF))))
    feathering = float(values.get("teq_feathering", 1.0))
    if details == EIGF and step > 0.0:
        correction = -0.0276 + 0.01823 * feathering + (0.7566 - 1.0) * step
        if feathering < 5.0:
            step += correction
        elif feathering < 10.0:
            step += correction * (2.0 - feathering / 5.0)
    elif details == GUIDED and step > 0.0:
        step = 0.0235 + 1.1225 * step
    return float(values.get("teq_contrast_boost", 0.0)) + step


# ---------------------------------------------------------------------------------------------------------------------------------------------- darktable's presets
def _bands(*gains) -> dict:
    return {f"teq_band{i}": float(g) for i, g in enumerate(gains)}


def _compress(step: float) -> dict:
    return _bands(step, 5 / 3 * step, 5 / 3 * step, step, 0.0, -step, -5 / 3 * step, -5 / 3 * step, -step)


def _dilate(step: float) -> dict:
    return _bands(-15 / 9 * step, -14 / 9 * step, -12 / 9 * step, -8 / 9 * step, 0.0, 8 / 9 * step, 12 / 9 * step, 14 / 9 * step, 15 / 9 * step)


def _preset(details, method, exposure, contrast, blending, feathering, iterations, quantization, bands) -> dict:
    return {**DEFAULTS, **bands, "teq_details": float(details), "teq_method": float(method), "teq_exposure_boost": exposure, "teq_contrast_boost": contrast,
            "teq_blending": blending, "teq_feathering": feathering, "teq_iterations": float(iterations), "teq_quantization": quantization, "teq_smoothing": 0.0}


PRESETS: dict[str, dict] = {
    "simple tone curve": _preset(NONE, NORM_POWER, -0.5, 0.0, 5.0, 1.0, 1, 0.0, {}),
    "mask blending | all purposes": _preset(EIGF, NORM_2, 0.0, 0.0, 5.0, 1.0, 1, 0.0, {}),
    "mask blending | people with backlight": _preset(EIGF, NORM_2, 0.0, 0.0, 1.0, 10.0, 3, 0.0, {}),
    "compress shadows/highlights | EIGF | strong": _preset(EIGF, NORM_2, -1.57, 0.0, 2.0, 20.0, 5, 0.0, _compress(0.65)),
    "compress shadows/highlights | GF | strong": _preset(GUIDED, NORM_2, -1.57, 0.0, 2.0, 500.0, 5, 0.0, _compress(0.65)),
    "compress shadows/highlights | EIGF | medium": _preset(EIGF, NORM_2, -1.57, 0.0, 3.0, 7.0, 3, 0.0, _compress(0.45)),
    "compress shadows/highlights | GF | medium": _preset(GUIDED, NORM_2, -1.57, 0.0, 3.0, 500.0, 3, 0.0, _compress(0.45)),
    "compress shadows/highlights | EIGF | soft": _preset(EIGF, NORM_2, -1.57, 0.0, 5.0, 1.0, 1, 0.0, _compress(0.25)),
    "compress shadows/highlights | GF | soft": _preset(GUIDED, NORM_2, -1.57, 0.0, 5.0, 500.0, 1, 0.0, _compress(0.25)),
    "contrast tone curve | soft": _preset(NONE, NORM_2, -1.57, 0.0, 5.0, 500.0, 1, 0.0, _dilate(0.25)),
    "contrast tone curve | medium": _preset(NONE, NORM_2, -1.57, 0.0, 5.0, 500.0, 1, 0.0, _dilate(0.45)),
    "contrast tone curve | strong": _preset(NONE, NORM_2, -1.57, 0.0, 5.0, 500.0, 1, 0.0, _dilate(0.65)),
    "relight: fill-in": _preset(EIGF, NORM_2, -0.5, 0.0, 5.0, 1.0, 1, 0.0, _bands(0.0, 0.15, 0.6, 1.15, 1.33, 1.15, 0.6, 0.15, 0.0)),
}


APPLY = apply_tone_equalizer          # what the renderer calls (desktop/render.py)
