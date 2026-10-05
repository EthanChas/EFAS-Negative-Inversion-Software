"""Pure white-balance / exposure math - numpy only, no Qt/UI imports."""

import numpy as np

HistogramData = dict[str, list[int]]

# Standard luma weights (ITU-R BT.601) - used for the single "how bright is
# this pixel/image overall" reading, distinct from the three raw R/G/B channels.
_LUMA_WEIGHTS = (0.299, 0.587, 0.114)


def rgb_histogram(pixels: np.ndarray) -> HistogramData:
    """Per-channel pixel-value histogram (0-255) for an HxWx3 uint8 array.
    bincount, not np.histogram - histogram's float bin-edge machinery is
    markedly slower for this exact 0-255-integer case (measured ~5x), and
    with this running on every interactive exposure-slider tick, that gap
    was the difference between smooth and visibly stuttering."""
    channels = {}
    for index, name in enumerate(("r", "g", "b")):
        counts = np.bincount(pixels[:, :, index].reshape(-1), minlength=256)
        channels[name] = counts[:256].tolist()
    return channels


def luminance_histogram(pixels: np.ndarray) -> list[int]:
    """Single-channel perceived-brightness histogram (0-255) - the "Exposure"
    view of the white balance graph, as opposed to the three raw R/G/B
    channels shown by the "Color" view."""
    luminance = _luminance_array(pixels).astype(np.uint8)
    counts = np.bincount(luminance.reshape(-1), minlength=256)
    return counts[:256].tolist()


def _luminance_array(pixels: np.ndarray) -> np.ndarray:
    return (
        _LUMA_WEIGHTS[0] * pixels[:, :, 0]
        + _LUMA_WEIGHTS[1] * pixels[:, :, 1]
        + _LUMA_WEIGHTS[2] * pixels[:, :, 2]
    )


def channel_stats(pixels: np.ndarray) -> dict[str, dict[str, float]]:
    """Min / max / average value and shadow/highlight clipping percentage
    per channel - a quick numeric read on color cast and white balance."""
    stats = {}
    total = pixels.shape[0] * pixels.shape[1]
    for index, name in enumerate(("r", "g", "b")):
        channel = pixels[:, :, index]
        stats[name] = {
            "min": float(channel.min()),
            "max": float(channel.max()),
            "avg": float(channel.mean()),
            "shadow_clip_pct": float((channel == 0).sum()) / total * 100.0,
            "highlight_clip_pct": float((channel == 255).sum()) / total * 100.0,
        }
    return stats


def luminance_of(rgb: tuple[int, int, int]) -> float:
    """Perceived brightness (0-255) of a single R/G/B pixel."""
    r, g, b = rgb
    return _LUMA_WEIGHTS[0] * r + _LUMA_WEIGHTS[1] * g + _LUMA_WEIGHTS[2] * b


def luminance_stats(pixels: np.ndarray) -> dict[str, float]:
    """Min / max / average perceived brightness across the whole image."""
    luminance = _luminance_array(pixels)
    return {"min": float(luminance.min()), "max": float(luminance.max()), "avg": float(luminance.mean())}


def exposure_label(avg_luminance: float) -> str:
    """A plain-language read on `luminance_stats(...)["avg"]`."""
    if avg_luminance < 60:
        return "Underexposed"
    if avg_luminance > 190:
        return "Overexposed"
    return "Well exposed"


CLIP_SHADOW_MAX = 3  # luminance at or below this counts as crushed to black
CLIP_HIGHLIGHT_MIN = 252  # at or above this counts as blown out
_CLIP_SHADOW_RGB = (50, 110, 255)  # blue
_CLIP_HIGHLIGHT_RGB = (255, 40, 40)  # red


def clipping_overlay(pixels: np.ndarray, shadows: bool, highlights: bool):
    """RGBA marking clipped tones - shadows blue, highlights red - or None if
    neither asked-for kind of clipping is present. Clipping is judged on
    luminance, the same quantity the Exposure graph plots. Returns
    (rgba or None, shadow_fraction, highlight_fraction)."""
    h, w, _ = pixels.shape
    luma = (pixels.reshape(-1, 3).astype(np.float32) @ np.array(_LUMA_WEIGHTS, dtype=np.float32)).reshape(h, w)
    dark = luma <= CLIP_SHADOW_MAX
    bright = luma >= CLIP_HIGHLIGHT_MIN
    total = float(h * w)
    fractions = (float(dark.sum()) / total, float(bright.sum()) / total)
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    any_marked = False
    if shadows and dark.any():
        rgba[dark] = (*_CLIP_SHADOW_RGB, 255)
        any_marked = True
    if highlights and bright.any():
        rgba[bright] = (*_CLIP_HIGHLIGHT_RGB, 255)
        any_marked = True
    return (rgba if any_marked else None), fractions[0], fractions[1]
