"""Why part of a density measurement cannot be trusted: sensor clipping, too little signal, noise, a possible film limit, or invalid data
(docs/sensitometry-tier2-design.md, section 7). Each finding carries an evidence status, and nothing is blamed on the film unless the scan could
not be the cause. Numpy only, no Qt/UI imports.
"""

from dataclasses import dataclass

import numpy as np

from .linear import ScanInfo

CLIP_LEVEL = 0.999
SNR_MIN = 10.0
HEADROOM_TARGET = 0.90
MIN_HEADROOM_STOPS = 0.3
PLATEAU_BAND = 0.05
PLATEAU_RATIO = 3.0
PLATEAU_MIN_SHARE = 0.005
TILES = 8
TILE_SAMPLE = 1000
BOOTSTRAPS = 60
REPORT_SHARE = 0.001
CATEGORIES = ("sensor_clipped", "below_floor", "noise_limited", "usable", "invalid")
CATEGORY_LABELS = {
    "sensor_clipped": "Sensor clipped (thin areas of the negative)",
    "below_floor": "Below the noise floor (dense areas)",
    "noise_limited": "Noise limited (weak signal)",
    "usable": "Usable",
    "invalid": "Invalid (not a number)",
}


@dataclass(frozen=True)
class Statement:
    level: str
    text: str
    evidence: str


@dataclass(frozen=True)
class Interval:
    value: float
    low: float
    high: float


@dataclass(frozen=True)
class Diagnosis:
    fractions: dict
    any_channel: dict
    evidence: dict
    headroom_stops: float | None
    headroom_density: float | None
    dmax: tuple
    film_limit: tuple
    statements: tuple[Statement, ...]
    pixels: int


def classify(px: np.ndarray, info: ScanInfo, floor) -> tuple[dict, dict, dict]:
    """Per-channel shares of each category, the shares of pixels where any channel is in it (for 'usable': where every channel is), and the evidence status of each category."""
    px = np.asarray(px, dtype=np.float64).reshape(-1, 3)
    fl = np.asarray(floor, dtype=np.float64)
    finite = np.isfinite(px)
    safe = np.where(finite, px, 0.0)
    clipped = (safe >= CLIP_LEVEL) & finite
    below = (safe <= fl) & finite & ~clipped
    sigma = None if info.noise_sigma is None else np.asarray(info.noise_sigma, dtype=np.float64)
    noisy = (safe > fl) & (safe <= SNR_MIN * sigma) & finite if sigma is not None else np.zeros_like(clipped)
    invalid = ~finite
    usable = finite & ~clipped & ~below & ~noisy
    cats = {"sensor_clipped": clipped, "below_floor": below, "noise_limited": noisy, "usable": usable, "invalid": invalid}
    n = max(px.shape[0], 1)
    per = {c: tuple(float(m[:, i].sum() / n) for i in range(3)) for c, m in cats.items()}
    anych = {c: float(m.any(axis=1).sum() / n) for c, m in cats.items()}
    anych["usable"] = float(usable.all(axis=1).sum() / n)
    raw = info.measured
    evidence = {
        "sensor_clipped": "measured" if raw else "inferred",
        "below_floor": "measured" if raw else "inferred",
        "noise_limited": "inferred" if sigma is not None else "unknown",
        "usable": "measured" if raw else "inferred",
        "invalid": "measured",
    }
    return per, anych, evidence


def headroom(v_base, px: np.ndarray, target: float = HEADROOM_TARGET):
    """How much more light the camera could have taken before the thinnest areas clip: (stops, density-equivalent). None when already near the top."""
    top = max(float(np.max(v_base)), float(np.percentile(np.asarray(px, dtype=np.float64).reshape(-1, 3), 99.9)))
    if top <= 0 or not np.isfinite(top):
        return None, None
    g = target / top
    stops = float(np.log2(g))
    if stops < MIN_HEADROOM_STOPS:
        return None, None
    return stops, float(np.log10(g))


def _tile_samples(net: np.ndarray, region_shape, tiles: int, per_tile: int, rng) -> list[np.ndarray]:
    h, w = region_shape
    ys, xs = np.linspace(0, h, tiles + 1).astype(int), np.linspace(0, w, tiles + 1).astype(int)
    out = []
    grid = net.reshape(h, w, 3)
    for i in range(tiles):
        for j in range(tiles):
            t = grid[ys[i]:ys[i + 1], xs[j]:xs[j + 1]].reshape(-1, 3)
            if t.shape[0] == 0:
                continue
            take = rng.choice(t.shape[0], size=min(per_tile, t.shape[0]), replace=False)
            out.append(t[take])
    return out


def bound_interval(net: np.ndarray, region_shape, percentile: float, bootstraps: int = BOOTSTRAPS, seed: int = 12345) -> tuple:
    """A percentile of the density above base per channel, with a 95% interval from resampling image tiles (not pixels), so spatial correlation counts."""
    rng = np.random.default_rng(seed)
    tiles = _tile_samples(net, region_shape, TILES, TILE_SAMPLE, rng)
    if len(tiles) < 4:
        pooled = net.reshape(-1, 3)
        val = np.percentile(pooled, percentile, axis=0)
        return tuple(Interval(float(v), float(v), float(v)) for v in val)
    point = np.percentile(np.concatenate(tiles), percentile, axis=0)
    draws = np.empty((bootstraps, 3))
    for b in range(bootstraps):
        pick = rng.integers(0, len(tiles), size=len(tiles))
        draws[b] = np.percentile(np.concatenate([tiles[i] for i in pick]), percentile, axis=0)
    lo, hi = np.percentile(draws, 2.5, axis=0), np.percentile(draws, 97.5, axis=0)
    return tuple(Interval(float(point[c]), float(min(lo[c], point[c])), float(max(hi[c], point[c]))) for c in range(3))


def plateau_at_top(net_channel: np.ndarray, percentile: float = 99.9) -> bool:
    """Whether the density histogram piles up at its dense end: the band just below the top percentile holds several times the mass of the three
    bands under it (and at least 0.5% of all pixels). A pile-up there is consistent with a film maximum density (or with the camera's own limit; see film_limit for that distinction)."""
    top = float(np.percentile(net_channel, percentile))
    edges = top - PLATEAU_BAND * np.arange(5)
    masses = [float(((net_channel <= edges[i]) & (net_channel > edges[i + 1])).sum()) for i in range(4)]
    below = float(np.mean(masses[1:]))
    return masses[0] >= max(PLATEAU_RATIO * below, PLATEAU_MIN_SHARE * net_channel.size) and masses[0] > 0


def film_limit(px: np.ndarray, net: np.ndarray, info: ScanInfo, floor) -> tuple:
    """Per channel: 'unknown', 'not indicated' or 'possible'. A film maximum is only suggested when the densest areas still give a signal well above
    the noise (so the camera could have shown more) AND the histogram piles up there. If the signal is near the floor, the scan, not the film, may be
    the limit and nothing is claimed."""
    sigma = np.asarray(info.noise_sigma if info.noise_sigma is not None else (0.0, 0.0, 0.0), dtype=np.float64)
    fl = np.asarray(floor, dtype=np.float64)
    out = []
    for c in range(3):
        dense = np.percentile(px[:, c], 0.1)
        signal_ok = info.noise_sigma is not None and dense >= SNR_MIN * sigma[c] and dense > fl[c] * 2.0
        if not signal_ok:
            out.append("unknown")
        elif plateau_at_top(net[:, c]):
            out.append("possible")
        else:
            out.append("not indicated")
    return tuple(out)


def diagnose(v: np.ndarray, info: ScanInfo, v_base, floor, net: np.ndarray, region_shape, percentile: float = 99.9) -> Diagnosis:
    """The full diagnosis of one measured region. `net` is the density above base of every pixel in `v` (same order, Nx3)."""
    px = np.asarray(v, dtype=np.float64).reshape(-1, 3)
    per, anych, evidence = classify(px, info, floor)
    stops, dens = headroom(v_base, px)
    dm = bound_interval(np.where(np.isfinite(net), net, 0.0), region_shape, percentile)
    fl = film_limit(np.where(np.isfinite(px), px, 0.0), np.where(np.isfinite(net), net, 0.0), info, floor)
    s: list[Statement] = []
    if anych["sensor_clipped"] > REPORT_SHARE:
        s.append(Statement("warning", f"{anych['sensor_clipped'] * 100:.1f}% of the picture is clipped in the camera (the thinnest parts of the negative). "
                                      "Their density cannot be measured. The cause is exposure: take the scan with less light.", evidence["sensor_clipped"]))
    if anych["below_floor"] > REPORT_SHARE:
        text = (f"{anych['below_floor'] * 100:.1f}% of the picture is below the camera's noise floor (the densest parts). Those areas could be denser than the scan "
                "can show; the scan cannot say whether the film, the exposure, the light or the camera is the limit.")
        if stops is not None:
            text += (f" The film base reads well below the sensor's top, so about {stops:.1f} stops more light would measure about {dens:.2f} more density. "
                     "That points to the exposure or the backlight, which you can change.")
        else:
            text += " The exposure is already near the sensor's limit, so more light will not help; the sensor's range or flare is the limit."
        s.append(Statement("warning", text, evidence["below_floor"]))
    if anych["noise_limited"] > REPORT_SHARE:
        s.append(Statement("info", f"{anych['noise_limited'] * 100:.1f}% of the picture has a weak signal (under {SNR_MIN:.0f} times the sensor's read noise), so its density is noisy.", evidence["noise_limited"]))
    elif evidence["noise_limited"] == "unknown":
        s.append(Statement("info", "No sensor noise estimate was available, so noise-limited areas cannot be identified.", "unknown"))
    if anych["invalid"] > 0:
        s.append(Statement("warning", f"{anych['invalid'] * 100:.2f}% of the values were not numbers and were left out.", evidence["invalid"]))
    possible = [("R", "G", "B")[i] for i in range(3) if fl[i] == "possible"]
    if possible:
        s.append(Statement("info", f"In {', '.join(possible)} the densest areas still give a strong signal and the histogram piles up at the dense end, which is consistent with "
                                   "the film's maximum density. This is an inference from the histogram shape, not a measurement.", "inferred"))
    unknown = [("R", "G", "B")[i] for i in range(3) if fl[i] == "unknown"]
    if unknown:
        s.append(Statement("info", f"In {', '.join(unknown)} the signal in the densest areas is too weak to tell whether the film or the scan sets the limit, so nothing is claimed about the film.", "unknown"))
    return Diagnosis(per, anych, evidence, stops, dens, dm, fl, tuple(s), int(px.shape[0]))
