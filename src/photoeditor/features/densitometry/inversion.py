"""Curve-informed negative inversion and the numbers for comparing it with the existing inversion (docs/sensitometry-tier2-design.md, section 9).

Four steps, each of a different kind, and never mixed:
  1. measured     density above the film base, from the linear scan;
  2. estimated    the exposure that density implies, through the profile's measured curve (out-of-range densities are clamped, never extrapolated);
  3. reconstructed that exposure divided by a white reference (an assumption: the scene and its light are unknown);
  4. rendered     the display encoding, applied last.

Numpy only, no Qt/UI imports.
"""

from dataclasses import dataclass

import numpy as np

from .fit import invert_curve
from .scanner import correct_flare

CHUNK = 600_000
FLAT_RATIO = 0.15
ASSUMED_SIGMA_D = 0.01
WHITE_PERCENTILE = 99.5
OETF_LINEAR_BELOW = 0.0031308


class InversionError(ValueError):
    """The curve-informed inversion cannot be done, with the reason."""


@dataclass(frozen=True)
class ChannelModel:
    curve: object
    support: tuple[float, float]


def channel_models(profile) -> dict[str, ChannelModel]:
    """The per-channel curves of a usable profile, as R, G, B models (a black-and-white profile's K curve serves all three)."""
    if not profile.usable_for_inversion():
        raise InversionError("This profile cannot drive an inversion: only measured or supplied profiles with R, G and B curves (or a K curve) can.")
    out = {}
    for ch in "RGB":
        cc = profile.curves.get(ch) or profile.curves["K"]
        out[ch] = ChannelModel(cc.curve(), cc.supported())
    return out


@dataclass(frozen=True)
class InversionResult:
    positive: np.ndarray
    log_exposure: np.ndarray
    delta_density: np.ndarray
    white: tuple[float, float, float]
    below: tuple[float, float, float]
    above: tuple[float, float, float]
    covered: float
    poorly_determined: tuple[float, float, float]
    notes: tuple[str, ...]


def _density(v: np.ndarray, v_base, floor, flare):
    """Density above base per channel, with the flare fraction removed first when a calibrated one and a clear sample are given."""
    v = np.asarray(v, dtype=np.float64)
    base = np.asarray(v_base, dtype=np.float64)
    fl = np.maximum(np.asarray(floor, dtype=np.float64), 1e-12)
    if flare is not None:
        clear, phi = flare
        t = correct_flare(v, np.asarray(clear, dtype=np.float64), phi)
        tb = correct_flare(base, np.asarray(clear, dtype=np.float64), phi)
        return np.log10(np.maximum(tb, 1e-12)) - np.log10(np.maximum(t, fl / np.asarray(clear)))
    return np.log10(base) - np.log10(np.maximum(v, fl))


def invert_with_curves(v: np.ndarray, v_base, models: dict, floor=(1e-6, 1e-6, 1e-6), flare=None, white=None,
                       white_percentile: float = WHITE_PERCENTILE, reference_region=None) -> InversionResult:
    """Invert the linear scan `v` (HxWx3) with each channel's measured curve.

    `white` is the per-channel relative exposure that should come out as 1.0: None takes the `white_percentile` of the picture (or of
    `reference_region`, a (y1, y2, x1, x2) slice, when given). That choice is an assumption and is reported in `notes`. The coverage and
    flat-curve shares are counted over `reference_region` too (the clear film border is not picture and would read as out of range)."""
    v = np.asarray(v)
    if v.ndim != 3 or v.shape[2] != 3:
        raise InversionError("the scan must be an HxWx3 array")
    h, w = v.shape[:2]
    flat = v.reshape(-1, 3)
    n = flat.shape[0]
    x = np.empty((n, 3), dtype=np.float32)
    dd = np.empty((n, 3), dtype=np.float32)
    status = np.empty((n, 3), dtype=np.int8)
    flat_zone = np.zeros((n, 3), dtype=bool)
    peaks = {}
    for ch in "RGB":
        grid = np.linspace(models[ch].support[0], models[ch].support[1], 801)
        peaks[ch] = float(np.max(models[ch].curve.derivative(grid)))
    for start in range(0, n, CHUNK):
        sl = slice(start, min(start + CHUNK, n))
        d = _density(flat[sl], v_base, floor, flare)
        for c, ch in enumerate("RGB"):
            m = models[ch]
            xc, st = invert_curve(m.curve, d[:, c], m.support[0], m.support[1])
            x[sl, c], status[sl, c], dd[sl, c] = xc, st, d[:, c]
            flat_zone[sl, c] = np.asarray(m.curve.derivative(xc)) < FLAT_RATIO * peaks[ch]
    expo = np.power(10.0, x.astype(np.float64))
    notes = []
    if white is None:
        ref = expo
        if reference_region is not None:
            y1, y2, x1, x2 = reference_region
            ref = expo.reshape(h, w, 3)[y1:y2, x1:x2].reshape(-1, 3)
        white_ref = np.percentile(ref, white_percentile, axis=0)
        notes.append(f"The white reference is the {white_percentile:g}th percentile of the estimated exposure in each channel. It is an assumption about the scene's lighting, "
                     "and it is what sets the colour balance.")
    else:
        white_ref = np.asarray(white, dtype=np.float64)
        notes.append("The white reference was set by the user.")
    if np.any(white_ref <= 0) or not np.isfinite(white_ref).all():
        raise InversionError("the white reference is not usable")
    positive = (expo / white_ref).astype(np.float32).reshape(h, w, 3)
    stat, flatz = status, flat_zone
    if reference_region is not None:
        y1, y2, x1, x2 = reference_region
        stat = status.reshape(h, w, 3)[y1:y2, x1:x2].reshape(-1, 3)
        flatz = flat_zone.reshape(h, w, 3)[y1:y2, x1:x2].reshape(-1, 3)
    below = tuple(float((stat[:, c] < 0).mean()) for c in range(3))
    above = tuple(float((stat[:, c] > 0).mean()) for c in range(3))
    covered = float((stat == 0).all(axis=1).mean())
    poor = tuple(float((flatz[:, c] & (stat[:, c] == 0)).mean()) for c in range(3))
    if covered < 0.9:
        notes.append(f"Only {covered * 100:.0f}% of the picture lies inside the profile's measured density range in all three channels. The rest was clamped to the "
                     "ends of the measured curve, so its tones are not estimated, only limited.")
    if max(poor) > 0.02:
        notes.append(f"Up to {max(poor) * 100:.0f}% of the picture sits where the curve is nearly flat (the toe or shoulder), so a small density error there means a large "
                     f"exposure error (about {ASSUMED_SIGMA_D / (FLAT_RATIO):.2f} log units at the flattest allowed point for {ASSUMED_SIGMA_D:g} density of uncertainty).")
    return InversionResult(positive, x.reshape(h, w, 3), dd.reshape(h, w, 3), tuple(float(s) for s in white_ref), below, above, covered, poor, tuple(notes))


def invert_to_uint16(v: np.ndarray, v_base, models: dict, floor, white, flare=None) -> np.ndarray:
    """The same inversion with a given white reference, written straight to a display-encoded 16-bit picture in row blocks, so a full-resolution scan
    does not need several full-size float arrays at once. Matches to_uint16(invert_with_curves(..., white=white).positive) exactly."""
    v = np.asarray(v)
    if v.ndim != 3 or v.shape[2] != 3:
        raise InversionError("the scan must be an HxWx3 array")
    white_ref = np.asarray(white, dtype=np.float64)
    if np.any(white_ref <= 0) or not np.isfinite(white_ref).all():
        raise InversionError("the white reference is not usable")
    h, w = v.shape[:2]
    out = np.empty((h, w, 3), dtype=np.uint16)
    rows = max(1, CHUNK // max(w, 1))
    for y in range(0, h, rows):
        block = v[y:y + rows].reshape(-1, 3)
        d = _density(block, v_base, floor, flare)
        e = np.empty_like(d)
        for c, ch in enumerate("RGB"):
            m = models[ch]
            xc, _st = invert_curve(m.curve, d[:, c], m.support[0], m.support[1])
            e[:, c] = np.power(10.0, xc.astype(np.float32).astype(np.float64))
        out[y:y + rows] = to_uint16((e / white_ref).astype(np.float32)).reshape(-1, w, 3)
    return out


def srgb_oetf(linear: np.ndarray) -> np.ndarray:
    """Display encoding of linear light in [0, 1]. This is rendering, applied after the reconstruction, never inside it."""
    a = np.clip(np.asarray(linear, dtype=np.float64), 0.0, 1.0)
    return np.where(a <= OETF_LINEAR_BELOW, 12.92 * a, 1.055 * np.power(a, 1.0 / 2.4) - 0.055)


def to_uint16(positive: np.ndarray) -> np.ndarray:
    """The reconstructed positive as a display-encoded 16-bit picture."""
    return np.round(srgb_oetf(positive) * 65535.0).astype(np.uint16)


def lstar(srgb01: np.ndarray) -> np.ndarray:
    """CIE L* of an sRGB picture in [0, 1], from its luminance. Used to compare two renderings in a perceptually even scale."""
    a = np.asarray(srgb01, dtype=np.float64)
    lin = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    y = 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]
    return np.where(y > 216.0 / 24389.0, 116.0 * np.cbrt(y) - 16.0, y * 24389.0 / 27.0)


def compare_positives(a: np.ndarray, b: np.ndarray) -> dict:
    """How two renderings of the same picture differ, given as arrays of equal size in display encoding, scaled 0-1."""
    a = np.clip(np.asarray(a, dtype=np.float64), 0.0, 1.0)
    b = np.clip(np.asarray(b, dtype=np.float64), 0.0, 1.0)
    if a.shape != b.shape or a.ndim != 3 or a.shape[2] != 3:
        raise InversionError("the two pictures must be HxWx3 arrays of the same size")
    la, lb = lstar(a), lstar(b)
    dl = lb - la
    ca = np.corrcoef(la.ravel(), lb.ravel())[0, 1] if la.std() > 1e-9 and lb.std() > 1e-9 else float("nan")
    return {
        "mean_abs_difference": tuple(float(x) for x in np.abs(b - a).mean(axis=(0, 1))),
        "mean_shift": tuple(float(x) for x in (b - a).mean(axis=(0, 1))),
        "rms_delta_lstar": float(np.sqrt(np.mean(dl ** 2))),
        "share_over_5_lstar": float((np.abs(dl) > 5.0).mean()),
        "luminance_correlation": float(ca),
        "lstar_range_a": (float(np.percentile(la, 1)), float(np.percentile(la, 99))),
        "lstar_range_b": (float(np.percentile(lb, 1)), float(np.percentile(lb, 99))),
    }


def tone_transfer(delta_density: np.ndarray, a: np.ndarray, b: np.ndarray, quantiles=(1, 5, 25, 50, 75, 95, 99)) -> list[dict]:
    """How each rendering maps the picture's own density to output lightness, at a few points: the density above base (green channel) at each quantile and the
    L* each method gave there. Shows where the two methods agree and where they part."""
    d = np.asarray(delta_density)[..., 1].ravel()
    la, lb = lstar(np.clip(a, 0, 1)).ravel(), lstar(np.clip(b, 0, 1)).ravel()
    rows = []
    for q in quantiles:
        lo, hi = np.percentile(d, max(q - 0.5, 0)), np.percentile(d, min(q + 0.5, 100))
        sel = (d >= lo) & (d <= hi)
        if sel.any():
            rows.append({"quantile": q, "density_above_base": float(d[sel].mean()), "lstar_a": float(la[sel].mean()), "lstar_b": float(lb[sel].mean())})
    return rows
