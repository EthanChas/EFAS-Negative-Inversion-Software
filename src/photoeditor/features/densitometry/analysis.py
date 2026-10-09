"""One call that measures a linear scan: film base, density range, Dmax, histograms and the warnings that go with them.

Simple Mode and Advanced Mode both read the Measurement this returns, so there is one engine and two presentations
(docs/scientific-inversion-design.md, section 7). Numpy only, no Qt/UI imports.
"""

from dataclasses import dataclass

import numpy as np

from . import base as base_mod
from . import diagnostics as diag_mod
from .base import BaseSample
from .dmax import DmaxResult, estimate_dmax
from .histogram import NET_RANGE, REL_RANGE, DensityHistogram, density_histogram
from .linear import ScanInfo, density_above_base, optical_density

MAX_PIXELS = 600_000
RANGE_LOW, RANGE_HIGH = 0.1, 99.9
SATURATED_WARN = 0.005
BRIGHTER_THAN_BASE = 1.05
BRIGHTER_WARN = 0.01
CHANNELS = ("R", "G", "B")


@dataclass(frozen=True)
class Diagnostic:
    level: str
    text: str


@dataclass(frozen=True)
class Measurement:
    info: ScanInfo
    pixels: int
    floor: tuple[float, float, float]
    base: BaseSample
    clear: tuple[float, float, float] | None
    dmin_rel: tuple[float, float, float]
    dmin_abs: tuple[float, float, float] | None
    dmax: DmaxResult
    value_range: tuple[tuple[float, float], ...]
    t_rel_range: tuple[tuple[float, float], ...]
    rel_hist: DensityHistogram
    net_hist: DensityHistogram
    diagnostics: tuple[Diagnostic, ...]
    confidence: str
    diagnosis: object = None

    def density_range(self) -> tuple[float, float, float]:
        """Density between the film base and the dense end, per channel."""
        return self.dmax.value


@dataclass(frozen=True)
class Row:
    label: str
    values: tuple[str, ...]
    status: str
    tip: str


def _subsample(v: np.ndarray, max_pixels: int) -> np.ndarray:
    h, w = v.shape[:2]
    step = max(1, int(np.ceil(np.sqrt(h * w / max_pixels))))
    return v[::step, ::step]


def analyse(v: np.ndarray, info: ScanInfo, base: BaseSample | None = None, clear=None, max_pixels: int = MAX_PIXELS) -> Measurement:
    """Measure the linear picture `v` (HxWx3, normalised). `base` is the sampled film base (None: estimated from the picture);
    `clear` is the per-channel value of the light source with no film, when the user sampled it."""
    sub = _subsample(np.asarray(v), max_pixels)
    px = sub.reshape(-1, 3).astype(np.float64)
    floor = info.floor()
    estimated = base is None
    base = base_mod.estimate_base(px, floor) if estimated else base
    d_rel = optical_density(px, floor)
    d_net = density_above_base(px, base.v, floor)
    dmax = estimate_dmax(px, base.v, floor)
    dmin_rel = base.dmin_rel(floor)
    clear_t = tuple(float(c) for c in clear) if clear is not None else None
    dmin_abs = tuple(float(-np.log10(base.v[i] / clear_t[i])) for i in range(3)) if clear_t else None

    lo, hi = np.percentile(px, RANGE_LOW, axis=0), np.percentile(px, RANGE_HIGH, axis=0)
    value_range = tuple((float(lo[i]), float(hi[i])) for i in range(3))
    t_rel = tuple((float(lo[i] / base.v[i]), float(hi[i] / base.v[i])) for i in range(3))

    diags: list[Diagnostic] = []
    if not info.measured:
        diags.append(Diagnostic("warning", f"This is not a RAW file, so the {info.encoding} encoding is assumed. Densities are approximate."))
    if info.bit_depth <= 8:
        diags.append(Diagnostic("warning", "An 8-bit file has coarse steps in the dense areas, so densities there are rough."))
    if info.noise_sigma is None:
        diags.append(Diagnostic("info", "The noise floor comes from the file's bit depth only; no sensor noise estimate was available."))
    for w in base.warnings:
        diags.append(Diagnostic("warning", w))
    if not estimated:
        brighter = (px > np.asarray(base.v) * BRIGHTER_THAN_BASE).mean(axis=0)
        if float(brighter.max()) > BRIGHTER_WARN:
            diags.append(Diagnostic("warning", "Some of the picture is lighter than the film base, which a negative cannot be. "
                                               "The light or exposure may have changed since the base was sampled, or the sample was not film base."))
    limited = [CHANNELS[i] for i in range(3) if dmax.limited[i]]
    if limited:
        diags.append(Diagnostic("info", f"Dmax in {', '.join(limited)} is limited by the scan (noise floor or flare), so it is a lower bound for the film."))
    if dmin_abs is not None:
        order = base_mod.mask_order_check(dmin_abs)
        if order:
            diags.append(Diagnostic("warning", order))
    else:
        diags.append(Diagnostic("info", "No clear-light sample: densities are camera-relative and the orange-mask order cannot be checked. "
                                        "Density above the film base is still exact."))
    diags.append(Diagnostic("info", "Camera flare is not corrected: the densest areas read lighter than they really are."))

    diagnosis = diag_mod.diagnose(px, info, base.v, floor, d_net, sub.shape[:2])
    diags.extend(Diagnostic(s.level, f"{s.text} [{s.evidence}]") for s in diagnosis.statements)
    warnings = sum(d.level == "warning" for d in diags)
    if estimated or not info.measured:
        confidence = "low"
    elif warnings:
        confidence = "medium"
    else:
        confidence = "high"
    return Measurement(
        info, int(px.shape[0]), floor, base, clear_t, dmin_rel, dmin_abs, dmax, value_range, t_rel,
        density_histogram(d_rel, REL_RANGE), density_histogram(d_net, NET_RANGE), tuple(diags), confidence, diagnosis,
    )


def density_at(m: Measurement, v_pixel) -> dict[str, tuple[float, float, float]]:
    """What one pixel's linear value means: camera-relative density, density above base and relative transmission."""
    v = np.asarray(v_pixel, dtype=np.float64).reshape(3)
    rel = optical_density(v, m.floor)
    net = density_above_base(v, m.base.v, m.floor)
    out = {
        "relative": tuple(float(x) for x in rel),
        "above_base": tuple(float(x) for x in net),
        "t_rel": tuple(float(x) for x in (v / np.asarray(m.base.v))),
    }
    if m.clear is not None:
        out["absolute"] = tuple(float(x) for x in -np.log10(np.maximum(v, 1e-12) / np.asarray(m.clear)))
    return out


def _fmt(values, digits: int = 3) -> tuple[str, ...]:
    return tuple(f"{x:.{digits}f}" for x in values)


def summary_rows(m: Measurement) -> list[Row]:
    """The numbers for the Density panel, as text with their status and a plain explanation each."""
    base_status = "estimated" if not m.base.measured else "measured (sampled)"
    rows = [
        Row("Dmin, camera-relative", _fmt(m.dmin_rel), base_status,
            "Density of the film base in the camera's own scale. It includes the unknown level of your backlight and exposure, so it is not an "
            "absolute density and the three channels are not comparable."),
    ]
    if m.dmin_abs is not None:
        rows.append(Row("Dmin, absolute", _fmt(m.dmin_abs), base_status, "Film-base density measured against the clear backlight: -log10(base / clear). Camera-band density, not Status M."))
    rows += [
        Row("Dmax above base", _fmt(m.dmax.value), "limited by scan" if any(m.dmax.limited) else "measured",
            f"Density above the film base at the {m.dmax.percentile:g}th percentile of the picture. Where marked, the camera set-up reached its noise floor, "
            "so the film itself may be denser."),
        Row("Scan limit above base", _fmt(m.dmax.system_limit), "from noise floor",
            "The highest density above the film base this exposure could register above the noise: log10(base / noise floor)."),
        Row("Density range (base to Dmax)", _fmt(m.density_range()), "derived", "Dmax above base: how much density the picture spans."),
        Row("Transmission, relative to base", tuple(f"{lo:.3f} - {hi:.3f}" for lo, hi in m.t_rel_range), "measured",
            "Light passed relative to the film base (1.0 = as clear as the base). Linear, not logarithmic."),
        Row("Sensor value range", tuple(f"{lo:.4f} - {hi:.4f}" for lo, hi in m.value_range), "measured" if m.info.measured else "assumed",
            "Linear, normalised sensor values (0 = black level, 1 = sensor white) between the 0.1th and 99.9th percentile."),
        Row("Noise floor", _fmt(m.floor, 5), "estimated", "The smallest sensor value told apart from zero: the larger of 3 sigma of read noise and 2 quantisation steps."),
    ]
    return rows


def assumptions(m: Measurement) -> list[str]:
    """The processing assumptions behind the numbers, for the Calibration panel."""
    info = m.info
    out = [
        "Densities are camera-band densities (the camera's R, G, B), not ISO Status M.",
        "The sensor is treated as linear, and flare as negligible except where flagged.",
        "The light source and camera exposure are assumed constant between the base sample and the picture.",
        f"Density is -log10 of the linear value, held at the noise floor ({', '.join(f'{x:.5f}' for x in m.floor)}) so the logarithm stays finite.",
    ]
    if info.measured:
        out.append("The values are RAW sensor data: black level subtracted, divided by the white level, no white balance, colour matrix or tone curve.")
    else:
        out.append(f"The file is an encoded picture; a {info.encoding} transfer function is assumed and undone.")
    return out
