"""Roll consistency: did the light, the exposure or the colour change between the scans of one roll?

Every scan of a roll should show the same film base. A frame whose film base reads brighter, darker or tinted compared with the rest was scanned under
different conditions, and its conversion will not match its neighbours. The film base is taken from the frame's clear border where one can be found and
otherwise estimated from the thinnest part of the picture, which depends on the scene, so estimated values are judged more leniently.
Numpy only, no Qt/UI imports.
"""

from dataclasses import dataclass

import numpy as np

from . import base as base_mod
from . import rebate as rebate_mod
from .linear import ScanInfo

MIN_FRAMES = 3
LIGHT_NOTE, LIGHT_WARN = 0.12, 0.25
TINT_NOTE, TINT_WARN = 0.10, 0.20
ESTIMATE_LENIENCY = 2.0
CLIP_WARN = 0.005
CENTRE = 0.1


@dataclass(frozen=True)
class FrameStats:
    label: str
    base: tuple[float, float, float]
    source: str
    clipped: float


@dataclass(frozen=True)
class FrameCheck:
    label: str
    light_stops: float
    tint_r: float
    tint_b: float
    source: str
    level: str
    notes: tuple[str, ...]


@dataclass(frozen=True)
class RollReport:
    frames: tuple[FrameCheck, ...]
    level: str
    headline: str
    detail: str
    reference: tuple[float, float, float] | None
    reference_source: str


def frame_stats(label: str, rgb: np.ndarray, info: ScanInfo) -> FrameStats:
    """The film base of one frame (from its clear border when found, else estimated) and how much of it is clipped."""
    floor = info.floor()
    h, w = rgb.shape[:2]
    step = max(1, int(np.ceil(np.sqrt(h * w / 600_000))))
    sub = rgb[::step, ::step]
    dy, dx = int(sub.shape[0] * CENTRE), int(sub.shape[1] * CENTRE)
    centre = sub[dy:sub.shape[0] - dy, dx:sub.shape[1] - dx]
    clipped = float((centre >= 0.999).any(axis=2).mean())
    found = rebate_mod.find_rebate(rgb, floor)
    if found is not None and found.confidence in ("high", "medium"):
        return FrameStats(label, tuple(float(x) for x in found.v), "border", clipped)
    return FrameStats(label, base_mod.estimate_base(centre, floor).v, "estimated", clipped)


def _log2(x: float) -> float:
    return float(np.log2(max(x, 1e-9)))


def compare(frames: list[FrameStats], reference=None) -> RollReport:
    """Compare every frame's film base with the roll's. `reference` is a sampled film base (linear); without one, the roll's median is used."""
    if len(frames) < MIN_FRAMES and reference is None:
        return RollReport((), "unknown", "Too few frames to compare", f"Consistency needs at least {MIN_FRAMES} scanned frames of the same roll.", None, "none")
    if not frames:
        return RollReport((), "unknown", "No frames to compare", "No RAW scans were found in this folder.", None, "none")
    if reference is not None:
        ref, ref_source = np.asarray(reference, dtype=np.float64), "the film base sampled for this roll"
    else:
        pool = [f for f in frames if f.source == "border"]
        pool = pool if len(pool) >= 2 else frames
        ref = np.exp(np.median(np.log(np.maximum([f.base for f in pool], 1e-9)), axis=0))
        ref_source = "the median film base of the frames" + (" with a clear border" if pool is not frames else "")
    out = []
    for f in frames:
        b = np.asarray(f.base, dtype=np.float64)
        stops = _log2(b[1] / ref[1])
        tr = _log2((b[0] / b[1]) / (ref[0] / ref[1]))
        tb = _log2((b[2] / b[1]) / (ref[2] / ref[1]))
        k = ESTIMATE_LENIENCY if f.source == "estimated" else 1.0
        notes, level = [], "ok"

        def raise_to(new):
            nonlocal level
            level = new if ["ok", "note", "warning"].index(new) > ["ok", "note", "warning"].index(level) else level

        if abs(stops) >= LIGHT_WARN * k:
            notes.append(f"{'Brighter' if stops > 0 else 'Darker'} than the roll by {abs(stops):.2f} stops. The light or exposure probably changed for this scan.")
            raise_to("warning")
        elif abs(stops) >= LIGHT_NOTE * k:
            notes.append(f"{'Slightly brighter' if stops > 0 else 'Slightly darker'} than the roll ({abs(stops):.2f} stops).")
            raise_to("note")
        worst = max(abs(tr), abs(tb))
        if worst >= TINT_WARN * k:
            notes.append(f"Colour differs from the roll (red {tr:+.2f}, blue {tb:+.2f} stops against green). The light's colour or the white balance probably changed.")
            raise_to("warning")
        elif worst >= TINT_NOTE * k:
            notes.append(f"Colour is slightly different from the roll (red {tr:+.2f}, blue {tb:+.2f}).")
            raise_to("note")
        if f.clipped > CLIP_WARN:
            notes.append(f"{f.clipped * 100:.1f}% of this scan is clipped white.")
            raise_to("warning")
        if f.source == "estimated" and level != "ok":
            notes.append("This frame has no clear border, so its film base was estimated from the picture: the difference may be the scene rather than the scan.")
        out.append(FrameCheck(f.label, stops, tr, tb, f.source, level, tuple(notes)))
    bad = [c for c in out if c.level == "warning"]
    mild = [c for c in out if c.level == "note"]
    if bad:
        level = "warning"
        headline = f"{len(bad)} of {len(out)} frames were scanned differently from the rest"
        detail = "Their conversions will not match their neighbours unless the scan is repeated under the same settings, or each is corrected by hand."
    elif mild:
        level, headline = "note", f"{len(mild)} of {len(out)} frames differ slightly"
        detail = "Small differences are normal. They are worth knowing about only if the conversions look uneven."
    else:
        level, headline = "ok", f"All {len(out)} frames are consistent"
        detail = "The film base reads the same in every frame, so the same conversion settings should suit the whole roll."
    return RollReport(tuple(out), level, headline, detail + f" Compared with {ref_source}.", tuple(float(x) for x in ref), ref_source)
