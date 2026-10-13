"""Print Response: Snap, Toe and Shoulder - the shape of a print's characteristic (Hurter-Driffield) curve - numpy only, no Qt/UI imports.

The edit works on density (-log10 of the linear brightness), where a print's response is naturally shaped:

  Snap      adds  snap * W * tanh((d - d0) / W)   - steeper (or flatter) midtones around mid grey d0, the two ends left to roll off
  Toe       takes  toe * softplus(d - knee_toe, w) away  - compresses the shadows: positive eases them into black (film-like), negative sends them to black faster
  Shoulder  adds  shoulder * softplus(knee_sh - d, w)   - compresses the highlights: positive eases them into white, negative pushes them harder to white

Each term is zero when its slider is zero, so the neutral setting changes nothing, bit for bit. The curve stays rising (never reverses a tone) while |Snap| < 1 and
|Toe|, |Shoulder| <= 1 / strength, which the slider ranges keep to. It is applied to the per-channel tone table the renderer already builds (see apply_print_response), so it
costs nothing per pixel.
"""
import numpy as np

SNAP_RANGE = 0.5
TOE_RANGE = 1.0
SHOULDER_RANGE = 1.0
WIDTH_MIN, WIDTH_MAX, WIDTH_DEFAULT = 0.1, 5.0, 2.5

PIVOT_DENSITY = 0.75  # mid grey: about 18% of white
SNAP_WIDTH = 0.6  # density over which the Snap bump rolls off either side of the pivot
TOE_KNEE = 1.6  # density where the toe starts to bite (shadows are high density)
SHOULDER_KNEE = 0.35  # density where the shoulder starts to bite (highlights are low density)
KNEE_WIDTH = 0.45  # softness of both knees at the default width
TOE_STRENGTH = 0.8  # density taken off per unit of Toe
SHOULDER_STRENGTH = 0.5  # density added per unit of Shoulder
_FLOOR = 1e-4  # the darkest linear value (density 4)

# the sliders' keys, defaults and ranges - the Print Response module and its presets are built from these
DEFAULTS = {"print_snap": 0.0, "print_toe": 0.0, "print_toe_width": WIDTH_DEFAULT, "print_shoulder": 0.0, "print_shoulder_width": WIDTH_DEFAULT}


def is_neutral(snap: float, toe: float, shoulder: float) -> bool:
    """True when nothing is set: the widths only matter while Toe or Shoulder is not zero."""
    return snap == 0.0 and toe == 0.0 and shoulder == 0.0


def _srgb_to_linear(v: np.ndarray) -> np.ndarray:
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(v: np.ndarray) -> np.ndarray:
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * np.power(np.maximum(v, 0.0), 1 / 2.4) - 0.055)


def _softplus(x: np.ndarray, width: float) -> np.ndarray:
    """width * log(1 + exp(x / width)), safe for large |x|: close to x for x >> width, close to 0 for x << -width."""
    t = x / width
    return width * (np.logaddexp(0.0, -np.abs(t)) + np.maximum(t, 0.0))


def knee_width(slider: float) -> float:
    """The knee softness, in density, for a Width slider (2.5 is the reference: 0.45)."""
    return KNEE_WIDTH * max(WIDTH_MIN, float(slider)) / WIDTH_DEFAULT


def shape_density(d: np.ndarray, snap: float, toe: float, toe_width: float, shoulder: float, shoulder_width: float) -> np.ndarray:
    """The three terms, on densities."""
    if snap:
        d = d + snap * SNAP_WIDTH * np.tanh((d - PIVOT_DENSITY) / SNAP_WIDTH)
    if toe:
        d = d - toe * TOE_STRENGTH * _softplus(d - TOE_KNEE, knee_width(toe_width))
    if shoulder:
        d = d + shoulder * SHOULDER_STRENGTH * _softplus(SHOULDER_KNEE - d, knee_width(shoulder_width))
    return d


def apply_print_response(display: np.ndarray, snap: float, toe: float, toe_width: float = WIDTH_DEFAULT, shoulder: float = 0.0,
                         shoulder_width: float = WIDTH_DEFAULT) -> np.ndarray:
    """`display`: tone values on the 0..255 display scale (any shape, float) -> the same scale, shaped. With every slider at zero the array comes back untouched."""
    if is_neutral(snap, toe, shoulder):
        return display
    x = np.clip(np.asarray(display, dtype=np.float64) / 255.0, 0.0, 1.0)
    linear = np.maximum(_srgb_to_linear(x), _FLOOR)
    d = shape_density(-np.log10(linear), snap, toe, toe_width, shoulder, shoulder_width)
    out = _linear_to_srgb(np.clip(np.power(10.0, -d), 0.0, 1.0)) * 255.0
    return out.astype(np.asarray(display).dtype if np.asarray(display).dtype.kind == "f" else np.float32)


def curve_points(snap: float, toe: float, toe_width: float, shoulder: float, shoulder_width: float, samples: int = 64) -> list[tuple[float, float]]:
    """The response as (in, out) pairs on a 0..1 display scale, for drawing it."""
    xs = np.linspace(0.0, 255.0, samples)
    ys = apply_print_response(xs, snap, toe, toe_width, shoulder, shoulder_width)
    return [(float(x) / 255.0, float(y) / 255.0) for x, y in zip(xs, ys)]
