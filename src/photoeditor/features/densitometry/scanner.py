"""The camera as a measuring instrument: calibration against a step tablet, flare correction, and a sensor linearity test
(docs/sensitometry-tier2-design.md, sections 2.3 and 8). Numpy only, no Qt/UI imports.

Model: v = k * T + f with T = 10^-D the tablet's transmittance. k is the gain (backlight, exposure, sensor), f the offset from flare and black-level
error. The flare fraction phi = f / k is a ratio, so it carries from one exposure level to another for the same set-up.
"""

from dataclasses import dataclass

import numpy as np

REL_ERROR = 0.003
GOOD_RMS, FAIR_RMS = 0.02, 0.05
SIGNIFICANT = 2.0
NOISE_SIGMAS = 3.0


class CalibrationError(ValueError):
    """The calibration data cannot be used."""


@dataclass(frozen=True)
class ChannelCalibration:
    k: float
    f: float
    k_se: float
    f_se: float
    flare_fraction: float
    flare_fraction_se: float
    rms_density: float
    max_density_error: float
    usable_max_density: float
    limit: str
    used: int
    quality: str
    reasons: tuple[str, ...]


def _weighted_line(T: np.ndarray, v: np.ndarray, sigma: np.ndarray):
    """Weighted least squares for v = k T + f. Returns (k, f, covariance, chi2_red)."""
    w = 1.0 / sigma ** 2
    A = np.stack([T, np.ones_like(T)], axis=1)
    AtW = A.T * w
    cov = np.linalg.inv(AtW @ A)
    k, f = cov @ (AtW @ v)
    resid = (v - (k * T + f)) / sigma
    dof = max(T.size - 2, 1)
    chi2_red = float(resid @ resid) / dof
    return float(k), float(f), cov * max(1.0, chi2_red), chi2_red


def calibrate_channel(densities: np.ndarray, v: np.ndarray, floor: float, used: np.ndarray | None = None) -> ChannelCalibration:
    """Fit one channel. `used` selects the patches to use (clipped or invalid ones left out). Point uncertainty combines the noise floor and a
    small relative term for light and shutter stability."""
    d = np.asarray(densities, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    keep = np.ones(d.size, dtype=bool) if used is None else np.asarray(used, dtype=bool)
    if keep.sum() < 4:
        raise CalibrationError("at least 4 usable steps are needed to fit gain and offset")
    T = 10.0 ** -d[keep]
    sigma = np.sqrt(max(floor, 1e-9) ** 2 + (REL_ERROR * v[keep]) ** 2)
    k, f, cov, chi2_red = _weighted_line(T, v[keep], sigma)
    if k <= 0:
        raise CalibrationError("the fitted gain is not positive: the signal does not fall as the tablet density rises")
    k_se, f_se = float(np.sqrt(cov[0, 0])), float(np.sqrt(max(cov[1, 1], 0.0)))
    phi = f / k
    if abs(f) > 0:
        phi_se = abs(phi) * float(np.sqrt(max(f_se ** 2 / f ** 2 + k_se ** 2 / k ** 2 - 2.0 * cov[0, 1] / (f * k), 0.0)))
    else:
        phi_se = f_se / k
    resid_d = -np.log10(np.clip((v[keep] - f) / k, 1e-12, None)) - d[keep]
    reliable = (v[keep] - f) > NOISE_SIGMAS * sigma
    rms = float(np.sqrt(np.mean(resid_d[reliable] ** 2))) if reliable.any() else float("inf")
    worst = float(np.max(np.abs(resid_d[reliable]))) if reliable.any() else float("inf")
    flare_floor, noise_floor = max(f, 0.0), NOISE_SIGMAS * max(floor, 1e-9)
    if flare_floor >= noise_floor and f > SIGNIFICANT * f_se:
        limit, level = "flare", flare_floor
    else:
        limit, level = "noise", noise_floor
    usable = float(-np.log10(max(level, 1e-12) / k))
    reasons = []
    if f < -SIGNIFICANT * f_se:
        reasons.append("the offset is negative: a black-level error or an uneven backlight is likely")
    if f_se > 0 and abs(f) <= SIGNIFICANT * f_se:
        reasons.append("the flare offset is not significantly different from zero")
    if chi2_red > 5.0:
        reasons.append("the points do not follow the straight-line model within their uncertainty")
    quality = "good" if rms <= GOOD_RMS and chi2_red <= 2.0 else ("fair" if rms <= FAIR_RMS and chi2_red <= 5.0 else "poor")
    return ChannelCalibration(k, f, k_se, f_se, phi, phi_se, rms, worst, usable, limit, int(keep.sum()), quality, tuple(reasons))


def calibrate(densities, v_patches: np.ndarray, floor, used=None) -> dict[str, ChannelCalibration]:
    """Calibrate all three channels from a tablet's patches. `v_patches` is (steps, 3) linear values."""
    v = np.asarray(v_patches, dtype=np.float64)
    if v.ndim != 2 or v.shape[1] != 3 or v.shape[0] != len(densities):
        raise CalibrationError("give one R, G, B value per tablet step")
    fl = np.broadcast_to(np.asarray(floor, dtype=np.float64), (3,))
    if used is None:
        masks = [None, None, None]
    else:
        u = np.asarray(used, dtype=bool)
        masks = [u[:, i] if u.ndim == 2 else u for i in range(3)]
    return {c: calibrate_channel(np.asarray(densities), v[:, i], float(fl[i]), masks[i]) for i, c in enumerate("RGB")}


def corrected_density(v, k: float, f: float) -> np.ndarray:
    """Density with the fitted offset removed: -log10((v - f) / k)."""
    return -np.log10(np.clip((np.asarray(v, dtype=np.float64) - f) / k, 1e-12, None))


def correct_flare(v, v_clear, phi: float) -> np.ndarray:
    """Transmittance with a calibrated flare fraction removed: T = (1 + phi) * v / v_clear - phi. v_clear is the same backlight with no film."""
    if not 0.0 <= phi < 1.0:
        raise CalibrationError("the flare fraction must be from 0 up to (not including) 1")
    return (1.0 + phi) * np.asarray(v, dtype=np.float64) / np.asarray(v_clear, dtype=np.float64) - phi


@dataclass(frozen=True)
class LinearityResult:
    error_percent: float
    max_positive_percent: float
    max_negative_percent: float
    slope: float
    offset: float
    used: int
    range_fraction: tuple[float, float]
    verdict: str


def linearity_error(times, signal, saturation: float = 1.0, low: float = 0.05, high: float = 0.95) -> LinearityResult:
    """Signal against exposure time at constant light. A straight line is fitted over the points between `low` and `high` of saturation; each point's
    deviation from it is expressed in percent of the fitted value. The result is the mean of the largest positive deviation and the magnitude of the
    largest negative one, after the EMVA 1288 idea of linearity error. EMVA 1288's exact normalisation was not verified, so this is EFAS's own
    definition and is labelled as such."""
    t = np.asarray(times, dtype=np.float64)
    y = np.asarray(signal, dtype=np.float64) / float(saturation)
    if t.size != y.size or t.size < 4:
        raise CalibrationError("a linearity test needs at least 4 exposures")
    if (t <= 0).any() or not np.isfinite(y).all():
        raise CalibrationError("exposure times must be positive and the signals numbers")
    sel = (y >= low) & (y <= high)
    if sel.sum() < 4:
        raise CalibrationError(f"at least 4 exposures must fall between {low:.0%} and {high:.0%} of saturation")
    slope, offset = np.polyfit(t[sel], y[sel], 1)
    fitted = slope * t[sel] + offset
    dev = (y[sel] - fitted) / fitted * 100.0
    pos, neg = float(max(dev.max(), 0.0)), float(min(dev.min(), 0.0))
    err = (pos + abs(neg)) / 2.0
    verdict = "good" if err < 1.0 else ("fair" if err < 3.0 else "poor")
    return LinearityResult(float(err), pos, neg, float(slope), float(offset), int(sel.sum()), (float(y[sel].min()), float(y[sel].max())), verdict)
