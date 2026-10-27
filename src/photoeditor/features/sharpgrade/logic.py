"""Grading how sharp a frame is - numpy + OpenCV, no Qt.

Ported from the Scan Grading of the author's modified NegPy. It grades the shot itself (is what the photographer focused on in focus?), not the scan, and does it with a re-blur test after
Crete et al., "The Blur Effect": blur the picture again and see how much local contrast survives. A sharp frame changes a great deal under a second blur; an already soft one barely changes,
so the comparison is against the frame's own content and means the same thing for completely different scenes, with no reference picture.

It is measured only on the strongest real edges (on a denoised copy, so grain and sensor noise cannot fake one): over a whole frame, in a flat area at high ISO the differences are pure noise
that a box blur wipes out almost entirely, which reads as *maximally sharp*. The strongest 5% of edges are the ones on whatever the frame is focused on, so an intentionally soft background
(a portrait, a bird against open sky) does not drag a correctly focused frame down.
"""

from dataclasses import dataclass

import cv2
import numpy as np

GOOD, WARNING, CRITICAL = "good", "warning", "critical"
SEVERITIES = (GOOD, WARNING, CRITICAL)
WORDS = {GOOD: "Sharp", WARNING: "Soft", CRITICAL: "Blurred"}

MAX_DIM = 700               # the frame is judged at most this wide on its long side
OVERLAY_MAX_DIM = 2100      # the picture the overlay is drawn on, and the size its colours and hover readout are measured at (three times the size the grade is, with the same test scaled to it)

_DENOISE_SIGMA = 1.2        # removed before locating edges, so sensor and grain noise are not mistaken for one
_EDGE_PCT_SUBJECT = 95.0    # the strongest edges only: favours whatever the shot is focused on
_EDGE_PCT_BROAD = 85.0      # a wider sample, to judge a frame with no single subject (a landscape)
_RE_BLUR_KSIZE = 9          # the second blur's kernel: the test's own unit of "a bit blurrier"
_MIN_EDGE_PIXELS = 50       # below this the edge sample is too thin to trust
_MASK_DILATE_PX = 1         # grows each judged pixel into a small blob, or the isolated single pixels do not survive the preview's resize up to the frame's size
_BORDER_TRIM_FRAC = 0.04    # margin left out at each edge: a scanned negative's own border and rebate are a stark edge that is not part of the scene and can dwarf anything in it
_GRADE_CRITICAL = 38.0      # a score below this is "Blurred" ...
_GRADE_WARNING = 60.0       # ... below this "Soft". Found by checking a real photo library: scores fall steadily as a frame is blurred and agree with frames checked by hand

_OVERLAY_ALPHA = 0.75
_OVERLAY_CLIP_PCT = 2.0     # taken off each end before the overlay's colours are stretched, so a few outlier pixels do not wash out the difference between sharp and soft areas
_BAD_TINT = np.array([0.85, 0.1, 0.1], dtype=np.float32)
_MID_TINT = np.array([0.9, 0.65, 0.05], dtype=np.float32)
_GOOD_TINT = np.array([0.15, 0.75, 0.25], dtype=np.float32)


@dataclass(frozen=True)
class SharpnessResult:
    severity: str                   # GOOD, WARNING or CRITICAL
    score: float                    # 0-100, higher is sharper: the severity only says which bucket it fell in, this says where in it
    detail: str                     # one sentence a person can act on
    preview: np.ndarray | None = None   # float [0, 1] per judged pixel (how much of its own contrast survived the second blur), NaN everywhere no edge was judged; at the size the frame was judged at


def to_unit(pixels: np.ndarray) -> np.ndarray:
    """A picture of any depth as float32 in [0, 1]."""
    if pixels.dtype == np.uint8:
        return pixels.astype(np.float32) / 255.0
    if pixels.dtype == np.uint16:
        return pixels.astype(np.float32) / 65535.0
    return pixels.astype(np.float32, copy=False)


def _unjudged(severity: str, detail: str, shape) -> SharpnessResult:
    return SharpnessResult(severity, 0.0, detail, np.full(shape, np.nan, dtype=np.float32))


def grade_sharpness(pixels: np.ndarray, max_dim: int = MAX_DIM, subject_aware: bool = True) -> SharpnessResult:
    """Grade a picture (HxW or HxWx3, uint8, uint16 or float in [0, 1]). `subject_aware` judges the strongest 5% of edges; False a broader 15%, better for a frame with no single subject."""
    img = to_unit(pixels)
    gray = (img.mean(axis=2) if img.ndim == 3 else img).astype(np.float32)
    h, w = gray.shape[:2]
    long_edge = max(h, w)
    scale = max_dim / long_edge if long_edge > max_dim else 1.0
    # the test's own sizes (in pixels) are those of the grade's size, MAX_DIM; at a finer size they grow with it, so the same test is made at a finer scale (the grade itself is always at MAX_DIM,
    # which its thresholds were found at: a finer scale reads higher, so only the overlay, which is stretched over its own range, uses one)
    k = max(1.0, (min(max_dim, long_edge)) / MAX_DIM)
    denoise_sigma, re_blur, min_edge_pixels, dilate_px = _DENOISE_SIGMA * k, max(3, int(round(_RE_BLUR_KSIZE * k)) | 1), int(_MIN_EDGE_PIXELS * k * k), max(1, int(round(_MASK_DILATE_PX * k)))
    small = cv2.resize(gray, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA) if scale != 1.0 else gray

    sh, sw = small.shape[:2]
    m = max(1, int(round(_BORDER_TRIM_FRAC * max(sh, sw))))
    has_margin = sh > 2 * m and sw > 2 * m
    g = small[m:sh - m, m:sw - m] if has_margin else small

    no_detail = _unjudged(CRITICAL, "No sharp detail found anywhere in the frame: check the focus.", small.shape)

    den = cv2.GaussianBlur(g, (0, 0), denoise_sigma)
    gx = cv2.Sobel(den, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(den, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    thr = float(np.percentile(mag, _EDGE_PCT_SUBJECT if subject_aware else _EDGE_PCT_BROAD))
    if thr <= 1e-6:
        return no_detail      # a genuinely featureless frame

    bh = cv2.blur(g, (re_blur, 1))
    bv = cv2.blur(g, (1, re_blur))
    d_h, b_h = np.abs(np.diff(g, axis=1)), np.abs(np.diff(bh, axis=1))
    d_v, b_v = np.abs(np.diff(g, axis=0)), np.abs(np.diff(bv, axis=0))

    m_h = mag[:, :-1] >= thr
    m_v = mag[:-1, :] >= thr
    if int(m_h.sum()) < min_edge_pixels or int(m_v.sum()) < min_edge_pixels:
        return no_detail

    s_h, s_v = float(d_h[m_h].sum()), float(d_v[m_v].sum())
    if s_h <= 0.0 or s_v <= 0.0:
        return no_detail
    v_h = float(np.maximum(0.0, d_h - b_h)[m_h].sum())
    v_v = float(np.maximum(0.0, d_v - b_v)[m_v].sum())

    blur = max((s_h - v_h) / s_h, (s_v - v_v) / s_v)      # the worse of the two directions, so blur in one direction (the camera moved) counts
    grade = float(np.clip(100.0 * (1.0 - blur), 0.0, 100.0))

    # per judged pixel: how much of its own contrast survived the second blur (1 = all of it, 0 = none)
    eps = 1e-6
    local_h = np.clip((d_h - b_h) / (d_h + eps), 0.0, 1.0)
    local_v = np.clip((d_v - b_v) / (d_v + eps), 0.0, 1.0)
    total = np.zeros_like(g)
    count = np.zeros_like(g)
    total[:, :-1][m_h] += local_h[m_h]
    count[:, :-1][m_h] += 1
    total[:-1, :][m_v] += local_v[m_v]
    count[:-1, :][m_v] += 1
    judged = count > 0
    local = np.divide(total, count, out=np.zeros_like(total), where=judged)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * dilate_px + 1, 2 * dilate_px + 1))
    judged_wide = cv2.dilate(judged.astype(np.uint8), kernel) > 0
    local_wide = cv2.dilate(local, kernel)
    preview = np.full(small.shape, np.nan, dtype=np.float32)
    y0, x0 = (m, m) if has_margin else (0, 0)
    preview[y0:y0 + g.shape[0], x0:x0 + g.shape[1]][judged_wide] = local_wide[judged_wide]

    if grade < _GRADE_CRITICAL:
        return SharpnessResult(CRITICAL, grade, "No sharp detail found anywhere in the frame: check the focus.", preview)
    if grade < _GRADE_WARNING:
        return SharpnessResult(WARNING, grade, "The frame reads soft overall: worth a check for focus or motion blur.", preview)
    return SharpnessResult(GOOD, grade, "Sharp, resolved detail throughout the frame.", preview)


def severity_of(score: float) -> str:
    return CRITICAL if score < _GRADE_CRITICAL else WARNING if score < _GRADE_WARNING else GOOD


def summary(grades: dict) -> str:
    """One line about a roll: how many frames are graded and how they came out ({path: (severity, score)})."""
    if not grades:
        return "No frames graded yet."
    counts = {s: sum(1 for v in grades.values() if v[0] == s) for s in SEVERITIES}
    parts = [f"{counts[s]} {WORDS[s].lower()}" for s in SEVERITIES if counts[s]]
    return f"{len(grades)} graded: " + ", ".join(parts) + "."


# ---------------------------------------------------------------- the overlay: where the grade was measured
def gray_frame(pixels: np.ndarray, max_dim: int = OVERLAY_MAX_DIM) -> np.ndarray:
    """The frame as float gray in [0, 1], stretched, at the size the overlay is drawn at."""
    img = to_unit(pixels)
    gray = (img.mean(axis=2) if img.ndim == 3 else img).astype(np.float32)
    h, w = gray.shape[:2]
    if max(h, w) > max_dim:
        k = max_dim / max(h, w)
        gray = cv2.resize(gray, (max(1, int(w * k)), max(1, int(h * k))), interpolation=cv2.INTER_AREA)
    lo, hi = float(gray.min()), float(gray.max())
    return np.zeros_like(gray) if hi - lo < 1e-8 else (gray - lo) / (hi - lo)


def plain_rgb(gray: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(np.repeat((gray * 255.0).astype(np.uint8)[..., None], 3, axis=2))


def overlay_norm(gray: np.ndarray, heatmap: np.ndarray) -> np.ndarray:
    """The preview resampled to the overlay's size and stretched to [0, 1]: the one array both the colours and the hover readout read, so what you see is what you read. NaN (no edge was
    judged there) survives the resize and the stretch."""
    hm = cv2.resize(heatmap.astype(np.float32), (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_LINEAR)
    h, w = hm.shape[:2]
    m = max(1, int(round(_BORDER_TRIM_FRAC * max(h, w))))
    interior = hm[m:h - m, m:w - m] if h > 2 * m and w > 2 * m else hm
    if not np.isfinite(interior).any():
        return np.full_like(hm, np.nan)
    lo, hi = np.nanpercentile(interior, _OVERLAY_CLIP_PCT), np.nanpercentile(interior, 100.0 - _OVERLAY_CLIP_PCT)
    if hi - lo < 1e-8:
        return np.where(np.isfinite(hm), 0.5, np.nan).astype(np.float32)      # they agree exactly: a flat middle colour, not a false "worst"
    return np.clip((hm - lo) / (hi - lo), 0.0, 1.0)


def tinted_rgb(gray: np.ndarray, norm: np.ndarray) -> np.ndarray:
    """The frame with `norm` laid over it as red (soft) through amber to green (sharp), only where an edge was judged: everywhere else stays plain gray, since no verdict was reached there."""
    valid = np.isfinite(norm)
    safe = np.where(valid, norm, 0.5)
    low = safe < 0.5
    t = np.where(low, safe * 2.0, (safe - 0.5) * 2.0)[..., None]
    tint = np.where(low[..., None], _BAD_TINT * (1.0 - t) + _MID_TINT * t, _MID_TINT * (1.0 - t) + _GOOD_TINT * t)
    base = np.repeat(gray[..., None], 3, axis=2)
    mixed = np.clip(base * (1.0 - _OVERLAY_ALPHA) + tint * _OVERLAY_ALPHA, 0.0, 1.0)
    return np.ascontiguousarray((np.where(valid[..., None], mixed, base) * 255.0).astype(np.uint8))
