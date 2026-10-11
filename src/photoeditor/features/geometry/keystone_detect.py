"""Suggesting a keystone correction from the straight lines in a picture.

When the camera is tilted, lines that should be parallel lean towards each other. Among the near-vertical lines, the lean grows steadily from the left of the
picture to the right; the rate is the vertical keystone. The near-horizontal lines give the horizontal keystone the same way. A copy stand or a film
carrier gives many long straight edges (the film's border, the frame lines, sprocket holes), so this works best on a scan that shows them; a picture without
straight lines gets no suggestion rather than a wrong one.
"""

import math
from dataclasses import dataclass, field

import numpy as np

from .logic import KEYSTONE_MAX_INSET, keystone

MAX_DIM = 1200
MAX_LEAN_DEG = 20.0
MIN_LINES = 4
MIN_SPAN = 0.35
MIN_AGREEMENT = 0.6
IGNORE_BELOW = 0.02
REFINE_STEPS = 4


@dataclass(frozen=True)
class KeystoneSuggestion:
    v: float
    h: float
    vertical_lines: int
    horizontal_lines: int
    notes: tuple[str, ...] = field(default_factory=tuple)

    def found(self) -> bool:
        return abs(self.v) >= IGNORE_BELOW or abs(self.h) >= IGNORE_BELOW


def _segments(gray: np.ndarray):
    import cv2

    h, w = gray.shape[:2]
    scale = min(1.0, MAX_DIM / max(h, w))
    small = cv2.resize(gray, (max(8, round(w * scale)), max(8, round(h * scale))), interpolation=cv2.INTER_AREA) if scale < 1.0 else gray
    blur = cv2.GaussianBlur(small, (0, 0), 1.2)
    edges = cv2.Canny(blur, 40, 120)
    sh, sw = small.shape[:2]
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=60, minLineLength=int(0.22 * min(sh, sw)), maxLineGap=int(0.02 * max(sh, sw)))
    return ([] if lines is None else lines.reshape(-1, 4)), sw, sh


def _fit(xs: np.ndarray, angles: np.ndarray, weights: np.ndarray):
    """Weighted straight-line fit of the lean against position: returns (slope, share of the lines that agree with it)."""
    design = np.stack([np.ones_like(xs), xs], axis=1)
    sw = np.sqrt(weights)
    coef, *_ = np.linalg.lstsq(design * sw[:, None], angles * sw, rcond=None)
    resid = np.abs(angles - design @ coef)
    tolerance = max(math.radians(0.6), 0.5 * float(np.average(np.abs(angles - np.average(angles, weights=weights)), weights=weights)))
    agree = float((weights * (resid <= tolerance)).sum() / weights.sum())
    return float(coef[1]), agree


def _axis(positions, angles, lengths, label: str, notes: list[str]):
    if len(positions) < MIN_LINES:
        notes.append(f"Too few straight {label} lines to judge ({len(positions)}).")
        return 0.0, len(positions)
    xs, an, wt = np.asarray(positions), np.asarray(angles), np.asarray(lengths)
    if float(xs.max() - xs.min()) < MIN_SPAN * 2.0:
        notes.append(f"The {label} lines are all in one part of the picture, so their lean cannot be compared.")
        return 0.0, len(positions)
    slope, agree = _fit(xs, an, wt)
    if agree < MIN_AGREEMENT:
        notes.append(f"The {label} lines do not lean consistently, so no {label} correction is suggested.")
        return 0.0, len(positions)
    return slope, len(positions)


def _measure(gray: np.ndarray) -> KeystoneSuggestion:
    segs, w, h = _segments(gray)
    vx, va, vl, hy, ha, hl = [], [], [], [], [], []
    for x1, y1, x2, y2 in segs:
        dx, dy = float(x2 - x1), float(y2 - y1)
        length = math.hypot(dx, dy)
        if length < 1:
            continue
        lean_v = math.degrees(math.atan2(dx, dy))
        lean_v = (lean_v + 90.0) % 180.0 - 90.0
        lean_h = math.degrees(math.atan2(dy, dx))
        lean_h = (lean_h + 90.0) % 180.0 - 90.0
        if abs(lean_v) <= MAX_LEAN_DEG:
            vx.append(((x1 + x2) / 2.0 - w / 2.0) / (w / 2.0))
            va.append(math.radians(lean_v))
            vl.append(length)
        elif abs(lean_h) <= MAX_LEAN_DEG:
            hy.append(((y1 + y2) / 2.0 - h / 2.0) / (h / 2.0))
            ha.append(math.radians(lean_h))
            hl.append(length)
    notes: list[str] = []
    cv, nv = _axis(vx, va, vl, "vertical", notes)
    ch, nh = _axis(hy, ha, hl, "horizontal", notes)
    v = max(-1.0, min(1.0, cv * h / w / KEYSTONE_MAX_INSET))
    hz = max(-1.0, min(1.0, ch * w / h / KEYSTONE_MAX_INSET))
    return KeystoneSuggestion(v, hz, nv, nh, tuple(notes))


def suggest_keystone(gray: np.ndarray) -> KeystoneSuggestion:
    """Look at a single-channel 8-bit picture and suggest vertical and horizontal keystone amounts (each -1 to 1, as the sliders use them). The first
    estimate assumes small tilts, so it is refined: the picture is corrected by it and measured again until little is left."""
    import cv2

    gray = np.ascontiguousarray(gray)
    scale = min(1.0, MAX_DIM / max(gray.shape[:2]))
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1.0 else gray
    first = _measure(small)
    v, hz = first.v, first.h
    for _ in range(REFINE_STEPS):
        if abs(v) < IGNORE_BELOW and abs(hz) < IGNORE_BELOW:
            break
        step = _measure(keystone(small, v, hz))
        if abs(step.v) < 0.01 and abs(step.h) < 0.01:
            break
        v, hz = max(-1.0, min(1.0, v + step.v)), max(-1.0, min(1.0, hz + step.h))
    v = 0.0 if abs(v) < IGNORE_BELOW else round(v, 2)
    hz = 0.0 if abs(hz) < IGNORE_BELOW else round(hz, 2)
    notes = list(first.notes)
    if not (v or hz) and not notes:
        notes.append("The straight lines in this picture are already parallel.")
    return KeystoneSuggestion(v, hz, first.vertical_lines, first.horizontal_lines, tuple(notes))
