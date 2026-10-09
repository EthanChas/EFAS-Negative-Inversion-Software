"""The Hurter-Driffield (characteristic) curve: density against log exposure. A parametric model, and the analysis of curve data.

A photograph has densities but not the exposures that produced them, so nothing here builds a curve from a photograph. Curve data
comes from the user (a measured step tablet, a digitised manufacturer curve) or from the model, and each is labelled as such.
Numpy only, no Qt/UI imports.
"""

from dataclasses import dataclass

import numpy as np

DEFAULT_GRADIENT_TOE_OFFSET = 0.10
DEFAULT_GRADIENT_SPAN = 1.30
STRAIGHT_FRACTION = 0.9


def softplus(z):
    """ln(1 + e^z), computed without overflow."""
    return np.logaddexp(0.0, z)


@dataclass(frozen=True)
class ModelCurve:
    """A toe / straight-line / shoulder curve. Not measured: it is for exploring how range, gamma and the knees interact."""

    dmin: float = 0.2
    dmax: float = 2.5
    gamma: float = 0.6
    x0: float = -1.5
    d0: float = 1.0
    toe_sharpness: float = 6.0
    shoulder_sharpness: float = 3.0

    def density(self, log_exposure) -> np.ndarray:
        """Straight line v = d0 + gamma (x - x0), then a toe at Dmin and a shoulder at Dmax, each a softplus knee."""
        x = np.asarray(log_exposure, dtype=np.float64)
        v = self.d0 + self.gamma * (x - self.x0)
        v1 = self.dmin + softplus(self.toe_sharpness * (v - self.dmin)) / self.toe_sharpness
        return self.dmax - softplus(self.shoulder_sharpness * (self.dmax - v1)) / self.shoulder_sharpness


def sample(curve: ModelCurve, lo: float = -4.0, hi: float = 1.0, n: int = 501) -> tuple[np.ndarray, np.ndarray]:
    x = np.linspace(lo, hi, n)
    return x, curve.density(x)


def log_exposure_at(log_exposure: np.ndarray, density: np.ndarray, target) -> np.ndarray:
    """The log exposure at which the curve reaches `target` density (NaN outside the curve's range). Needs a rising curve."""
    x = np.asarray(log_exposure, dtype=np.float64)
    d = np.maximum.accumulate(np.asarray(density, dtype=np.float64))
    t = np.asarray(target, dtype=np.float64)
    out = np.interp(t, d, x)
    return np.where((t < d[0]) | (t > d[-1]), np.nan, out)


@dataclass(frozen=True)
class CurveAnalysis:
    dmin: float
    dmax: float
    gamma: float | None
    straight: tuple[float, float] | None
    average_gradient: float | None
    gradient_points: tuple[tuple[float, float], tuple[float, float]] | None


def straight_line(log_exposure: np.ndarray, density: np.ndarray, fraction: float = STRAIGHT_FRACTION):
    """The straight-line portion: the longest run where the local slope stays within `fraction` of its steepest value. Returns (gamma, (x_lo, x_hi))."""
    x = np.asarray(log_exposure, dtype=np.float64)
    d = np.asarray(density, dtype=np.float64)
    if x.size < 4:
        return None, None
    g = np.gradient(d, x)
    peak = float(np.max(g))
    if not np.isfinite(peak) or peak <= 0:
        return None, None
    ok = g >= fraction * peak
    best, start = (0, 0), None
    for i, flag in enumerate(np.append(ok, False)):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    lo, hi = best
    if hi - lo < 3:
        return None, None
    slope = float(np.polyfit(x[lo:hi], d[lo:hi], 1)[0])
    return slope, (float(x[lo]), float(x[hi - 1]))


def average_gradient(log_exposure: np.ndarray, density: np.ndarray, dmin: float,
                     toe_offset: float = DEFAULT_GRADIENT_TOE_OFFSET, span: float = DEFAULT_GRADIENT_SPAN):
    """The slope of the chord from the point at Dmin + toe_offset to the point `span` log-exposure units higher. The end points are conventions
    (configurable), not a claim about any standard. Returns (gradient, ((x1, d1), (x2, d2))) or (None, None) when the curve does not reach."""
    x = np.asarray(log_exposure, dtype=np.float64)
    d = np.asarray(density, dtype=np.float64)
    x1 = float(log_exposure_at(x, d, dmin + toe_offset))
    if not np.isfinite(x1) or x1 + span > x[-1]:
        return None, None
    x2 = x1 + span
    d1, d2 = float(np.interp(x1, x, d)), float(np.interp(x2, x, d))
    return (d2 - d1) / span, ((x1, d1), (x2, d2))


def analyse_curve(log_exposure, density, toe_offset: float = DEFAULT_GRADIENT_TOE_OFFSET, span: float = DEFAULT_GRADIENT_SPAN) -> CurveAnalysis:
    x = np.asarray(log_exposure, dtype=np.float64)
    d = np.asarray(density, dtype=np.float64)
    order = np.argsort(x)
    x, d = x[order], d[order]
    dmin, dmax = float(d.min()), float(d.max())
    gamma, straight = straight_line(x, d)
    avg, pts = average_gradient(x, d, dmin, toe_offset, span)
    return CurveAnalysis(dmin, dmax, gamma, straight, avg, pts)
