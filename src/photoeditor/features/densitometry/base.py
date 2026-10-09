"""Film-base density (Dmin) per channel, measured from a sampled patch or estimated from the picture - numpy only, no Qt/UI imports."""

from dataclasses import dataclass

import numpy as np

from .linear import optical_density

ESTIMATE_PERCENTILE = 1.0
MAX_PATCH_SPREAD = 0.08
MASK_ORDER_TOLERANCE = 0.02


@dataclass(frozen=True)
class BaseSample:
    """The film base in linear units: v_base per channel, with how it was obtained and how steady it was."""

    v: tuple[float, float, float]
    measured: bool
    pixels: int
    spread: tuple[float, float, float]
    near_floor: float
    saturated: float
    warnings: tuple[str, ...] = ()

    def dmin_rel(self, floor=0.0) -> tuple[float, float, float]:
        d = optical_density(np.asarray(self.v), floor)
        return tuple(float(x) for x in d)


def _channels(patch: np.ndarray) -> np.ndarray:
    return np.asarray(patch, dtype=np.float64).reshape(-1, 3)


def measure_base(patch: np.ndarray, floor=(0.0, 0.0, 0.0)) -> BaseSample:
    """The film base from a user-picked patch: per-channel median of the linear value (steadier than any one pixel, which is grain or dust)."""
    px = _channels(patch)
    if px.shape[0] == 0:
        raise ValueError("the film-base patch is empty")
    med = np.median(px, axis=0)
    dens = optical_density(px, np.asarray(floor))
    d_med = optical_density(med, np.asarray(floor))
    mad = np.median(np.abs(dens - d_med), axis=0)
    fl = np.asarray(floor, dtype=np.float64)
    near_floor = float((px <= fl * 1.5).any(axis=1).mean()) if fl.any() else 0.0
    saturated = float((px >= 0.999).any(axis=1).mean())
    warnings = []
    if np.any(med <= fl * 1.5) and fl.any():
        warnings.append("The sampled patch is almost as dark as the noise floor, so it is probably not film base.")
    if saturated > 0.05:
        warnings.append("Part of the sampled patch is clipped white. Expose the scan so the film base is below pure white.")
    if float(mad.max()) > MAX_PATCH_SPREAD:
        warnings.append("The sampled patch is not uniform (grain, dust or picture content). Pick a smaller, cleaner area of the clear border.")
    if px.shape[0] < 25:
        warnings.append("Very few pixels were sampled; pick a larger area of the border for a steadier value.")
    return BaseSample(tuple(float(x) for x in med), True, int(px.shape[0]), tuple(float(x) for x in mad), near_floor, saturated, tuple(warnings))


def estimate_base(v: np.ndarray, floor=(0.0, 0.0, 0.0), percentile: float = ESTIMATE_PERCENTILE) -> BaseSample:
    """A guess at the film base when none was sampled: the thinnest density per channel in the picture. Always marked as not measured."""
    px = _channels(v)
    dens = optical_density(px, np.asarray(floor))
    d_low = np.percentile(dens, percentile, axis=0)
    v_base = tuple(float(10.0 ** (-d)) for d in d_low)
    warnings = ("Film base estimated from the thinnest part of the picture. Sample the clear film border for a measured value.",)
    return BaseSample(v_base, False, int(px.shape[0]), (0.0, 0.0, 0.0), 0.0, float((px >= 0.999).any(axis=1).mean()), warnings)


def from_reference(v, pixels: int = 0) -> BaseSample:
    """A film base stored earlier (linear values for the roll), back as a BaseSample."""
    return BaseSample(tuple(float(x) for x in v), True, int(pixels), (0.0, 0.0, 0.0), 0.0, 0.0, ())


def mask_order_check(dmin_abs: tuple[float, float, float]) -> str:
    """For colour negative the film base is expected to have Dmin(B) >= Dmin(G) >= Dmin(R). Only meaningful on absolute densities."""
    r, g, b = dmin_abs
    if b + MASK_ORDER_TOLERANCE >= g and g + MASK_ORDER_TOLERANCE >= r:
        return ""
    return ("The film-base densities are not in the usual orange-mask order (blue highest, red lowest). "
            "This can be a black-and-white film, a sample that is not film base, or an unusual backlight.")
