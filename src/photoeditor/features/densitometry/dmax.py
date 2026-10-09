"""Maximum useful density (Dmax) per channel, and whether the film or the scan set the limit - numpy only, no Qt/UI imports."""

from dataclasses import dataclass

import numpy as np

from .linear import density_above_base

DEFAULT_PERCENTILE = 99.9
SYSTEM_MARGIN = 0.15
MAX_FLOOR_FRACTION = 0.001


@dataclass(frozen=True)
class DmaxResult:
    """Density above the film base at the dense end, per channel; `limited` marks channels where the camera set-up, not the film, set the value."""

    value: tuple[float, float, float]
    system_limit: tuple[float, float, float]
    limited: tuple[bool, bool, bool]
    floor_fraction: tuple[float, float, float]
    percentile: float


def system_limit(v_base, floor) -> tuple[float, float, float]:
    """The highest density above base the set-up can register above its noise floor: log10(v_base / v_floor)."""
    base, fl = np.asarray(v_base, dtype=np.float64), np.asarray(floor, dtype=np.float64)
    fl = np.maximum(fl, 1e-12)
    return tuple(float(x) for x in np.log10(base / fl))


def estimate_dmax(v: np.ndarray, v_base, floor, percentile: float = DEFAULT_PERCENTILE, margin: float = SYSTEM_MARGIN,
                  max_floor_fraction: float = MAX_FLOOR_FRACTION) -> DmaxResult:
    """A robust high percentile of the density above base (never the single darkest pixel), judged against what the camera could register.
    Where the value comes within `margin` of the system limit, or too many pixels sit at the floor, it is a lower bound set by the scan."""
    px = np.asarray(v, dtype=np.float64).reshape(-1, 3)
    fl = np.maximum(np.asarray(floor, dtype=np.float64), 1e-12)
    dd = density_above_base(px, v_base, fl)
    values = np.percentile(dd, percentile, axis=0)
    sys_lim = np.asarray(system_limit(v_base, fl))
    at_floor = (px <= fl).mean(axis=0)
    limited = (values >= sys_lim - margin) | (at_floor > max_floor_fraction)
    capped = np.where(limited, np.minimum(values, sys_lim), values)
    return DmaxResult(
        tuple(float(x) for x in capped), tuple(float(x) for x in sys_lim), tuple(bool(x) for x in limited),
        tuple(float(x) for x in at_floor), float(percentile),
    )
