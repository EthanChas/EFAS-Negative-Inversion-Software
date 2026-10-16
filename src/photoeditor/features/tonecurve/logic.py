"""Pure tone-curve math - numpy only, no Qt/UI imports."""

import numpy as np

from ..lut.logic import apply_channel_lut

DEFAULT_POINTS: tuple[tuple[int, int], ...] = ((0, 0), (255, 255))
CHANNELS = ("red", "green", "blue")
CHANNEL_KEYS = tuple(f"tone_curve_{c}" for c in CHANNELS)
CURVE_KEYS = ("tone_curve_points",) + CHANNEL_KEYS   # the master (RGB) curve first, then one curve for each colour channel, applied after it
AUTO_CLIP = (0.5, 99.5)   # percentiles Auto sets black and white at


def build_lut(points: list[tuple[int, int]]) -> np.ndarray:
    """A 256-entry 0-255 uint8 lookup table from sparse (x, y) control points."""
    return curve_values(points, np.arange(256, dtype=np.float64)).round().astype(np.uint8)


def curve_values(points: list[tuple[int, int]], sample_x: np.ndarray) -> np.ndarray:
    """The curve's own (unrounded, 0..255) value at each x of `sample_x`, any shape - build_lut samples it at 0..255, the wide path at every
    one of 65536 levels."""
    pts = sorted(points)
    xs = np.array([p[0] for p in pts], dtype=np.float64)
    ys = np.array([p[1] for p in pts], dtype=np.float64)

    if len(pts) == 1:
        return np.clip(np.full(np.shape(sample_x), ys[0]), 0, 255)

    tangents = _tangents(xs, ys)
    sample_x = np.asarray(sample_x, dtype=np.float64)
    segment = np.clip(np.searchsorted(xs, sample_x, side="right") - 1, 0, len(xs) - 2)

    x0, x1 = xs[segment], xs[segment + 1]
    y0, y1 = ys[segment], ys[segment + 1]
    m0, m1 = tangents[segment], tangents[segment + 1]
    h = x1 - x0
    t = (sample_x - x0) / h

    t2, t3 = t * t, t * t * t
    h00 = 2 * t3 - 3 * t2 + 1
    h10 = t3 - 2 * t2 + t
    h01 = -2 * t3 + 3 * t2
    h11 = t3 - t2
    sample_y = h00 * y0 + h10 * h * m0 + h01 * y1 + h11 * h * m1

    return np.clip(sample_y, 0, 255)


def _tangents(xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    n = len(xs)
    tangents = np.zeros(n)
    tangents[0] = (ys[1] - ys[0]) / (xs[1] - xs[0])
    tangents[-1] = (ys[-1] - ys[-2]) / (xs[-1] - xs[-2])
    for i in range(1, n - 1):
        tangents[i] = (ys[i + 1] - ys[i - 1]) / (xs[i + 1] - xs[i - 1])
    return tangents


def apply_tone_curve(pixels: np.ndarray, points: list[tuple[int, int]]) -> np.ndarray:
    """Remap every pixel through the same curve - one combined RGB curve, not three independent per-channel curves."""
    if pixels.dtype == np.float32:
        if tuple(map(tuple, points)) == DEFAULT_POINTS:
            return pixels
        grid = np.linspace(0.0, 255.0, 4097)
        return np.interp(pixels, grid, curve_values(points, grid)).astype(np.float32)
    lut = build_lut(points)
    return apply_channel_lut(pixels, np.broadcast_to(lut, (3, 256)))


def is_identity(points) -> bool:
    return tuple(map(tuple, points)) == DEFAULT_POINTS


def curves_are_identity(master, channels) -> bool:
    return is_identity(master) and all(is_identity(c) for c in channels)


def apply_curves(pixels: np.ndarray, master, channels) -> np.ndarray:
    """The master (RGB) curve, then each colour channel's own curve, on the last axis (red, green, blue) of a picture or a ramp. All three at the identity leave it untouched."""
    if curves_are_identity(master, channels):
        return pixels
    if pixels.dtype == np.float32:
        grid = np.linspace(0.0, 255.0, 4097)
        master_values = curve_values(master, grid)
        out = np.empty_like(pixels)
        for c in range(3):
            first = np.interp(pixels[..., c], grid, master_values)
            out[..., c] = np.interp(first, grid, curve_values(channels[c], grid)) if not is_identity(channels[c]) else first
        return out
    master_lut = build_lut(master)
    luts = np.stack([build_lut(channels[c])[master_lut] for c in range(3)])
    return apply_channel_lut(pixels, luts)


def inverse_input(points, value: float) -> int:
    """The input (0-255) a curve turns into `value` (0-255): the first input whose output reaches it, which is exact for a rising curve."""
    lut = build_lut(points)
    return int(min(255, np.searchsorted(lut, np.clip(round(value), 0, 255), side="left")))


def set_black(points, x: int) -> list[tuple[int, int]]:
    """The curve with its black point at input x: everything below it prints as 0."""
    x = int(min(max(x, 0), 254))
    kept = [tuple(p) for p in points if p[0] > x]
    return [(0, 0)] + ([(x, 0)] if x > 0 else []) + (kept if kept else [(255, 255)])


def set_white(points, x: int) -> list[tuple[int, int]]:
    """The curve with its white point at input x: everything above it prints as 255."""
    x = int(min(max(x, 1), 255))
    kept = [tuple(p) for p in points if p[0] < x]
    return (kept if kept else [(0, 0)]) + ([(x, 255)] if x < 255 else []) + [(255, 255)]


def add_point(points, x: int, y: int) -> list[tuple[int, int]]:
    """The curve with a point at (x, y), replacing any point within a few inputs of it; the end points stay at 0 and 255."""
    x, y = int(min(max(x, 0), 255)), int(min(max(y, 0), 255))
    near = 3
    kept = [tuple(p) for p in points if abs(p[0] - x) > near or p[0] in (0, 255)]
    if x in (0, 255):
        kept = [p for p in kept if p[0] != x]
    kept.append((x, y))
    out = sorted(set(kept))
    if out[0][0] != 0:
        out.insert(0, (0, 0))
    if out[-1][0] != 255:
        out.append((255, 255))
    return out


def pick_black(channels, rgb) -> list[list[tuple[int, int]]]:
    """Each channel curve with its black point where the picked pixel (its displayed red, green, blue) sits - so that pixel prints as black."""
    return [set_black(channels[c], inverse_input(channels[c], rgb[c])) for c in range(3)]


def pick_white(channels, rgb) -> list[list[tuple[int, int]]]:
    return [set_white(channels[c], inverse_input(channels[c], rgb[c])) for c in range(3)]


def pick_grey(channels, rgb) -> list[list[tuple[int, int]]]:
    """Each channel curve with a point that takes the picked pixel's channel to the average of the three, so that pixel comes out neutral at the brightness it had."""
    target = int(round(sum(rgb) / 3.0))
    return [add_point(channels[c], inverse_input(channels[c], rgb[c]), target) for c in range(3)]


def auto_levels(channels, image: np.ndarray) -> list[list[tuple[int, int]]]:
    """Each channel curve with its black and white points at the picture's own darkest and lightest tones (the 0.5th and 99.5th percentile of each channel)."""
    out = []
    for c in range(3):
        lo, hi = np.percentile(image[..., c], AUTO_CLIP)
        out.append(set_white(set_black(channels[c], inverse_input(channels[c], lo)), inverse_input(channels[c], hi)))
    return out
