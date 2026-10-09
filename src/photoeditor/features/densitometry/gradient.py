"""Gradients of a characteristic curve: local gradient, chord (average) gradient over a stated interval, gamma, the regions of the curve, the ISO 6
speed-criterion geometry, and plain-language guidance (docs/sensitometry-tier2-design.md, sections 2.5 and 5). Numpy only, no Qt/UI imports.

Gradient is density per unit of log10 exposure, so it is dimensionless. Every figure comes with the exposure interval it was measured over.
`curve` is any object that is callable and has a derivative: a Pchip or a fitted model from fit.py.
"""

from dataclasses import dataclass

import numpy as np

ISO6_TOE_OFFSET = 0.10
ISO6_SPAN = 1.30
ISO6_RISE = 0.80
STRAIGHT_FRACTION = 0.90
GRID = 2001
HIGH_RATIO, LOW_RATIO = 0.75, 0.40


def local_gradient(curve, x) -> np.ndarray:
    """dD / d log10 H at x."""
    return np.asarray(curve.derivative(np.asarray(x, dtype=np.float64)), dtype=np.float64)


def _grid(support: tuple[float, float], n: int = GRID) -> np.ndarray:
    return np.linspace(support[0], support[1], n)


def chord_gradient(curve, x1: float, x2: float, support: tuple[float, float] | None = None):
    """The slope of the straight line joining the curve at x1 and x2, and the interval it covers. `ok` is False when the interval leaves the supported range."""
    if x2 <= x1:
        raise ValueError("the interval must have x2 above x1")
    d1, d2 = float(curve(x1)), float(curve(x2))
    ok = support is None or (support[0] - 1e-9 <= x1 and x2 <= support[1] + 1e-9)
    return {"gradient": (d2 - d1) / (x2 - x1), "interval": (float(x1), float(x2)), "density": (d1, d2), "supported": bool(ok)}


@dataclass(frozen=True)
class GammaResult:
    gamma: float
    interval: tuple[float, float]
    fraction: float
    at_edge: bool


def gamma(curve, support: tuple[float, float], fraction: float = STRAIGHT_FRACTION) -> GammaResult | None:
    """Gamma: the peak local gradient over the supported range, and the contiguous exposure interval around it where the gradient stays within
    `fraction` of the peak (the straight-line portion). `at_edge` is True when that interval touches the end of the measurements, so the true straight
    portion may be longer than what was measured."""
    x = _grid(support)
    g = local_gradient(curve, x)
    if not np.isfinite(g).all() or g.max() <= 0:
        return None
    i = int(np.argmax(g))
    keep = g >= fraction * g[i]
    lo = hi = i
    while lo > 0 and keep[lo - 1]:
        lo -= 1
    while hi < x.size - 1 and keep[hi + 1]:
        hi += 1
    return GammaResult(float(g[lo:hi + 1].mean()), (float(x[lo]), float(x[hi])), float(fraction), bool(lo == 0 or hi == x.size - 1))


def regions(curve, support: tuple[float, float], fraction: float = STRAIGHT_FRACTION) -> dict:
    """Where the toe, straight-line portion and shoulder lie, from the gradient profile. A region the measurements do not reach is None."""
    g = gamma(curve, support, fraction)
    if g is None:
        return {"toe": None, "straight": None, "shoulder": None}
    lo, hi = g.interval
    return {
        "toe": (support[0], lo) if lo - support[0] > 1e-6 else None,
        "straight": (lo, hi),
        "shoulder": (hi, support[1]) if support[1] - hi > 1e-6 else None,
    }


def iso6_geometry(curve, support: tuple[float, float], toe_offset: float = ISO6_TOE_OFFSET, span: float = ISO6_SPAN) -> dict:
    """The geometry of the ISO 6 speed criterion for black-and-white negatives: the point 0.10 above base, the point 1.30 log H higher, the density
    rise between them (the criterion asks for 0.80) and the average gradient. It describes the *curve's* geometry; it is not a speed determination and
    does not apply to colour negative film."""
    x = _grid(support, 4001)
    d = np.maximum.accumulate(np.asarray(curve(x), dtype=np.float64))
    target = toe_offset
    if target < d[0] or target > d[-1]:
        return {"available": False, "reason": f"the curve does not pass {toe_offset:.2f} above the base within the measured range"}
    xs = float(np.interp(target, d, x))
    xe = xs + span
    if xe > support[1] + 1e-9:
        return {"available": False, "reason": f"the measurements end {xe - support[1]:.2f} log H short of the point {span:.2f} above the speed point"}
    ds, de = float(curve(xs)), float(curve(xe))
    return {
        "available": True, "speed_point": (xs, ds), "end_point": (float(xe), de), "rise": de - ds, "criterion_rise": ISO6_RISE,
        "average_gradient": (de - ds) / span, "span": span,
    }


@dataclass(frozen=True)
class Guidance:
    shadow: str
    midtone: str
    highlight: str
    numbers: dict
    note: str


def _word(ratio: float, region: str) -> str:
    return "good" if ratio >= HIGH_RATIO else ("moderate" if ratio >= LOW_RATIO else "weak")


def guidance(curve, support: tuple[float, float]) -> Guidance | None:
    """Plain-language reading of the gradient in the lowest, middle and highest thirds of the measured density range, relative to the peak gradient."""
    x = _grid(support)
    d = np.asarray(curve(x), dtype=np.float64)
    g = local_gradient(curve, x)
    peak = float(g.max())
    if peak <= 0 or d[-1] - d[0] <= 1e-6:
        return None
    top = float(d[-1])
    edges = np.array([d[0], d[0] + (top - d[0]) / 3.0, d[0] + 2.0 * (top - d[0]) / 3.0, top])
    means = []
    for a, b in zip(edges[:-1], edges[1:]):
        sel = (d >= a) & (d <= b)
        means.append(float(g[sel].mean()) if sel.any() else 0.0)
    r_lo, r_mid, r_hi = (m / peak for m in means)
    toe_seen = d[0] <= 0.15 * top
    shoulder_seen = g[-1] <= 0.5 * peak
    shadow = {
        "good": "Shadows keep good separation: the film responds almost as strongly in the thinnest densities as in the midtones.",
        "moderate": "Shadows are somewhat compressed: close tones in the darkest parts of the scene lose some separation.",
        "weak": "Shadows are strongly compressed: close tones in the darkest parts of the scene are squeezed together.",
    }[_word(r_lo, "shadow")]
    if not toe_seen:
        shadow += " The measurements do not reach down to the film base, so the toe is not shown."
    highlight = {
        "good": "Highlights keep good separation: the film still responds strongly at its densest measured values.",
        "moderate": "Highlights are gently compressed: bright tones are packed a little closer together.",
        "weak": "Highlights are strongly compressed: bright tones are squeezed together.",
    }[_word(r_hi, "highlight")]
    if not shoulder_seen:
        highlight += " The measurements end before the curve flattens, so the shoulder may lie beyond what was measured."
    gm = gamma(curve, support)
    level = "low" if peak < 0.45 else ("moderate" if peak < 0.75 else "high")
    midtone = f"Midtone contrast is {level}: the steepest part of the curve has a gradient of {peak:.2f} (density per unit of log exposure). The wording uses EFAS's own cut-offs, not a standard."
    return Guidance(
        shadow, midtone, highlight,
        {"peak_gradient": peak, "shadow_ratio": r_lo, "midtone_ratio": r_mid, "highlight_ratio": r_hi, "gamma": gm.gamma if gm else None, "toe_seen": toe_seen, "shoulder_seen": shoulder_seen},
        "This describes the film's response over the exposures that were measured. It is not a reconstruction of the scene.",
    )
