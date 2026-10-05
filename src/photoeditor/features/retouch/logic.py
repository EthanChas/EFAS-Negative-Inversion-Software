"""Dust and scratch removal - numpy + OpenCV only, no Qt/UI imports.

Ported from NegPy's retouch module (negpy/features/retouch/logic.py): the
statistical "optical" dust detector, the score-weighted multiscale fill that
repairs specks, Navier-Stokes inpaint for hair-shaped defects, and
click-to-trace transport-scratch repair. NegPy's infrared-channel routes,
painted heal strokes and Smart Heal are left out (no IR plane here, and no
brush tools yet), and its numba kernels are plain numpy.

Everything runs on the raw scan, before inversion: dust and scratches block
light, so they're dark in the scan whether it's a negative or a slide. The
sRGB bytes are linearized with a 2.2 gamma for detection and filling, since
averaging is only meaningful in linear light. OpenCV is imported lazily."""

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

_cv2 = None


def _cv():
    global _cv2
    if _cv2 is None:
        import cv2

        _cv2 = cv2
    return _cv2


# Adobe RGB (1998) luminance row, as NegPy uses for its detection proxy.
_LUMA = (0.2973769, 0.6273491, 0.0752741)
_GAMMA = 2.2

_PROXY_MIN_SPREAD = 0.8
_DETECT_PAD_PX = 2.5
_DETECT_AVG_PX = 3
_DETECT_MAD_GAIN = 4.0
_DETECT_SIGMA_MIN = 0.003
_DETECT_Z_LOOSE = 3.0
_DETECT_Z_DEFAULT = 9.0
_DETECT_Z_TIGHT = 48.0
_DETECT_DEFAULT_POS = 0.66
_DETECT_Z_GROW = 2.5
_DETECT_Z_GROW_FRAC = 0.3
_DETECT_GROW_REACH = 2
_DETECT_TEXTURE_KNEE = 0.02
_DETECT_TEXTURE_GAIN = 40.0
_DETECT_PROXY_MIN = 0.15

_SCRATCH_FINE_PX = 1.2
_SCRATCH_BROAD_PX = 9.0
_SCRATCH_NOISE_WIN = 151
_SCRATCH_SLOPE_MAX = 0.02
_SCRATCH_SLOPE_STEP = 0.00025
_SCRATCH_SEARCH_ROWS = 30
_SCRATCH_CLICK_PULL = 12.0
_SCRATCH_Z_LOOSE = 0.4
_SCRATCH_Z_TIGHT = 1.6
_SCRATCH_RUN_WIN = 151
_SCRATCH_RUN_FRAC = 0.35
_SCRATCH_MIN_EVIDENCE = 0.25
_SCRATCH_WIDTH_MAX = 14.0
_SCRATCH_WIDTH_MIN = 3.0
_SCRATCH_RIDGE_REACH = 128

_DETECT_REF = 1600  # detection long edge (NegPy's _IR_DETECT_REF) the film-scale windows are pinned to
_SCORE_FLOOR = 0.02
_FILL_SCALES = (9, 5, 3)
_FILL_TAU = 0.15
_WRITE_HI = 0.85
_WRITE_LO = 0.40
_REPAIR_MAX_COMPONENTS = 256

_HAIR_MIN_AREA = 20
_HAIR_MIN_ELONG = 8.0
_HAIR_DILATE_PX = 1
_HAIR_INPAINT_RADIUS = 3
_HAIR_INPAINT_GAMMA = 2.2
_HAIR_RANGE_SAMPLE_PX = 1 << 20
_HAIR_TILE_PX = 1024
_HAIR_TILE_HALO = 32
_HAIR_INPAINT_PAD = 16

# Manual heal gate: a painted stroke marks a *search area*, not a stamp - only
# pixels that stand out from the film around them are repaired.
_MANUAL_Z_HI = 8.0
_MANUAL_Z_GROW = 2.0
_MANUAL_Z_GROW_FRAC = 0.25
_MANUAL_Z_MIN = 5.0
_MANUAL_WIN_FACTOR = 3.0
_MANUAL_RIM_PX = 1.5
_MANUAL_SENS_MULT_LOOSE = 0.2
_MANUAL_SENS_MULT_TIGHT = 1.8
HEAL_SIZE_REF = 1600  # brush size is a diameter at this reference long edge (px)
SMART_HEAL_SEARCH_SIZE = 40.0
_ROUTE_RADIUS = 5
_ROUTE_DILATE = 2

REPAIR_AUTO = "auto"
REPAIR_SMOOTH = "smooth"
REPAIR_STRUCTURE = "structure"
REPAIR_METHODS = (REPAIR_AUTO, REPAIR_SMOOTH, REPAIR_STRUCTURE)

DUST_SIZE_RANGE = (3, 8)
BRUSH_SIZE_RANGE = (2, 16)
DEFAULT_BRUSH_SIZE = 6
DEFAULT_MANUAL_SENSITIVITY = 0.5
DEFAULT_THRESHOLD = 0.66
DEFAULT_SIZE = 4
DEFAULT_SCRATCH_SENSITIVITY = 0.5


# ---------------------------------------------------------------- detection


def _density(lin: np.ndarray) -> np.ndarray:
    luma = lin[..., 0] * _LUMA[0] + lin[..., 1] * _LUMA[1] + lin[..., 2] * _LUMA[2]
    return -np.log10(np.clip(luma, 1e-6, None)).astype(np.float32)


def film_scale(shape: Tuple[int, int]) -> float:
    return max(1.0, max(shape) / _DETECT_REF)


def _u8(plane: np.ndarray) -> np.ndarray:
    return (np.clip(plane, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def _box_mean_std(plane: np.ndarray, win: int) -> Tuple[np.ndarray, np.ndarray]:
    cv2 = _cv()
    mean = cv2.blur(plane, (win, win))
    var = cv2.blur(plane * plane, (win, win)) - mean * mean
    return mean, np.sqrt(np.clip(var, 0.0, None))


def _proxy_norm(lin: np.ndarray) -> Tuple[float, float]:
    dens = _density(lin)
    lo, hi = np.percentile(dens, (0.5, 99.5))
    return float(lo), max(float(hi - lo), _PROXY_MIN_SPREAD)


def _is_hair(labels_sub: np.ndarray, area: int) -> bool:
    """Thin (hair/scratch) rather than a speck: area / thickness^2 reads as
    length / thickness for a ribbon, and bending doesn't change it."""
    if area < _HAIR_MIN_AREA:
        return False
    cv2 = _cv()
    dist = cv2.distanceTransform(np.pad(labels_sub.astype(np.uint8), 1), cv2.DIST_L2, 5)
    thickness = 2.0 * float(dist.max())
    return area / max(thickness * thickness, 1e-6) >= _HAIR_MIN_ELONG


def _mask_to_score(mask: np.ndarray, pad_px: float) -> np.ndarray:
    """Binary defect mask -> a continuous score: at the floor on the defect,
    ramping to clean over pad_px, so the repair has no hard edge to halo."""
    cv2 = _cv()
    d = cv2.distanceTransform((np.asarray(mask) == 0).astype(np.uint8), cv2.DIST_L2, 3)
    t = np.clip(d / max(pad_px, 1e-3), 0.0, 1.0)
    return (_SCORE_FLOOR + (1.0 - _SCORE_FLOOR) * (t * t * (3.0 - 2.0 * t))).astype(np.float32)


def split_hairs(mask: np.ndarray) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """Defect mask -> (compact specks, hair-shaped defects or None)."""
    cv2 = _cv()
    n_lbl, labels, stats, _ = cv2.connectedComponentsWithStats(np.ascontiguousarray(mask, dtype=np.uint8), connectivity=8)
    compact = np.zeros(mask.shape[:2], dtype=np.uint8)
    hairs: Optional[np.ndarray] = None
    for i in range(1, n_lbl):
        x0, y0 = int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP])
        bw, bh = int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT])
        labels_sub = labels[y0 : y0 + bh, x0 : x0 + bw] == i
        if _is_hair(labels_sub, int(stats[i, cv2.CC_STAT_AREA])):
            if hairs is None:
                hairs = np.zeros(mask.shape[:2], dtype=np.uint8)
            hairs[y0 : y0 + bh, x0 : x0 + bw][labels_sub] = 1
        else:
            compact[y0 : y0 + bh, x0 : x0 + bw][labels_sub] = 1
    return compact, hairs


def compute_dust_stats(lin: np.ndarray, dust_size: int) -> Tuple[np.ndarray, ...]:
    """Threshold-independent detection maps (proxy, background, z, texture) -
    the expensive part, cacheable across threshold changes."""
    cv2 = _cv()
    lo, spread = _proxy_norm(lin)
    proxy = np.clip((_density(lin) - lo) / spread, 0.0, 1.0).astype(np.float32)
    base_size = max(1.0, float(dust_size)) * film_scale(proxy.shape)
    v_win = int(max(3, base_size * 3.0)) * 2 + 1
    w_win = int(max(7, base_size * 4.0)) * 2 + 1
    disk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * int(round(base_size)) + 1,) * 2)
    background = np.maximum(
        cv2.medianBlur(_u8(proxy), v_win).astype(np.float32) / 255.0, cv2.morphologyEx(proxy, cv2.MORPH_OPEN, disk)
    )
    excess = cv2.blur(proxy - background, (_DETECT_AVG_PX, _DETECT_AVG_PX))
    mad = cv2.medianBlur(_u8(np.abs(excess) * _DETECT_MAD_GAIN), w_win).astype(np.float32) / (255.0 * _DETECT_MAD_GAIN)
    z = excess / np.maximum(mad / 0.6745, _DETECT_SIGMA_MIN)
    _, texture = _box_mean_std(proxy, w_win)
    return tuple(np.ascontiguousarray(a.astype(np.float32)) for a in (proxy, background, z, texture))


def detect_bar(slider: float) -> float:
    """UI threshold (higher = more conservative) -> seed bar in local sigma."""
    s = float(np.clip(slider, 0.0, 1.0))
    if s <= _DETECT_DEFAULT_POS:
        return _DETECT_Z_LOOSE + (_DETECT_Z_DEFAULT - _DETECT_Z_LOOSE) * s / _DETECT_DEFAULT_POS
    t = (s - _DETECT_DEFAULT_POS) / (1.0 - _DETECT_DEFAULT_POS)
    return _DETECT_Z_DEFAULT * (_DETECT_Z_TIGHT / _DETECT_Z_DEFAULT) ** t


def detect_luma_score(
    lin: np.ndarray, dust_threshold: float, dust_size: int, stats: Optional[Tuple[np.ndarray, ...]] = None
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """Statistical dust detection -> (score, hair_mask). Seeds above the
    threshold's bar grow through connected pixels down to a lower bar, so a
    mark covers the defect's footprint rather than its brightest pixel."""
    cv2 = _cv()
    if stats is None:
        stats = compute_dust_stats(lin, dust_size)
    proxy, _, z, texture = stats[:4]
    hi = detect_bar(dust_threshold)
    seeds = (z >= hi) & (proxy > _DETECT_PROXY_MIN)
    if not np.any(seeds):
        return None, None
    scale = film_scale(proxy.shape)
    lo = max(_DETECT_Z_GROW, hi * _DETECT_Z_GROW_FRAC)
    reach = int(round(_DETECT_GROW_REACH * max(1, dust_size) * scale))
    near = cv2.dilate(seeds.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * reach + 1,) * 2)) > 0
    n_lbl, lab, stats_cc, _ = cv2.connectedComponentsWithStats((near & (z >= lo)).astype(np.uint8), connectivity=8)
    bar = hi * (1.0 + _DETECT_TEXTURE_GAIN * np.maximum(texture - _DETECT_TEXTURE_KNEE, 0.0))
    strong = np.zeros(n_lbl, dtype=bool)
    strong[np.unique(lab[seeds & (z >= bar)])] = True
    seeded = np.zeros(n_lbl, dtype=bool)
    seeded[np.unique(lab[seeds])] = True
    keep = np.zeros(n_lbl, dtype=bool)
    for i in np.flatnonzero(seeded[1:]) + 1:
        x0, y0 = int(stats_cc[i, cv2.CC_STAT_LEFT]), int(stats_cc[i, cv2.CC_STAT_TOP])
        bw, bh = int(stats_cc[i, cv2.CC_STAT_WIDTH]), int(stats_cc[i, cv2.CC_STAT_HEIGHT])
        keep[i] = strong[i] or _is_hair(lab[y0 : y0 + bh, x0 : x0 + bw] == i, int(stats_cc[i, cv2.CC_STAT_AREA]))
    if not keep.any():
        return None, None
    hit = keep[lab].astype(np.uint8)
    compact, hair_mask = split_hairs(hit)
    score = _mask_to_score(compact, _DETECT_PAD_PX * scale) if compact.any() else None
    return score, hair_mask


def _min_pool(lin: np.ndarray, target_long_edge: int) -> np.ndarray:
    """Min-preserving downsample for detection: a speck is a minimum in
    transmittance, and plain area averaging dilutes it below the grain."""
    cv2 = _cv()
    h, w = lin.shape[:2]
    long_edge = max(h, w)
    if long_edge <= target_long_edge:
        return lin
    s = target_long_edge / long_edge
    dims = (max(1, int(round(w * s))), max(1, int(round(h * s))))
    k = max(1, int(round(long_edge / target_long_edge)) | 1)
    if k > 1:
        lin = cv2.erode(lin, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    return cv2.resize(lin, dims, interpolation=cv2.INTER_AREA).astype(np.float32)


# ------------------------------------------------------------------- repair


def _score_weighted_fill(img: np.ndarray, score: np.ndarray, scales: Tuple[int, ...], reject_floor_mass: bool) -> np.ndarray:
    """Multiscale score-normalized average, blended coarse to fine by each
    rung's clean fraction."""
    cv2 = _cv()
    weighted = img * score[..., None]
    fill = np.empty_like(img)
    inv_span = 1.0 - _SCORE_FLOOR
    for i, k in enumerate(scales):
        if i == len(scales) - 1:
            num = cv2.GaussianBlur(weighted, (k, k), 0)
            den = cv2.GaussianBlur(score, (k, k), 0)
        else:
            num = cv2.boxFilter(weighted, -1, (k, k))
            den = cv2.boxFilter(score, -1, (k, k))
        cand = num / np.maximum(den, 1e-6)[..., None]
        if i == 0:
            fill[:] = cand
        else:
            mass = (den - _SCORE_FLOOR) / inv_span if reject_floor_mass else den
            conf = np.clip(mass / _FILL_TAU, 0.0, 1.0)[..., None]
            fill[:] = fill * (1.0 - conf) + cand * conf
    return fill


def _fill_supports(buffer_long_edge: int, factor: float) -> Tuple[int, ...]:
    fine = [int(round(k * factor)) | 1 for k in _FILL_SCALES]
    film = max(factor, buffer_long_edge / _DETECT_REF)
    return tuple(dict.fromkeys([int(round(_FILL_SCALES[0] * film)) | 1] + fine))


def _borrow_clean_grain(src: np.ndarray, clean: np.ndarray, sigma: float, idx: np.ndarray):
    """Detail of the nearest clean pixel (high-passed at sigma) for the flat
    indices idx - real film grain, not synthesized noise."""
    cv2 = _cv()
    h, w = clean.shape
    _, labels = cv2.distanceTransformWithLabels((~clean).astype(np.uint8), cv2.DIST_L2, 3, labelType=cv2.DIST_LABEL_PIXEL)
    nearest = np.flatnonzero(clean.ravel())[labels.ravel()[idx].astype(np.intp) - 1]
    ny, nx = np.divmod(nearest, w)
    py, px = np.divmod(idx, w)
    mirrored = np.clip(2 * ny - py, 0, h - 1) * w + np.clip(2 * nx - px, 0, w - 1)
    take = np.where(clean.ravel()[mirrored], mirrored, nearest)
    blur = cv2.GaussianBlur(src, (0, 0), sigma)
    return src.reshape(-1, 3)[take] - blur.reshape(-1, 3)[take], blur


def _apply_score_repair(
    img: np.ndarray,
    score_det: np.ndarray,
    *,
    floor: bool = True,
    long_edge: Optional[int] = None,
    factor: Optional[float] = None,
) -> np.ndarray:
    cv2 = _cv()
    h, w = img.shape[:2]
    src = np.ascontiguousarray(img, dtype=np.float32)
    if score_det.shape[:2] == (h, w):
        score = np.ascontiguousarray(score_det, dtype=np.float32)
        factor = factor or 1.0
    else:
        factor = max(h / score_det.shape[0], w / score_det.shape[1])
        score = cv2.resize(score_det, (w, h), interpolation=cv2.INTER_LINEAR)
    out = _score_weighted_fill(src, score, _fill_supports(long_edge or max(h, w), factor), reject_floor_mass=not floor)

    a = np.clip((_WRITE_HI - score) / (_WRITE_HI - _WRITE_LO), 0.0, 1.0)
    a = (a * a * (3.0 - 2.0 * a)).astype(np.float32)
    out = src * (1.0 - a[..., None]) + out * a[..., None]

    sigma = max(1.0, factor)
    clean = score >= _WRITE_HI
    idx = np.flatnonzero(~clean)
    blur_src = None
    if clean.any() and idx.size:
        grain, blur_src = _borrow_clean_grain(src, clean, sigma, idx)
        out.reshape(-1, 3)[idx] += a.reshape(-1, 1)[idx] * grain
    if floor:
        # Dust is dark in the scan, so a repair may only lighten - compared on
        # the low-frequency deficit so the fill's grain isn't half-rectified.
        if blur_src is None:
            blur_src = cv2.GaussianBlur(src, (0, 0), sigma)
        deficit = np.maximum(blur_src - cv2.GaussianBlur(out, (0, 0), sigma), 0.0)
        out = np.maximum(out + a[..., None] * deficit, 0.0)
    else:
        np.maximum(out, 0.0, out=out)
    return out


def _repair_components(
    img: np.ndarray, score_det: np.ndarray, *, floor: bool = True, factor: Optional[float] = None
) -> np.ndarray:
    """_apply_score_repair per defect, each in its own padded crop - the fill
    is several convolutions, wasteful over a whole frame to repair a handful
    of specks."""
    cv2 = _cv()
    h, w = img.shape[:2]
    if score_det.shape[:2] == (h, w):
        score = np.ascontiguousarray(score_det, dtype=np.float32)
        factor = factor or 1.0
    else:
        factor = max(h / score_det.shape[0], w / score_det.shape[1])
        score = cv2.resize(score_det, (w, h), interpolation=cv2.INTER_LINEAR)
    m = (score < 1.0).astype(np.uint8)
    if not m.any():
        return img
    n_lbl, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n_lbl - 1 > _REPAIR_MAX_COMPONENTS:
        return _apply_score_repair(img, score, floor=floor, factor=factor)
    src = np.ascontiguousarray(img, dtype=np.float32)
    out = src.copy()
    pad = max(_fill_supports(max(h, w), factor))
    for i in range(1, n_lbl):
        bx, by = int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP])
        cw, ch = int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT])
        x0, y0 = max(0, bx - pad), max(0, by - pad)
        x1, y1 = min(w, bx + cw + pad), min(h, by + ch + pad)
        sub = _apply_score_repair(src[y0:y1, x0:x1], score[y0:y1, x0:x1], floor=floor, long_edge=max(h, w), factor=factor)
        mb = labels[y0:y1, x0:x1] == i
        out[y0:y1, x0:x1][mb] = sub[mb]
    return out


def _apply_hair_inpaint(img: np.ndarray, hair_mask: np.ndarray) -> np.ndarray:
    """Structure-following fill of long/twisted defects (Navier-Stokes
    inpaint), then real grain borrowed back so the fill isn't smooth."""
    cv2 = _cv()
    h, w = img.shape[:2]
    factor = max(1.0, h / hair_mask.shape[0], w / hair_mask.shape[1])
    dilate_px = max(_HAIR_DILATE_PX, round(factor))
    if hair_mask.shape[:2] == (h, w):
        m = (hair_mask > 0).astype(np.uint8)
    else:
        m = (cv2.resize(hair_mask.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR) > 0.5).astype(np.uint8)
    if not m.any():
        return img
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * dilate_px + 1, 2 * dilate_px + 1))
    m = cv2.dilate(m, k)
    src = np.ascontiguousarray(img, dtype=np.float32)
    out = src.copy()
    n_lbl, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    inv_gamma = 1.0 / _HAIR_INPAINT_GAMMA
    for i in range(1, n_lbl):
        bx, by = int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP])
        x0, y0 = max(0, bx - _HAIR_INPAINT_PAD), max(0, by - _HAIR_INPAINT_PAD)
        x1 = min(w, bx + int(stats[i, cv2.CC_STAT_WIDTH]) + _HAIR_INPAINT_PAD)
        y1 = min(h, by + int(stats[i, cv2.CC_STAT_HEIGHT]) + _HAIR_INPAINT_PAD)
        sub_m = np.ascontiguousarray(m[y0:y1, x0:x1])
        crop = np.ascontiguousarray(src[y0:y1, x0:x1])
        step = max(1, int(math.isqrt(max(1, crop.shape[0] * crop.shape[1] // _HAIR_RANGE_SAMPLE_PX))))
        ctx = crop[::step, ::step][sub_m[::step, ::step] == 0]
        lo = float(np.percentile(ctx, 0.5)) if ctx.size else 0.0
        hi = float(np.percentile(ctx, 99.5)) if ctx.size else 1.0
        span = max(hi - lo, 1e-4)
        dec_lut = ((np.arange(256, dtype=np.float32) / 255.0) ** _HAIR_INPAINT_GAMMA) * span + lo
        ch, cw = crop.shape[:2]
        for ty0 in range(0, ch, _HAIR_TILE_PX):
            for tx0 in range(0, cw, _HAIR_TILE_PX):
                ty1, tx1 = min(ch, ty0 + _HAIR_TILE_PX), min(cw, tx0 + _HAIR_TILE_PX)
                if not (labels[y0 + ty0 : y0 + ty1, x0 + tx0 : x0 + tx1] == i).any():
                    continue
                ay0, ay1 = max(0, ty0 - _HAIR_TILE_HALO), min(ch, ty1 + _HAIR_TILE_HALO)
                ax0, ax1 = max(0, tx0 - _HAIR_TILE_HALO), min(cw, tx1 + _HAIR_TILE_HALO)
                tile = np.ascontiguousarray(crop[ay0:ay1, ax0:ax1])
                enc = (np.clip((tile - lo) / span, 0.0, 1.0) ** inv_gamma * 255.0 + 0.5).astype(np.uint8)
                filled = cv2.inpaint(enc, np.ascontiguousarray(sub_m[ay0:ay1, ax0:ax1]), _HAIR_INPAINT_RADIUS, cv2.INPAINT_NS)
                mb = labels[y0 + ay0 : y0 + ay1, x0 + ax0 : x0 + ax1] == i
                d = cv2.distanceTransform(mb.astype(np.uint8), cv2.DIST_C, 3)
                core = np.zeros(mb.shape, dtype=bool)
                core[ty0 - ay0 : ty1 - ay0, tx0 - ax0 : tx1 - ax0] = True
                sel = np.flatnonzero(mb & core)
                a = np.minimum(d.ravel()[sel] / float(dilate_px + 1), 1.0)[:, None]
                dec = dec_lut[filled.reshape(-1, 3)[sel]]
                tile_px = tile.reshape(-1, 3)[sel]
                ry, rx = np.divmod(sel, ax1 - ax0)
                out.reshape(-1, 3)[(y0 + ay0 + ry) * w + (x0 + ax0 + rx)] = tile_px * (1.0 - a) + dec * a
    idx = np.flatnonzero(m)
    clean = m == 0
    if clean.any() and idx.size:
        out.reshape(-1, 3)[idx] += _borrow_clean_grain(src, clean, max(1.0, factor), idx)[0]
    return out


# ---------------------------------------------------------------- scratches


def scratch_detect_bar(slider: float) -> float:
    s = float(np.clip(slider, 0.0, 1.0))
    return _SCRATCH_Z_LOOSE + (_SCRATCH_Z_TIGHT - _SCRATCH_Z_LOOSE) * s


def _scratch_ridge(lin: np.ndarray) -> np.ndarray:
    """Cross-section ridge response in units of the local noise: band-passed
    across the scratch (grain is finer, image structure broader)."""
    cv2 = _cv()
    dens = _density(lin)
    fine = cv2.GaussianBlur(dens, (1, 0), sigmaX=0, sigmaY=_SCRATCH_FINE_PX)
    broad = cv2.GaussianBlur(dens, (1, 0), sigmaX=0, sigmaY=_SCRATCH_BROAD_PX)
    ridge = fine - broad
    scale = cv2.blur(np.abs(ridge), (_SCRATCH_NOISE_WIN, _SCRATCH_NOISE_WIN)) / 0.8
    return ridge / np.maximum(scale, 1e-6)


def _scratch_ridge_rows(lin: np.ndarray, r0: int, r1: int) -> Tuple[np.ndarray, int]:
    h = lin.shape[0]
    a, b = max(0, r0 - _SCRATCH_RIDGE_REACH), min(h, r1 + _SCRATCH_RIDGE_REACH)
    return _scratch_ridge(lin[a:b]), a


def _shear_rows(plane: np.ndarray, slope: float, about_x: float, width: int) -> np.ndarray:
    cv2 = _cv()
    m = np.float32([[1.0, 0.0, 0.0], [-slope, 1.0, slope * about_x]])
    return cv2.warpAffine(plane, m, (width, plane.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def _grow_band(sheared: np.ndarray, row: int, xs: np.ndarray, max_half: int, sign: float, bar: float) -> np.ndarray:
    h = sheared.shape[0]
    band = np.zeros((2 * max_half + 1, xs.size), dtype=bool)
    band[max_half] = True
    for direction in (-1, 1):
        alive = np.ones(xs.size, dtype=bool)
        for step in range(1, max_half + 1):
            r = row + direction * step
            if not 0 <= r < h:
                break
            alive &= (sheared[r, xs] * sign) > bar
            if not alive.any():
                break
            band[max_half + direction * step] = alive
    return band


def trace_scratch(
    pixels: np.ndarray, nx: float, ny: float, threshold: float = DEFAULT_SCRATCH_SENSITIVITY
) -> Optional[Tuple[float, float, float, float, float]]:
    """One click near a (roughly horizontal) transport scratch -> (nx0, ny0,
    nx1, ny1, width) in 0..1 raw-frame coordinates, or None if the click
    found clean film. pixels is the raw scan as uint8 sRGB."""
    cv2 = _cv()
    lin = _linearize(pixels)
    h, w = lin.shape[:2]
    cx, cy = float(nx) * w, float(ny) * h
    bar = scratch_detect_bar(threshold)
    y0 = max(0, int(cy) - _SCRATCH_SEARCH_ROWS)
    y1 = min(h, int(cy) + _SCRATCH_SEARCH_ROWS)
    if y1 - y0 < 3:
        return None
    scale = film_scale((h, w))
    max_half = max(1, int(round(0.5 * _SCRATCH_WIDTH_MAX * scale)))
    reach = max_half + int(math.ceil(_SCRATCH_SLOPE_MAX * w)) + 2
    z, z0 = _scratch_ridge_rows(lin, y0 - reach, y1 + reach)
    band = np.ascontiguousarray(z[y0 - z0 : y1 - z0])
    pull = np.exp(-0.5 * ((np.arange(y0, y1) - cy) / _SCRATCH_CLICK_PULL) ** 2)

    best = None
    for slope in np.arange(-_SCRATCH_SLOPE_MAX, _SCRATCH_SLOPE_MAX + 1e-9, _SCRATCH_SLOPE_STEP):
        sheared = _shear_rows(band, float(slope), cx, w)
        strength = np.abs(sheared.mean(axis=1)) * pull
        k = int(np.argmax(strength))
        if best is None or strength[k] > best[0]:
            best = (float(strength[k]), float(slope), k, sheared[k])
    if best is None or best[0] < _SCRATCH_MIN_EVIDENCE:
        return None
    _, slope, k, along = best

    on = (along * np.sign(along.mean()) > bar).astype(np.float32)
    run = cv2.blur(on.reshape(1, -1), (_SCRATCH_RUN_WIN, 1)).ravel() >= _SCRATCH_RUN_FRAC
    if not run.any():
        return None
    cols = np.flatnonzero(run)
    x0, x1 = float(cols[0]), float(cols[-1])
    row = y0 + k
    grown = _grow_band(_shear_rows(z, slope, cx, w), row - z0, cols, max_half, float(np.sign(along.mean()) or 1.0), bar)
    width = float(np.clip(2.0 * float(np.median(grown.sum(axis=0))) / max(scale, 1e-6), _SCRATCH_WIDTH_MIN, _SCRATCH_WIDTH_MAX))
    return (x0 / w, (row + slope * (x0 - cx)) / h, x1 / w, (row + slope * (x1 - cx)) / h, width)


def lines_to_score(lin: np.ndarray, lines: List[Tuple], threshold: float = DEFAULT_SCRATCH_SENSITIVITY) -> Optional[np.ndarray]:
    """Traced scratch lines -> a defect score for the shared repair. The line
    says where to look; presence and width are re-measured here, so
    stretches carrying no scratch are left alone."""
    cv2 = _cv()
    if not lines:
        return None
    h, w = lin.shape[:2]
    bar = scratch_detect_bar(threshold)
    scale = film_scale((h, w))
    mask = np.zeros((h, w), dtype=np.uint8)
    touched = False

    for nx0, ny0, nx1, ny1, _width in lines:
        x0, x1 = float(nx0) * w, float(nx1) * w
        y0, y1 = float(ny0) * h, float(ny1) * h
        if abs(x1 - x0) < 1.0:
            continue
        slope = (y1 - y0) / (x1 - x0)
        max_half = max(1, int(round(0.5 * _SCRATCH_WIDTH_MAX * scale)))
        row = int(round(y0))
        if not 0 <= row < h:
            continue
        reach = max_half + int(math.ceil(abs(slope) * max(x0, w - x0))) + 2
        z, z0 = _scratch_ridge_rows(lin, row - reach, row + reach + 1)
        sheared = _shear_rows(z, slope, x0, w)
        row -= z0
        along = sheared[row]
        sign = np.sign(along.mean()) or 1.0
        on = (along * sign > bar).astype(np.float32)
        run = cv2.blur(on.reshape(1, -1), (_SCRATCH_RUN_WIN, 1)).ravel() >= _SCRATCH_RUN_FRAC
        lo, hi = int(max(0, min(x0, x1))), int(min(w, max(x0, x1)) + 1)
        keep = np.zeros(w, dtype=bool)
        keep[lo:hi] = run[lo:hi]
        if not keep.any():
            continue

        xs = np.flatnonzero(keep)
        grown = _grow_band(sheared, row, xs, max_half, float(sign), bar)
        centres = np.round(y0 + slope * (xs - x0)).astype(np.int64)
        offsets = np.arange(-max_half, max_half + 1)[:, None]
        rows = centres[None, :] + offsets
        valid = grown & (rows >= 0) & (rows < h)
        cols = np.broadcast_to(xs, rows.shape)
        mask[rows[valid], cols[valid]] = 1
        touched = True

    return _mask_to_score(mask, _DETECT_PAD_PX * scale) if touched and mask.any() else None


def smooth_polyline(pts, closed: bool = False, samples_per_seg: int = 16):
    """Densify a polyline into a uniform Catmull-Rom curve through its points
    (fewer than 3 points are returned unchanged)."""
    n = len(pts)
    if n < 3:
        return [(float(x), float(y)) for x, y in pts]
    p = np.asarray(pts, dtype=np.float64)
    t = np.linspace(0.0, 1.0, samples_per_seg, endpoint=False)[:, None]
    t2, t3 = t * t, t * t * t
    out = []
    n_seg = n if closed else n - 1
    for i in range(n_seg):
        p0 = p[(i - 1) % n] if closed else p[max(i - 1, 0)]
        p1 = p[i]
        p2 = p[(i + 1) % n] if closed else p[i + 1]
        p3 = p[(i + 2) % n] if closed else p[min(i + 2, n - 1)]
        seg = 0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)
        out.extend((float(x), float(y)) for x, y in seg)
    if not closed:
        out.append((float(p[-1][0]), float(p[-1][1])))
    return out


def manual_sensitivity_mult(slider: float) -> float:
    """UI sensitivity (higher = more conservative) -> the multiplier applied
    to a stroke's z-score bars. 1.0 at the slider's midpoint."""
    s = float(np.clip(slider, 0.0, 1.0))
    return _MANUAL_SENS_MULT_LOOSE + (_MANUAL_SENS_MULT_TIGHT - _MANUAL_SENS_MULT_LOOSE) * s


def strokes_to_score(lin: np.ndarray, strokes) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """Painted heal strokes -> (score, method_mask). Each stroke is
    (points, size, mult, force, method): points are 0..1 raw-frame [x, y]
    pairs, size is the brush diameter at HEAL_SIZE_REF, mult scales the
    z-score bars (sensitivity), force skips detection and repairs everything
    the stroke covers, method pins the fill (smooth) or inpaint (structure).

    The capsule a stroke paints is a search area: inside it, a pixel is
    repaired by how far it stands out from the film around it (two-sided,
    since dust is a bright density outlier and a scratch a dark one), so
    clean grain under a generous brush comes back untouched.

    method_mask is None unless a stroke pinned a method: 1 marks pixels
    pinned to the fill, 2 pixels pinned to the inpaint."""
    cv2 = _cv()
    if not strokes:
        return None, None
    h, w = lin.shape[:2]
    score = np.ones((h, w), dtype=np.float32)
    scale = max(w, h) / HEAL_SIZE_REF
    touched = False
    method_mask: Optional[np.ndarray] = None

    for stroke in strokes:
        points, size, mult, force, method = stroke[0], float(stroke[1]), float(stroke[2]), bool(stroke[3]), str(stroke[4])
        radius = max(1.0, size * scale * 0.5)
        chain = [(float(p[0]) * w, float(p[1]) * h) for p in points]
        if len(chain) >= 3:
            chain = smooth_polyline(chain, closed=False)
        pts = np.array(chain, dtype=np.float32)

        win = int(max(3.0, radius * _MANUAL_WIN_FACTOR)) * 2 + 1
        pad = int(radius) + win
        x0 = max(0, int(pts[:, 0].min()) - pad)
        y0 = max(0, int(pts[:, 1].min()) - pad)
        x1 = min(w, int(pts[:, 0].max()) + pad + 1)
        y1 = min(h, int(pts[:, 1].max()) + pad + 1)
        if x1 <= x0 or y1 <= y0:
            continue

        cover = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
        local = np.round(pts - (x0, y0)).astype(np.int32)
        if len(local) > 1:
            cv2.polylines(cover, [local], False, 1, thickness=max(1, int(round(2.0 * radius))))
        for cx, cy in local:  # round caps and joins
            cv2.circle(cover, (int(cx), int(cy)), max(1, int(round(radius))), 1, -1)
        if not cover.any():
            continue

        if force:
            keep = cover
        else:
            crop = _density(lin[y0:y1, x0:x1])
            detail = cv2.blur(crop - cv2.blur(crop, (win, win)), (3, 3))
            sigma = float(np.median(np.abs(detail))) / 0.6745
            z = np.abs(detail) / max(sigma, 1e-9)
            inside = cover > 0
            peak = float(z[inside].max())
            z_min = _MANUAL_Z_MIN * mult
            z_hi = _MANUAL_Z_HI * mult
            if peak < z_min:
                continue  # the brush found clean film; repairing it would only smooth grain
            hi = z_hi if peak >= z_hi else peak * 0.9
            lo = max(_MANUAL_Z_GROW * mult, hi * _MANUAL_Z_GROW_FRAC)
            strong = inside & (z >= hi)
            if not strong.any():
                continue
            _n, lab = cv2.connectedComponents((inside & (z >= lo)).astype(np.uint8), connectivity=8)
            seeded = np.unique(lab[strong])
            keep = np.isin(lab, seeded[seeded > 0]).astype(np.uint8)

        region = _mask_to_score(keep, _DETECT_PAD_PX * film_scale((h, w)))
        d = cv2.distanceTransform(cover, cv2.DIST_L2, 3)
        alpha = np.clip(d / _MANUAL_RIM_PX, 0.0, 1.0)
        region = 1.0 - alpha * (1.0 - region)
        np.minimum(score[y0:y1, x0:x1], region.astype(np.float32), out=score[y0:y1, x0:x1])
        touched = True

        if method != REPAIR_AUTO:
            if method_mask is None:
                method_mask = np.zeros((h, w), dtype=np.uint8)
            marked = keep
            if method != REPAIR_STRUCTURE:
                dil = 2 * int(round(_ROUTE_DILATE * film_scale((h, w)))) + 1
                marked = cv2.dilate(keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dil, dil)))
            method_mask[y0:y1, x0:x1][marked.astype(bool)] = 2 if method == REPAIR_STRUCTURE else 1

    return (score if touched else None), method_mask


def route_wide_defects(score: np.ndarray) -> Optional[np.ndarray]:
    """Mask of at-floor components wider than the fill can reach across -
    these go to the structure-following inpaint instead."""
    cv2 = _cv()
    at_floor = (score <= _SCORE_FLOOR + 1e-6).astype(np.uint8)
    if not at_floor.any():
        return None
    n_lbl, labels, stats, _ = cv2.connectedComponentsWithStats(at_floor, connectivity=8)
    radius = int(round(_ROUTE_RADIUS * film_scale(score.shape[:2])))
    side = 2 * radius - 1
    routed = np.zeros_like(at_floor)
    hit = False
    for i in range(1, n_lbl):
        bw, bh = int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT])
        if min(bw, bh) < side:
            continue
        x0, y0 = int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP])
        own = labels[y0 : y0 + bh, x0 : x0 + bw] == i
        if float(cv2.distanceTransform(np.pad(own.astype(np.uint8), 1), cv2.DIST_C, 3).max()) >= radius:
            routed[y0 : y0 + bh, x0 : x0 + bw][own] = 1
            hit = True
    if not hit:
        return None
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * int(round(_ROUTE_DILATE * film_scale(score.shape[:2]))) + 1,) * 2)
    return cv2.dilate(routed, k)


# --------------------------------------------------------------- top level


def _linearize(pixels: np.ndarray) -> np.ndarray:
    return np.power(pixels.astype(np.float32) * np.float32(1.0 / 255.0), np.float32(_GAMMA))


def _delinearize(lin: np.ndarray) -> np.ndarray:
    out = np.power(np.clip(lin, 0.0, 1.0), np.float32(1.0 / _GAMMA))
    out *= np.float32(255.0)
    return (out + np.float32(0.5)).astype(np.uint8)


class DustStatsCache:
    """Holds the threshold-independent detection maps between calls, so
    dragging the Threshold slider only redoes seeding/growing."""

    def __init__(self):
        self.key = None
        self.stats = None


@dataclass
class RetouchResult:
    pixels: np.ndarray  # the repaired scan (or the input itself if nothing changed)
    specks: Optional[np.ndarray] = None  # uint8 mask, detection scale: auto-detected specks
    hairs: Optional[np.ndarray] = None  # uint8 mask, detection scale: hair-shaped defects
    manual: Optional[np.ndarray] = None  # uint8 mask, source scale: painted heals + traced scratches


def _detect(lin, threshold, size, stats_cache, cache_token):
    small = _min_pool(lin, _DETECT_REF)
    key = (cache_token, int(size), small.shape)
    if stats_cache is not None and stats_cache.key == key:
        stats = stats_cache.stats
    else:
        stats = compute_dust_stats(small, int(size))
        if stats_cache is not None:
            stats_cache.key, stats_cache.stats = key, stats
    return small, detect_luma_score(small, threshold, int(size), stats=stats)


def detect_dust_masks(
    pixels: np.ndarray,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    size: int = DEFAULT_SIZE,
    stats_cache: Optional[DustStatsCache] = None,
    cache_token=None,
) -> RetouchResult:
    """Detection only (no repair) - what the "Marked" overlay shows while
    Auto Dust Removal is off, so the threshold can be tuned by eye first."""
    lin = _linearize(pixels)
    _small, (score, hair) = _detect(lin, threshold, size, stats_cache, cache_token)
    specks = (score < 1.0).astype(np.uint8) if score is not None else None
    return RetouchResult(pixels, specks=specks, hairs=hair)


def remove_dust_and_scratches(
    pixels: np.ndarray,
    *,
    auto: bool,
    threshold: float = DEFAULT_THRESHOLD,
    size: int = DEFAULT_SIZE,
    scratch_lines: Optional[List[Tuple]] = None,
    scratch_sensitivity: float = DEFAULT_SCRATCH_SENSITIVITY,
    heal_strokes: Optional[List[Tuple]] = None,
    stats_cache: Optional[DustStatsCache] = None,
    cache_token=None,
) -> RetouchResult:
    """Repairs dust specks, hairs (auto), painted heal strokes and traced
    scratches in a raw scan (uint8 sRGB). pixels in the result is the input
    itself, untouched, if nothing was found."""
    scratch_lines = list(scratch_lines or [])
    heal_strokes = list(heal_strokes or [])
    if not auto and not scratch_lines and not heal_strokes:
        return RetouchResult(pixels)
    lin = _linearize(pixels)
    out = lin
    changed = False
    specks = hairs = manual = None

    if auto:
        small, (score, hair) = _detect(lin, threshold, size, stats_cache, cache_token)
        if score is not None:
            out = _repair_components(out, score)
            specks = (score < 1.0).astype(np.uint8)
            changed = True
        if hair is not None:
            out = _apply_hair_inpaint(out, hair)
            hairs = hair
            changed = True

    # Painted strokes and traced lines go through one repair: whichever calls
    # a pixel more damaged wins. floor=False - a scratch has lost emulsion and
    # reads brighter than the film around it, so the repair must be free to
    # darken as well as lighten.
    stroke_score, method_mask = strokes_to_score(lin, heal_strokes)
    line_score = lines_to_score(lin, scratch_lines, scratch_sensitivity)
    parts = [p for p in (stroke_score, line_score) if p is not None]
    if parts:
        score = parts[0] if len(parts) == 1 else np.minimum(*parts)
        out = _repair_components(out, score, floor=False, factor=film_scale(lin.shape[:2]))
        manual = (score < 1.0).astype(np.uint8)
        routed = route_wide_defects(score)
        if method_mask is not None:
            forced = (method_mask == 2).astype(np.uint8)
            if forced.any():
                routed = forced if routed is None else np.maximum(routed, forced)
            if routed is not None:
                routed = np.where(method_mask == 1, 0, routed).astype(np.uint8)
                if not routed.any():
                    routed = None
        if routed is not None:
            out = _apply_hair_inpaint(out, routed)
        changed = True

    return RetouchResult(_delinearize(out) if changed else pixels, specks, hairs, manual)
