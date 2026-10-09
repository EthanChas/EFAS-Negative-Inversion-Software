"""Step-target patches: where they are, what they measure, and which measurements can be trusted (docs/sensitometry-tier2-design.md, sections 2.1 and 8).

A target is a series of patches with known steps: a transmission step tablet scanned to calibrate the camera, or a developed film strip that was
exposed through a tablet. Nothing here invents a patch value: it only samples the linear scan the user points at and says which patches are usable.
Numpy only, no Qt/UI imports.
"""

from dataclasses import dataclass, field

import numpy as np

from .linear import optical_density

STEP_TOLERANCE = 0.015
DEPARTURE_ABS, DEPARTURE_REL = 0.02, 0.02
FIT_DEPARTURE = 0.02
MAX_UNEVEN = 0.05
CLIP_LEVEL = 0.999
MAX_CLIPPED_FRACTION = 0.05
FLOOR_FACTOR = 1.5
MIN_PIXELS = 25
SPREAD_NORMAL = 2.563


class TargetError(ValueError):
    """The target description cannot be used."""


@dataclass(frozen=True)
class StepTarget:
    """A step series. `densities` are the tablet's actual (calibrated) values when known; otherwise the nominal ones are `start + increment * i`."""

    steps: int
    start: float = 0.05
    increment: float = 0.15
    densities: tuple[float, ...] | None = None
    name: str = ""
    reverse: bool = False

    def values(self) -> np.ndarray:
        """The step densities in the order the patches are laid out: lowest to highest, or highest to lowest when `reverse` is set."""
        if self.densities is not None:
            d = np.asarray(self.densities, dtype=np.float64)
            if d.size != self.steps:
                raise TargetError("the list of tablet densities must have one value per step")
        else:
            d = self.start + self.increment * np.arange(self.steps)
        return d[::-1].copy() if self.reverse else d

    def actual(self) -> bool:
        """True when the densities came from a calibration chart or a densitometer rather than the nominal series."""
        return self.densities is not None


def parse_density_list(text: str) -> tuple[float, ...]:
    """Tablet densities pasted as text (commas, spaces or new lines between them)."""
    parts = [p for p in text.replace(",", " ").replace(";", " ").split() if p]
    try:
        values = tuple(float(p) for p in parts)
    except ValueError as exc:
        raise TargetError("the density list must contain only numbers") from exc
    if len(values) < 3:
        raise TargetError("give at least three densities")
    if not all(np.isfinite(values)) or min(values) < 0 or max(values) > 6.0:
        raise TargetError("tablet densities must lie between 0 and 6")
    return values


def tolerance_warnings(densities: np.ndarray, nominal_increment: float = 0.15) -> list[str]:
    """SMPTE RP 14-1997 tolerances for treating a tablet as its nominal series. Failing them does not make a tablet unusable; it means the actual
    densities must be used rather than the nominal ones, and cumulative errors can mislead."""
    d = np.asarray(densities, dtype=np.float64)
    out = []
    if d.size < 3:
        return out
    steps = np.diff(d)
    if np.any(np.abs(steps - nominal_increment) > STEP_TOLERANCE * nominal_increment / 0.15):
        out.append(f"Some adjacent steps differ from {nominal_increment:.3f} by more than {STEP_TOLERANCE * nominal_increment / 0.15:.3f}.")
    nominal = d[0] + nominal_increment * np.arange(d.size)
    limit = np.maximum(DEPARTURE_ABS, DEPARTURE_REL * np.abs(nominal))
    if np.any(np.abs(d - nominal) > limit):
        out.append("Some steps depart from the nominal series by more than 0.02 density or 2%.")
    slope, intercept = np.polyfit(np.arange(d.size), d, 1)
    if np.any(np.abs(d - (slope * np.arange(d.size) + intercept)) > FIT_DEPARTURE):
        out.append("Some steps are more than 0.02 density from a straight line through all the steps.")
    return out


@dataclass(frozen=True)
class Patch:
    index: int
    cx: float
    cy: float
    half: int


def layout_patches(p0: tuple[float, float], p1: tuple[float, float], n: int, fill: float = 0.5, max_half: int = 400) -> list[Patch]:
    """`n` square patches centred evenly from p0 to p1 (the first and last patch centres the user clicked). `fill` is the share of the spacing each
    patch's side takes, so the sampled square keeps clear of the neighbouring steps."""
    if n < 3:
        raise TargetError("a target needs at least 3 patches")
    if not 0.1 <= fill <= 0.95:
        raise TargetError("fill must be between 0.1 and 0.95")
    p0, p1 = np.asarray(p0, dtype=np.float64), np.asarray(p1, dtype=np.float64)
    spacing = float(np.linalg.norm(p1 - p0)) / (n - 1)
    if spacing < 3.0:
        raise TargetError("the first and last patch are too close together for this many steps")
    half = int(max(1, min(max_half, round(spacing * fill / 2.0))))
    return [Patch(i, float(p0[0] + (p1[0] - p0[0]) * i / (n - 1)), float(p0[1] + (p1[1] - p0[1]) * i / (n - 1)), half) for i in range(n)]


@dataclass(frozen=True)
class PatchSample:
    index: int
    v: tuple[float, float, float]
    spread: tuple[float, float, float]
    pixels: int
    clipped: float
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def valid(self) -> bool:
        return not self.reasons


def sample_patches(framed: np.ndarray, patches: list[Patch], floor=(0.0, 0.0, 0.0)) -> list[PatchSample]:
    """Median linear value of each patch, how uneven it is (the 10th to 90th percentile range of density, scaled to a standard deviation, which unlike a median deviation still sees a patch that is half one tone and half another), how much of it is clipped, and why it is not usable."""
    h, w = framed.shape[:2]
    fl = np.asarray(floor, dtype=np.float64)
    out = []
    for p in patches:
        x1, x2 = int(round(p.cx)) - p.half, int(round(p.cx)) + p.half + 1
        y1, y2 = int(round(p.cy)) - p.half, int(round(p.cy)) + p.half + 1
        if x1 < 0 or y1 < 0 or x2 > w or y2 > h:
            out.append(PatchSample(p.index, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 0, 0.0, ("outside the picture",)))
            continue
        px = framed[y1:y2, x1:x2].reshape(-1, 3).astype(np.float64)
        med = np.median(px, axis=0)
        dens = optical_density(px, fl)
        spread = (np.percentile(dens, 90, axis=0) - np.percentile(dens, 10, axis=0)) / SPREAD_NORMAL
        clipped = float((px >= CLIP_LEVEL).any(axis=1).mean())
        reasons = []
        if px.shape[0] < MIN_PIXELS:
            reasons.append("too few pixels")
        if clipped > MAX_CLIPPED_FRACTION or np.any(med >= CLIP_LEVEL):
            reasons.append("sensor clipped")
        if fl.any() and np.any(med <= fl * FLOOR_FACTOR):
            reasons.append("below the noise floor")
        if float(spread.max()) > MAX_UNEVEN:
            reasons.append("uneven (dust, an edge or a gradient)")
        out.append(PatchSample(p.index, tuple(float(x) for x in med), tuple(float(x) for x in spread), int(px.shape[0]), clipped, tuple(reasons)))
    return out


def order_violations(v: np.ndarray, densities: np.ndarray, tolerance: float = 0.02) -> list[int]:
    """Patches whose signal does not fall as the tablet density rises (within `tolerance` of the value, in density terms), per the steps' known order.
    Returns the indices that break the order; a wrong patch order or a patch on the wrong step shows up here."""
    v = np.asarray(v, dtype=np.float64)
    d = np.asarray(densities, dtype=np.float64)
    order = np.argsort(d, kind="stable")
    bad = []
    prev = None
    for i in order:
        if prev is not None and d[i] > d[prev] + 1e-9 and v[i] > v[prev] * (10.0 ** tolerance):
            bad.append(int(i))
        else:
            prev = i if prev is None or v[i] <= v[prev] else prev
    return bad
