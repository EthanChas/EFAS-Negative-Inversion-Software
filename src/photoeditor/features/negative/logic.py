"""Pure negative-film detection and inversion - numpy only, no Qt/UI imports.

Adapted from NegPy's detect_process_mode (negpy/features/process/logic.py)
and the orange-mask black/white-point math behind
analyze_log_exposure_bounds (negpy/features/exposure/normalization.py).
NegPy reads these off a raw, un-white-balanced linear scan buffer, where the
orange mask is still fully visible; PhotoEditor only ever has whatever
gamma/white-balance a file was already saved with, so these thresholds are a
heuristic starting point here, not a colorimetric match - it can misread an
already color-corrected photo as a negative, or vice versa.
"""

from enum import Enum

import numpy as np

from ..lut.logic import apply_channel_lut
from .metering import POINT_SHIFT, RANGE_STEP, Metering

_ANALYSIS_BUFFER = 0.12  # center-crop ratio - drops film rebate/sprocket holes
_ANALYSIS_MAX_DIM = 256  # downsample the analysis crop to this before any statistics -
# correlation/percentile are robust to subsampling (NegPy's own detector does the same,
# to its own 256px cap), and this is what actually keeps detection/calibration fast -
# running them on the full ~1600px preview crop was costing hundreds of milliseconds.
_BW_CORR_THRESHOLD = 0.99  # min pairwise channel correlation -> monochrome
_C41_ORANGE_THRESHOLD = 1.5  # red-over-blue cast above this -> orange mask (C41)
_PURPLE_G_DEFICIT = 0.05  # min (R+B)/2 - G, Harman Phoenix-style purple mask
_PURPLE_RB_BALANCE = 1.05  # min(R, B)/G must exceed this too
_FLOOR_DENSITY_PERCENTILE = 1.0  # low density (brightest raw pixels) -> film base
_CEIL_DENSITY_PERCENTILE = 99.0  # high density (darkest raw pixels) -> max exposure
_EPS = 1e-6


class ProcessMode(Enum):
    C41 = "c41"  # color negative (orange mask)
    BW = "bw"  # black & white negative
    E6 = "e6"  # transparency/slide - already a positive


def _center_crop(pixels: np.ndarray, buffer: float) -> np.ndarray:
    h, w = pixels.shape[:2]
    dy, dx = int(h * buffer), int(w * buffer)
    return pixels[dy : h - dy or None, dx : w - dx or None]


def _downsample_for_analysis(pixels: np.ndarray, max_dim: int) -> np.ndarray:
    """A cheap strided subsample (no resize library needed) - good enough
    for statistics like correlation/percentile, which don't need every
    pixel to land on a stable answer."""
    longest = max(pixels.shape[:2])
    if longest <= max_dim:
        return pixels
    step = max(1, longest // max_dim)
    return pixels[::step, ::step]


def _analysis_region(pixels: np.ndarray, region: tuple[int, int, int, int] | None, buffer: float = _ANALYSIS_BUFFER) -> np.ndarray:
    """region (x1,y1,x2,y2), when given, is normally the user's own crop
    rect - detection/inversion then reads only the kept composition, not
    whatever's outside it, and tracks the crop automatically since nothing
    here is cached. Falls back to the default center-crop border trim when
    there's no crop (region is None)."""
    if region is not None:
        h, w = pixels.shape[:2]
        x1, x2 = sorted((max(0, min(region[0], w)), max(0, min(region[2], w))))
        y1, y2 = sorted((max(0, min(region[1], h)), max(0, min(region[3], h))))
        if x2 - x1 >= 1 and y2 - y1 >= 1:
            return _downsample_for_analysis(pixels[y1:y2, x1:x2], _ANALYSIS_MAX_DIM)
    return _downsample_for_analysis(_center_crop(pixels, buffer), _ANALYSIS_MAX_DIM)


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a.reshape(-1), b.reshape(-1)
    if a.std() < _EPS or b.std() < _EPS:
        return 1.0  # a flat channel can't disagree with another - treat as correlated
    return float(np.corrcoef(a, b)[0, 1])


def detect_process_mode(pixels: np.ndarray, region: tuple[int, int, int, int] | None = None) -> ProcessMode:
    """Classify an image as a C41 color negative, a B&W negative, or an E6
    positive (already a normal photo - no inversion needed). region, when
    given (normally the current crop rect), is what gets analyzed instead
    of the default center-crop border trim."""
    crop = _analysis_region(pixels, region).astype(np.float32) / 255.0
    if crop.size == 0:
        return ProcessMode.C41

    r, g, b = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]

    # B&W: channels stay near-perfectly correlated even with a color tint,
    # while real color film has decorrelated channels.
    if min(_corr(r, g), _corr(g, b), _corr(r, b)) > _BW_CORR_THRESHOLD:
        return ProcessMode.BW

    r_mean, b_mean = float(r.mean()), float(b.mean())
    r_p25, b_p25 = float(np.percentile(r, 25)), float(np.percentile(b, 25))
    r_p98, g_p98, b_p98 = (float(np.percentile(c, 98)) for c in (r, g, b))

    # Orange mask (standard C41): red much greater than blue, checked across
    # density levels in case a scan was only auto-corrected in highlights.
    orange_score = max(
        (r_mean + _EPS) / (b_mean + _EPS),
        (r_p25 + _EPS) / (b_p25 + _EPS),
        (r_p98 + _EPS) / (b_p98 + _EPS),
    )
    if orange_score > _C41_ORANGE_THRESHOLD:
        return ProcessMode.C41

    # Purple mask (e.g. Harman Phoenix): red roughly equals blue, green
    # suppressed - checked at p98, the clearest film area.
    deficit = (r_p98 + b_p98) / 2 - g_p98
    balance = min(r_p98, b_p98) / (g_p98 + _EPS)
    if deficit > _PURPLE_G_DEFICIT and balance > _PURPLE_RB_BALANCE:
        return ProcessMode.C41

    return ProcessMode.E6


def compute_invert_lut(
    pixels: np.ndarray, region: tuple[int, int, int, int] | None = None, base_rgb: tuple[int, int, int] | None = None,
    metering: Metering | None = None,
) -> np.ndarray:
    """The expensive half of invert_negative, split out so a caller can
    cache it: measures each channel's film-base (floor) and max-exposure
    (ceiling) log-density from region (normally the current crop rect, so
    cropping to the real composition keeps the calibration accurate instead
    of still partly reading content you've cropped away), and returns a
    (3, 256) uint8 lookup table - one 0-255 input-to-output curve per
    channel. With base_rgb (the film base measured on the rebate with the eyedropper) each channel floor is that, instead of a guess from the picture, so every frame of a roll is calibrated to the same base. Recomputing this via np.percentile over a multi-megapixel
    region costs hundreds of milliseconds; it only actually needs
    recomputing when the region or the pre-invert pixels change (a crop, a
    rotation/flip, or a new file) - not on every unrelated slider tick, which
    is what made dragging exposure/tone curve/color sliders stutter while a
    negative was inverted, before AppController started caching this.

    metering (features/negative/metering.py) steers the reading: the edge margin used when there is no region, how hard the tails are
    clipped, how much each channel is stretched alone (cast removal), and where white and black land, overall and per channel."""
    m = metering or Metering()
    wide = pixels.dtype == np.uint16  # a 16-bit scan: the table has an entry for every one of its 65536 levels and holds unrounded floats
    top = 65535.0 if wide else 255.0
    crop = _analysis_region(pixels, region, m.buffer).astype(np.float32) / top
    crop_density = -np.log10(np.clip(crop, _EPS, 1.0))

    sample_values = np.arange(int(top) + 1, dtype=np.float32)
    sample_density = -np.log10(np.clip(sample_values / top, _EPS, 1.0))

    low_p = max(0.0, min(25.0, _FLOOR_DENSITY_PERCENTILE + m.range_clip * RANGE_STEP))
    high_p = max(75.0, min(100.0, _CEIL_DENSITY_PERCENTILE - m.range_clip * RANGE_STEP))
    floors, ceils = [], []
    for c in range(3):
        floor = float(np.percentile(crop_density[:, :, c], low_p))
        ceil = float(np.percentile(crop_density[:, :, c], high_p))
        if base_rgb is not None:
            measured = float(-np.log10(np.clip(base_rgb[c] / 255.0, _EPS, 1.0)))
            if ceil - measured > 0.15:  # a base that leaves no density range above it is a bad pick; the picture's own estimate stands
                floor = measured
        floors.append(floor)
        ceils.append(ceil)
    if m.cast_removal < 1.0:  # less than full: the channels are pulled toward a shared range, so part of the film's cast stays
        mean_floor, mean_ceil = sum(floors) / 3.0, sum(ceils) / 3.0
        floors = [mean_floor + m.cast_removal * (f - mean_floor) for f in floors]
        ceils = [mean_ceil + m.cast_removal * (c_ - mean_ceil) for c_ in ceils]
    whites, blacks = m.white_points(), m.black_points()

    lut = np.empty((3, int(top) + 1), dtype=np.float32 if wide else np.uint8)
    for c in range(3):
        span = max(ceils[c] - floors[c], _EPS)
        floor = floors[c] + blacks[c] * POINT_SHIFT * span   # a higher black point raises the floor: more shadow goes to pure black
        ceil = ceils[c] - whites[c] * POINT_SHIFT * span     # a higher white point lowers the ceiling: more highlight goes to pure white
        out = (sample_density - floor) / max(ceil - floor, _EPS)
        lut[c] = np.clip(out * 255.0, 0, 255) if wide else np.clip(out * 255.0, 0, 255).astype(np.uint8)
    return lut


def apply_invert_lut(pixels: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """The cheap half: a per-channel 0-255 lookup, same cost class as
    apply_exposure/apply_tone_curve - safe to run on every preview tick."""
    return apply_channel_lut(pixels, lut)


def invert_negative(pixels: np.ndarray, region: tuple[int, int, int, int] | None = None) -> np.ndarray:
    """Invert a negative scan to a positive in one call - computes and
    immediately applies the LUT (see compute_invert_lut/apply_invert_lut).
    Fine for a one-shot use (e.g. a thumbnail); AppController caches the
    LUT itself for the main edit pipeline, where this would otherwise
    re-run its expensive calibration on every unrelated slider tick."""
    return apply_invert_lut(pixels, compute_invert_lut(pixels, region))


FILM_TYPES = ("auto", "c41", "bw", "e6")
FILM_TYPE_LABELS = {
    "auto": "Auto-detect",
    "c41": "Color negative (C41)",
    "bw": "Black & white negative",
    "e6": "Slide film (E6)",
}
INVERT_OFFSET_LEVELS = 64.0  # a +-1 trim moves a channel by this many 0-255 levels

_MONO_WEIGHTS = np.array((0.299, 0.587, 0.114), dtype=np.float32)


def monochrome(pixels: np.ndarray) -> np.ndarray:
    """The scan's luminance copied to all three channels - a B&W negative has
    no color information worth keeping (any tint is film base or scanner)."""
    h, w, _ = pixels.shape
    luma = (pixels.reshape(-1, 3).astype(np.float32) @ _MONO_WEIGHTS).reshape(h, w)
    if pixels.dtype == np.uint16:
        gray = np.clip(luma + 0.5, 0, 65535).astype(np.uint16)
    else:
        gray = np.clip(luma + 0.5, 0, 255).astype(np.uint8)
    return np.repeat(gray[:, :, None], 3, axis=2)


def apply_channel_offsets(pixels: np.ndarray, offsets: tuple[float, float, float]) -> np.ndarray:
    """Manual red/green/blue trim of the positive, each in [-1, 1]: positive
    adds that color, negative removes it. Pointwise per channel, so it folds
    into the same lookup table as the inversion."""
    if not any(offsets):
        return pixels
    out = pixels.astype(np.float32)
    for c in range(3):
        out[..., c] += offsets[c] * INVERT_OFFSET_LEVELS
    if pixels.dtype == np.float32:  # a wide ramp: keep every fraction
        return np.clip(out, 0, 255)
    return np.clip(out, 0, 255).astype(np.uint8)
