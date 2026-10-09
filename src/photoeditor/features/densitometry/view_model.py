"""Everything the sensitometry display needs, computed without Qt: measured points with their uncertainty, the fitted curve with its confidence band
and the range the data actually support, residuals, the gradient profile, quality, and plain-language text (docs/sensitometry-tier2-design.md, sections 4, 5, 9).
Numpy only; the widgets only draw what this returns.
"""

from dataclasses import dataclass, field

import numpy as np

from . import fit, gradient
from .film_profile import ChannelCurve, FilmProfile

BAND_POINTS = 241


@dataclass(frozen=True)
class ChannelView:
    channel: str
    x: np.ndarray
    y: np.ndarray
    sigma: np.ndarray
    used: np.ndarray
    grid: np.ndarray
    curve: np.ndarray
    band: np.ndarray | None
    residual: np.ndarray
    gradient_grid: np.ndarray
    gradient: np.ndarray
    support: tuple[float, float]
    representation: str
    quality: str
    reasons: tuple[str, ...]
    rms: float
    max_abs: float
    loo_rms: float | None
    gamma: float | None
    gamma_interval: tuple[float, float] | None
    average: dict | None
    iso6: dict
    regions: dict
    notes: tuple[str, ...] = field(default_factory=tuple)


def channel_view(channel: str, cc: ChannelCurve, pad: float = 0.3) -> ChannelView:
    """The measured points and the chosen representation of one channel, with the range the measurements support marked and the curve drawn a little
    beyond it (the drawing outside the support is extrapolation and the widget must show it as such)."""
    curve = cc.curve()
    x = np.asarray(cc.x, dtype=np.float64)
    y = np.asarray(cc.y, dtype=np.float64)
    sigma = np.asarray(cc.sigma, dtype=np.float64)
    used = np.asarray(cc.used, dtype=bool)
    support = cc.supported()
    grid = np.linspace(support[0] - pad, support[1] + pad, BAND_POINTS)
    values = np.asarray(curve(grid), dtype=np.float64)
    fitrec = cc.fits.get(cc.chosen)
    band = None
    quality, reasons = ("interpolated", ()) if fitrec is None else (fitrec["quality"], tuple(fitrec["reasons"]))
    loo = None if fitrec is None else float(fitrec["loo_rms"])
    if fitrec is not None and cc.chosen in fit.MODELS:
        # the covariance is not stored, so the band is rebuilt from the stored standard errors: a conservative independent-parameter estimate
        band = _band_from_errors(cc.chosen, fitrec, grid)
    resid = y - np.asarray(curve(x), dtype=np.float64)
    g_grid = np.linspace(support[0], support[1], BAND_POINTS)
    g = gradient.local_gradient(curve, g_grid)
    gm = gradient.gamma(curve, support)
    avg = gradient.chord_gradient(curve, *_default_chord(support, curve), support=support) if _default_chord(support, curve) else None
    return ChannelView(
        channel, x, y, sigma, used, grid, values, band, resid, g_grid, g, support, cc.chosen, quality, reasons, float(np.sqrt(np.mean(resid[used] ** 2))) if used.any() else float("nan"),
        float(np.abs(resid[used]).max()) if used.any() else float("nan"), loo, gm.gamma if gm else None, gm.interval if gm else None, avg,
        gradient.iso6_geometry(curve, support), gradient.regions(curve, support), tuple(cc.notes),
    )


def _default_chord(support, curve):
    """The chord from the middle third of the measured range's start to its end: a plain 'average gradient over what was measured' with its interval stated."""
    lo, hi = support
    if hi - lo < 0.3:
        return None
    return lo + (hi - lo) / 3.0, hi - (hi - lo) / 6.0


def _band_from_errors(name: str, rec: dict, grid: np.ndarray, z: float = 1.96) -> np.ndarray | None:
    """Half-width of a rough confidence band from the stored parameter standard errors (each parameter varied alone, then added in quadrature)."""
    cls = fit.MODELS[name]
    params = rec["params"]
    errs = rec["std_errors"]
    if not all(np.isfinite(list(errs.values()))):
        return None
    base = cls(**params)(grid)
    total = np.zeros_like(grid)
    for k, se in errs.items():
        if se <= 0:
            continue
        up = dict(params)
        up[k] = params[k] + se
        total += (cls(**up)(grid) - base) ** 2
    return z * np.sqrt(total)


def quality_text(view: ChannelView) -> str:
    if view.representation == "pchip" or view.quality == "interpolated":
        head = "Shown as an interpolated curve through the measured points (no shape assumed)."
    else:
        head = f"Fit: {view.representation}, quality {view.quality}."
    parts = [head, f"RMS residual {view.rms:.3f} density, largest {view.max_abs:.3f}."]
    if view.loo_rms is not None:
        parts.append(f"Leave-one-out error {view.loo_rms:.3f}.")
    parts += list(view.reasons)
    return " ".join(parts)


def profile_lines(profile: FilmProfile) -> list[str]:
    """A plain summary of a profile for lists and the Sensitometry panel."""
    from .film_profile import KIND_LABELS, LIMIT_REMINDER

    lines = [f"{profile.name}: {KIND_LABELS[profile.kind]}", profile.identity_text()]
    cal = profile.calibration or {}
    if cal.get("date"):
        lines.append(f"Calibrated {cal['date']}")
    scale = {cc.scale for cc in profile.curves.values()}
    lines.append("Exposure on an absolute scale (lux-seconds)." if scale == {"absolute"} else "Exposure on a relative scale: speed cannot be derived.")
    lines.append(LIMIT_REMINDER)
    return lines


def guidance_for(profile: FilmProfile):
    """Shadow / midtone / highlight guidance from the green (or grey) curve of a profile, or None."""
    cc = profile.curves.get("G") or profile.curves.get("K")
    if cc is None:
        return None
    return gradient.guidance(cc.curve(), cc.supported())
