"""A film's own characteristic curve, put back into the Original and the Noritsu conversions.

Both of those conversions stretch the scan's density in a straight line, so the film's toe and shoulder (where density stops following the light) go into the picture as they are:
shadows are squeezed and highlights flattened. A film profile (features/densitometry: the maker's published curve, or one measured from a step tablet) says how the film really
responds. `build` turns it into a per-channel table that takes a scan's density back to log exposure (the inverse of the curve, as the curve-informed inversion does) and carries it
on along the curve's own straight section, so the result is a density again: the density an ideal film with no toe and no shoulder, and the same gradient, would have made. Everything
after it (Original's floor and ceiling, Noritsu's Dmin, Dmax and tone curve) then works on that straightened density and is otherwise unchanged. Numpy only, no Qt imports.
"""

import os
from dataclasses import dataclass

import numpy as np

from ..datadir import app_data_dir
from ..densitometry import film_profile as fpmod
from ..densitometry import inversion
from ..densitometry.fit import invert_curve
from .printengine import UNSURE_BASE

GRID_STEP = 0.002          # the density spacing of the table
GRID_MAX = 5.1             # the densest a uint16 density code can be (65535 / DENSITY_SCALE) with a little to spare
CURVE_POINTS = 801         # where the curve is sampled to find its steepest part


@dataclass(frozen=True, eq=False)
class FilmCurve:
    """Per channel, scan density -> straightened density, as tables over an even density grid."""
    tables: np.ndarray     # (3, n) float32
    slopes: np.ndarray     # (3,) the gradient of each channel's straight section: density per unit of log exposure
    strength: float        # 1 with a sampled film base, UNSURE_BASE with an estimated one: how far the table moves a density from where it was
    profile: str

    def print_positive(self, straight: np.ndarray, floor: float, ceil: float, channel: int) -> np.ndarray:
        """The picture a print would make from one channel's straightened density: the ceiling is white and the floor black in light (exposure), not in density, and the result is
        display encoded. This is the same reconstruction the curve-informed inversion makes (exposure over a white reference, a black point, the display encoding last), so a scene
        keeps the tones the film recorded instead of being spread evenly over log exposure."""
        s = float(self.slopes[channel])
        e = np.power(10.0, (np.asarray(straight, dtype=np.float64) - ceil) / s)
        e_floor = 10.0 ** ((floor - ceil) / s)
        return inversion.srgb_oetf(np.clip((e - e_floor) / max(1.0 - e_floor, 1e-6), 0.0, 1.0)).astype(np.float32)

    def __call__(self, density: np.ndarray, channel: int) -> np.ndarray:
        """One channel's density (any shape) straightened."""
        d = np.asarray(density, dtype=np.float32)
        t = self.tables[channel]
        return np.interp(d, np.arange(t.size, dtype=np.float32) * np.float32(GRID_STEP), t).astype(np.float32)

    def remap(self, density: np.ndarray) -> np.ndarray:
        """An H x W x 3 density image straightened channel by channel."""
        out = np.empty(density.shape, dtype=np.float32)
        for c in range(3):
            out[..., c] = self(density[..., c], c)
        return out

    def values(self, values) -> np.ndarray:
        """Three per-channel densities (a floor, a ceiling, a film base) straightened."""
        return np.array([float(self(np.float32(v), c)) for c, v in enumerate(values)], dtype=np.float32)


def _straight_table(curve, support: tuple[float, float], base: float, grid: np.ndarray) -> tuple[np.ndarray, float]:
    """The straightened density at each grid density, for one channel, and the slope of the line: the exposure each density implies through the curve (clamped to the measured range),
    laid on the straight line through the curve's steepest point; densities beyond the measured range go on at a slope of one, so tones keep their order."""
    lo, hi = support
    xs = np.linspace(lo, hi, CURVE_POINTS)
    slope = np.asarray(curve.derivative(xs), dtype=np.float64)
    peak = int(np.argmax(slope))
    x_p, v_p, s_p = float(xs[peak]), float(np.asarray(curve(xs[peak:peak + 1]))[0]), max(float(slope[peak]), 1e-3)
    net = grid.astype(np.float64) - base
    x, _status = invert_curve(curve, net, lo, hi)
    line = v_p + s_p * (x - x_p)
    values = np.maximum.accumulate(np.asarray(curve(xs), dtype=np.float64))
    line = line + np.where(net < values[0], net - values[0], 0.0) + np.where(net > values[-1], net - values[-1], 0.0)
    return np.maximum.accumulate(base + line), s_p


def build(models: dict, base, sampled: bool, profile: str = "") -> FilmCurve:
    """The table for a profile's per-channel models (inversion.channel_models), the film base density of each channel and whether that base was sampled (an estimated base only
    moves the densities by UNSURE_BASE of the way: the same trust the NegPy Conversion gives its film curve)."""
    grid = np.arange(0.0, GRID_MAX, GRID_STEP, dtype=np.float64)
    strength = 1.0 if sampled else UNSURE_BASE
    tables = np.empty((3, grid.size), dtype=np.float32)
    slopes = np.empty(3, dtype=np.float32)
    for c, ch in enumerate("RGB"):
        full, slopes[c] = _straight_table(models[ch].curve, models[ch].support, float(base[c]), grid)
        tables[c] = (grid + strength * (full - grid)).astype(np.float32)
    return FilmCurve(tables, slopes, strength, profile)


# --- the profiles, loaded once per file version -------------------------------------------------------------------------------------------------------------------------

_MODELS: dict[tuple, dict | None] = {}


def profile_stamp(profile_id: str) -> tuple | None:
    """Which version of a profile's file is there (its path and modified time), or None when there is no such file: what a cached table is keyed on."""
    if not profile_id or os.sep in profile_id or "/" in profile_id or profile_id.startswith("."):
        return None
    path = os.path.join(fpmod.profiles_dir(app_data_dir()), profile_id + ".json")
    try:
        return (path, os.stat(path).st_mtime_ns)
    except OSError:
        return None


def profile_models(profile_id: str) -> dict | None:
    """The per-channel models of a film profile in the data folder, or None when there is no such profile or it cannot drive a conversion."""
    stamp = profile_stamp(profile_id)
    if stamp is None:
        return None
    if stamp not in _MODELS:
        try:
            _MODELS[stamp] = inversion.channel_models(fpmod.ProfileStore(fpmod.profiles_dir(app_data_dir())).load(profile_id))
        except (fpmod.ProfileError, inversion.InversionError, OSError, ValueError):
            _MODELS[stamp] = None
    return _MODELS[stamp]
