"""From sampled patches of a developed exposure strip to a measured characteristic curve and a film profile (docs/sensitometry-tier2-design.md, sections 2.1, 3, 4).

The exposures come from the step tablet the film was exposed through: log H_i = log H_0 - D_i (type Ib sensitometer, SMPTE RP 14). They are relative
unless the user supplies log H_0. Without confirmed known exposures nothing is built: a measured curve is never made from arbitrary image samples.
Numpy only, no Qt/UI imports.
"""

import math
from dataclasses import dataclass, field

import numpy as np

from . import fit
from .film_profile import ChannelCurve, FilmProfile, curve_from_report, new_profile, now_iso
from .target import PatchSample, StepTarget, order_violations, tolerance_warnings

MIN_USED = 6
MIN_SIGMA_D = 0.005
SYSTEMATIC_SHARE = 0.25
EXPOSURE_METHODS = (
    "Contact exposure through the tablet (sensitometer)",
    "Contact exposure, home-made light source",
    "Camera photograph of a lit tablet (flare is mixed in)",
)


class CharacterizationError(ValueError):
    """The strip cannot be turned into a curve, with the reason."""


@dataclass(frozen=True)
class FilmFit:
    x: np.ndarray
    delta_density: np.ndarray
    sigma: np.ndarray
    used: np.ndarray
    reports: dict
    scale: str
    warnings: tuple[str, ...] = field(default_factory=tuple)


def patch_sigma(sample: PatchSample, v_base, floor) -> np.ndarray:
    """Density uncertainty of one patch per channel: the random error of its median (spread over the square root of the pixels), a systematic part of the
    spread (uneven lighting does not average away), and the noise floor's effect on a density from `v`."""
    v = np.maximum(np.asarray(sample.v, dtype=np.float64), 1e-9)
    n = max(sample.pixels, 1)
    spread = np.asarray(sample.spread, dtype=np.float64)
    noise = np.asarray(floor, dtype=np.float64) / (v * math.log(10.0))
    return np.maximum(np.sqrt(spread ** 2 / n + (SYSTEMATIC_SHARE * spread) ** 2 + noise ** 2), MIN_SIGMA_D)


def characterize_film(tablet: StepTarget, samples: list[PatchSample], v_base, floor, confirmed: bool, log_h0: float | None = None,
                      used=None) -> FilmFit:
    """Fit the three channels of an exposure strip. `confirmed` must be True: the film was exposed through the tablet and the exposure steps are known.
    `used` (one bool per patch) lets the user leave patches out; invalid patches are left out in any case."""
    if not confirmed:
        raise CharacterizationError("A characteristic curve needs known exposures. Without them these patches are only densities in an image, and EFAS will not "
                                    "present them as a measured curve.")
    d_tab = tablet.values()
    if len(samples) != d_tab.size:
        raise CharacterizationError("The number of sampled patches must match the number of tablet steps.")
    base = np.asarray(v_base, dtype=np.float64)
    if np.any(base <= 0):
        raise CharacterizationError("The film base value must be positive: sample the film base first.")
    keep = np.array([s.valid() for s in samples], dtype=bool)
    if used is not None:
        keep &= np.asarray(used, dtype=bool)
    if keep.sum() < MIN_USED:
        raise CharacterizationError(f"At least {MIN_USED} usable patches are needed; {int(keep.sum())} remain after leaving out invalid ones.")
    v = np.array([s.v for s in samples], dtype=np.float64)
    fl = np.broadcast_to(np.asarray(floor, dtype=np.float64), (3,))
    dd = np.log10(base) - np.log10(np.maximum(v, np.maximum(fl, 1e-12)))
    sigma = np.stack([patch_sigma(s, base, fl) for s in samples])
    scale = "absolute" if log_h0 is not None else "relative"
    x = (float(log_h0) if log_h0 is not None else 0.0) - d_tab
    warnings = []
    if tablet.actual():
        warnings += tolerance_warnings(d_tab, tablet.increment)
    else:
        warnings.append("The tablet's nominal densities were used. Real tablets differ from nominal, and RP 14 asks for the calibrated values: cumulative errors "
                        "can bend the curve.")
    for c, ch in enumerate("RGB"):
        bad = order_violations(v[keep, c], x[keep])
        if bad:
            warnings.append(f"In {ch}, some patches do not get denser as the exposure rises: check the patch order and that each box sits on its own step.")
    reports = {}
    for c, ch in enumerate("RGB"):
        reports[ch] = fit.fit_curve(x[keep], dd[keep, c], sigma=sigma[keep, c])
    return FilmFit(x, dd, sigma, keep, reports, scale, tuple(warnings))


def build_profile(name: str, film: FilmFit, v_base, tablet: StepTarget, film_stock: str = "", process: str = "", notes: str = "", exposure: dict | None = None,
                  processing: str = "", scan: dict | None = None, light_source: str = "", dmin_rel=None) -> FilmProfile:
    """Store a characterisation as a *measured* profile with everything that says where it came from."""
    keep = film.used
    curves = {}
    for c, ch in enumerate("RGB"):
        rep = film.reports[ch]
        cc = curve_from_report(rep, scale=film.scale, unit="lux-seconds" if film.scale == "absolute" else "")
        cc.x, cc.y, cc.sigma = [float(v) for v in film.x], [float(v) for v in film.delta_density[:, c]], [float(v) for v in film.sigma[:, c]]
        cc.used = [bool(u) for u in keep]
        curves[ch] = cc
    p = new_profile(name, "measured", curves, film_stock=film_stock, process=process, notes=notes)
    p.base = {"v_base": [float(b) for b in v_base], "dmin_camera_relative": [float(-math.log10(b)) for b in v_base] if dmin_rel is None else list(dmin_rel)}
    p.calibration = {
        "target_type": "step tablet exposure of film (type Ib intensity scale)",
        "tablet": {"name": tablet.name, "steps": tablet.steps, "densities": [float(d) for d in tablet.values()], "densities_are_actual": tablet.actual(),
                   "nominal_increment": tablet.increment},
        "exposure": exposure or {}, "processing": processing, "scan": scan or {}, "date": now_iso()[:10], "light_source": light_source,
        "patches_used": int(keep.sum()), "patches_total": int(keep.size), "warnings": list(film.warnings),
    }
    p.conditions = {"densitometry": "camera-band density (not Status M)", "illuminant": light_source, "exposure_scale": film.scale}
    supports = {ch: list(curves[ch].supported()) for ch in "RGB"}
    p.validity = {"support_log_exposure": supports, "density_range": [float(np.min(film.delta_density[keep])), float(np.max(film.delta_density[keep]))]}
    qualities = {}
    for ch in "RGB":
        rec = curves[ch].fits.get(curves[ch].chosen)
        qualities[ch] = rec["quality"] if rec else "interpolated"
    worst = "poor" if "poor" in qualities.values() else ("fair" if "fair" in qualities.values() else ("interpolated" if "interpolated" in qualities.values() else "good"))
    p.uncertainty = {"quality": qualities, "overall": worst, "sigma_assumed": any(r.samples.sigma_assumed for r in film.reports.values())}
    return p
