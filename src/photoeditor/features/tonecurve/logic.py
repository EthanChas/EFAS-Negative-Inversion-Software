"""Pure tone-curve math - numpy only, no Qt/UI imports."""

import numpy as np

from ..lut.logic import apply_channel_lut

# Identity curve: a straight diagonal line, output == input.
DEFAULT_POINTS: tuple[tuple[int, int], ...] = ((0, 0), (255, 255))


def build_lut(points: list[tuple[int, int]]) -> np.ndarray:
    """A 256-entry 0-255 uint8 lookup table from sparse (x, y) control
    points. Uses a cubic Hermite spline through them - each interior
    point's tangent is the slope between its two neighbors (the standard
    Catmull-Rom choice) - so the curve passes exactly through every point
    and bends smoothly between them, instead of the sharp corners a plain
    connect-the-dots polyline would have."""
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

    # Cubic Hermite basis functions.
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
    """Remap every pixel through the same curve - one combined RGB curve,
    not three independent per-channel curves."""
    if pixels.dtype == np.float32:  # a wide ramp: the curve's own values, not rounded
        if tuple(map(tuple, points)) == DEFAULT_POINTS:
            return pixels
        grid = np.linspace(0.0, 255.0, 4097)  # the spline sampled finely, then read off by interpolation: far cheaper than evaluating it 196608 times
        return np.interp(pixels, grid, curve_values(points, grid)).astype(np.float32)
    lut = build_lut(points)
    return apply_channel_lut(pixels, np.broadcast_to(lut, (3, 256)))
