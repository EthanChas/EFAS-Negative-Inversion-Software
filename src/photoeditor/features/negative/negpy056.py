"""NegPy 0.56's conversion of a negative - numpy only, no Qt. Ported from NegPy 0.56.0 (GPL-3.0, github.com/marcinz606/NegPy): negpy/features/exposure/normalization.py (the bounds and
the meters), logic.py (the grade, the pivot, the cast-removal curve fit and the print curve) and processor.py (how they are put together), for the default colour or black-and-white
negative path.

It is kept as "NegPy 0.56 (old)" because NegPy changed this part later (0.58: print tone retuned, Auto Grade and Auto Density metering textured parts only, a shadow reach floor), and
because a conversion made with 0.56 has a look of its own: the bounds are the 0.01st to 99.99th percentile of each channel (the dense end read from a chroma-gated set of neutral pixels), the
film's orange mask is taken out by stretching each channel to its own bounds, and Cast Removal fits red and blue to green through the picture's own neutral greys.

The steps, in the order NegPy runs them:
  1. the scan's transmittance T (linear light) goes to log10(T);
  2. the metering region (the frame less its margin, or a rectangle) is reduced to a grid by block medians, which drops dust and speculars;
  3. per-channel floors and ceilings (the bounds) are read off that grid, and the picture is stretched to them (floor -> 0, ceiling -> 1): the orange mask is gone;
  4. the grid's meters read the picture's neutral axis (Cast Removal), its midtone (the anchor: Auto Density) and its textural range (Auto Grade);
  5. a print curve per channel - a straight line of slope k (the ISO-R grade), a midtone S, a toe into paper black and a shoulder into paper white - turns the stretched log into print
     density, then into reflectance (black point compensated) and the display's sRGB encoding.
Steps 3 and 5 are one function of each channel's own log value, so they are built as a lookup table over the scan's density codes, as printengine.py does."""

from dataclasses import dataclass

import numpy as np

LUMA = (0.2126, 0.7152, 0.0722)

# NegPy 0.56's EXPOSURE_CONSTANTS (negpy/features/exposure/models.py), the ones this path uses
ANCHOR_TARGET_DENSITY = 0.75
DENSITY_MULTIPLIER = 0.2
ASSUMED_ANCHOR = 0.46
ISO_R_MIN, ISO_R_MAX = 50.0, 180.0
SLOPE_MIN, SLOPE_MAX = 2.0, 10.0
D_MAX = 2.3
TOE_SHOULDER_STRENGTH = 0.85
TOE_SHARPNESS_BASE, SHOULDER_SHARPNESS_BASE = 4.0, 3.0
WIDTH_REF = 2.5
TOE_HEIGHT, SHOULDER_HEIGHT = 0.90, 0.35
GRADE_CONTRAST_SCALE = 2.9
ANALYSIS_GRID = 1024
BASE_LUMA_CLIP = 0.01
BASE_COLOR_CLIP = 1.0
SHADOW_NEUTRAL_PERCENTILE = 98.0
CAST_REMOVAL_MAX_OFFSET = 0.1
NEUTRAL_HIGHLIGHT_BAND, NEUTRAL_MID_BAND, NEUTRAL_SHADOW_BAND = (0.10, 0.30), (0.40, 0.60), (0.72, 0.92)
NEUTRAL_CHROMA_QUANTILE = 0.30
NEUTRAL_CHROMA_CAP = 0.29
NEUTRAL_FIRST_PASS_CAP = 0.55
NEUTRAL_MIN_PIXELS = 64
NEUTRAL_CONFIDENCE_N0 = 256
NEUTRAL_AGREEMENT_DEADZONE, NEUTRAL_AGREEMENT_SCALE = 0.10, 0.20
COLOR_BOUNDS_BAND_WIDTH = 4.0
MIDTONE_CAST_MAX_OFFSET = 0.2
NEUTRAL_CURV_MAX_RATIO = 0.45
ANCHOR_METER_PERCENTILE = 50.0
ANCHOR_METER_BAND = 0.12
ANCHOR_METER_STRENGTH = 0.2
TOE_GRADE_STRENGTH = 0.15 * 0.35 / 0.90
SHOULDER_GRADE_STRENGTH = 0.12
AUTO_GRADE_TARGET = 0.6
AUTO_GRADE_STRENGTH = 0.5
AUTO_GRADE_NOMINAL_RATIO = 2.0
TEXTURAL_RANGE_CLIP = 10.0
PAPER_MIDTONE_GAMMA = 0.15
PAPER_GAMMA_WIDTH = 0.6
EPS = 1e-6


@dataclass(frozen=True)
class Settings:
    """What the print is made with (NegPy's ExposureConfig, for the controls EFAS has)."""

    grade: float = 115.0           # ISO R paper exposure range: 50 (hardest) to 180 (softest); about 110 is a classic grade 2
    density: float = 1.0           # 1.0 prints the picture's metered middle at the target density; more prints darker
    cast_removal: float = 0.5      # how far red and blue are fitted to green through the picture's neutral greys
    toe: float = 0.0               # -1 to 1
    shoulder: float = 0.0          # -1 to 1
    luma_clip: float = 0.0         # NegPy's Luma Range Clip: >0 tightens the black and white points, <0 gives headroom
    black_and_white: bool = False  # a black-and-white negative: the picture is one density before the curve


def _softplus(x):
    return np.logaddexp(0.0, x)


def _inv_softplus(y):
    y = np.asarray(y, dtype=np.float64)
    return np.where(y > 20.0, y, np.log(np.expm1(np.maximum(y, 1e-12))))


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# the grid and the bounds


def block_median_grid(img_log: np.ndarray) -> np.ndarray:
    """The region reduced to at most ANALYSIS_GRID cells on its long side by block medians: a dust speck or a specular is lost inside its block's median."""
    h, w = img_log.shape[:2]
    b = int(np.ceil(max(h, w) / ANALYSIS_GRID))
    if b <= 1 or h < b or w < b:
        return img_log
    hb, wb = (h // b) * b, (w // b) * b
    v = img_log[:hb, :wb].reshape(hb // b, b, wb // b, b, img_log.shape[2])
    return np.median(v, axis=(1, 3))


def _rms_chroma(t: np.ndarray) -> np.ndarray:
    r, g, b = t[..., 0], t[..., 1], t[..., 2]
    return np.sqrt(((r - g) ** 2 + (g - b) ** 2 + (r - b) ** 2) / 3.0)


def _norm(img_log: np.ndarray, floors, ceils) -> np.ndarray:
    """The picture stretched so each channel's floor is 0 and its ceiling 1, in the precision it is given (NegPy does this in float32, and the meters' band edges are read off it)."""
    dtype = img_log.dtype if np.issubdtype(img_log.dtype, np.floating) else np.float64
    out = np.empty(img_log.shape, dtype=dtype)
    for ch in range(3):
        f, c = dtype.type(floors[ch]), dtype.type(ceils[ch])
        d = c - f
        if abs(d) < EPS:
            d = dtype.type(EPS if d >= 0 else -EPS)
        out[..., ch] = (img_log[..., ch] - f) / d
    return out


def _sample_bounds(grid: np.ndarray, clip: float, base: float) -> tuple[list, list]:
    """Per-channel floors (dense end) and ceilings (thin end, the film base) at one clip. A negative clip leaves headroom outside the extremes."""
    if clip >= 0:
        c, margin = max(0.00001, min(50.0, clip + base)), 0.0
    else:
        c, margin = base, -clip
    p_low, p_high = np.float64(c), np.float64(100.0 - c)     # (float64, as NegPy has them: a float32 grid is then read in float64)
    floors = [float(np.percentile(grid[..., ch], p_low)) for ch in range(3)]
    ceils = [float(np.percentile(grid[..., ch], p_high)) for ch in range(3)]
    if margin > 0.0:
        floors = [f - margin for f in floors]
        ceils = [v + margin for v in ceils]
    return floors, ceils


def _same_pixel_floor_refs(grid: np.ndarray, floors, ceils, base_refs, color_clip: float):
    """The dense end's per-channel refs from one shared set of pixels (the luma-extreme band's lowest-chroma subset), so a coloured highlight cannot pass as film cast. None when
    the band has too few or too chromatic neutrals (the percentile refs are used instead)."""
    flat = grid.reshape(-1, 3).astype(np.float64)
    base = np.asarray(base_refs, dtype=np.float64)
    norm = np.empty_like(flat)
    for ch in range(3):
        d = ceils[ch] - floors[ch]
        if abs(d) < EPS:
            d = EPS if d >= 0 else -EPS
        norm[:, ch] = (flat[:, ch] - floors[ch]) / d
    luma = LUMA[0] * norm[:, 0] + LUMA[1] * norm[:, 1] + LUMA[2] * norm[:, 2]
    clip = max(0.00001, min(50.0 - COLOR_BOUNDS_BAND_WIDTH, float(color_clip)))
    lo, hi = np.percentile(luma, [clip, clip + COLOR_BOUNDS_BAND_WIDTH])
    band = (luma >= lo) & (luma <= hi)
    if int(band.sum()) < NEUTRAL_MIN_PIXELS:
        return None
    d = flat[band] - base[None, :]

    def select(gamma):
        g = gamma.copy()
        g[np.abs(g) < EPS] = EPS
        chroma = _rms_chroma(d / g[None, :])
        sel = chroma <= float(np.quantile(chroma, NEUTRAL_CHROMA_QUANTILE))
        if int(sel.sum()) < NEUTRAL_MIN_PIXELS:
            return None
        return sel, float(np.median(chroma[sel]))

    spans = np.array([floors[ch] - base_refs[ch] for ch in range(3)], dtype=np.float64)
    first = select(spans)
    if first is None or first[1] > NEUTRAL_FIRST_PASS_CAP:
        return None
    provisional = np.median(d[first[0]], axis=0)
    if np.any(np.abs(provisional) < EPS):
        return None
    second = select(provisional)
    if second is None or second[1] > NEUTRAL_CHROMA_CAP:
        return None
    refs = base + np.median(d[second[0]], axis=0)
    return [float(refs[0]), float(refs[1]), float(refs[2])]


def bounds_of(grid: np.ndarray, luma_clip: float = 0.0, color_clip: float = BASE_COLOR_CLIP) -> tuple[list, list]:
    """(floors, ceilings) in log10: the luminance centre and span from the luma pass, each channel's deviation from it from the colour pass."""
    floors, ceils = _sample_bounds(grid, luma_clip, BASE_LUMA_CLIP)
    c_floors, c_ceils = _sample_bounds(grid, color_clip, 0.0)
    if color_clip >= 0:
        sp = _same_pixel_floor_refs(grid, floors, ceils, c_ceils, color_clip)
        if sp is not None:
            c_floors = sp
    mean_lf, mean_lc = sum(floors) / 3.0, sum(ceils) / 3.0
    mean_cf, mean_cc = sorted(c_floors)[1], sorted(c_ceils)[1]
    return ([mean_lf + (c_floors[ch] - mean_cf) for ch in range(3)], [mean_lc + (c_ceils[ch] - mean_cc) for ch in range(3)])


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# the meters


def shadow_refs(grid: np.ndarray) -> tuple[float, float, float]:
    return tuple(float(np.percentile(grid[..., ch], SHADOW_NEUTRAL_PERCENTILE)) for ch in range(3))


def neutral_axis(grid: np.ndarray, floors, ceils):
    """The picture's neutral axis for Cast Removal: the median log density of the lowest-chroma pixels in a highlight, a midtone and a shadow band, in two passes. (mid, shadow,
    highlight or None, confidence), or None when the midtone or the shadow has no trustworthy greys."""
    norm = _norm(grid, floors, ceils)
    luma = LUMA[0] * norm[..., 0] + LUMA[1] * norm[..., 1] + LUMA[2] * norm[..., 2]
    flat_log, norm_f, luma_f = grid.reshape(-1, 3), norm.reshape(-1, 3), luma.reshape(-1)
    chroma_f = _rms_chroma(norm_f)

    def band_refs(lo, hi, chroma_vals, cap):
        band = (luma_f >= lo) & (luma_f <= hi)
        if int(band.sum()) < NEUTRAL_MIN_PIXELS:
            return None
        bc = chroma_vals[band]
        keep = bc <= float(np.quantile(bc, NEUTRAL_CHROMA_QUANTILE))
        idx = np.nonzero(band)[0][keep]
        near = float(np.median(bc[keep])) if idx.size else cap
        if idx.size < NEUTRAL_MIN_PIXELS or near > cap:
            return None
        sel = flat_log[idx]
        return (tuple(float(np.median(sel[:, ch])) for ch in range(3)), near, int(idx.size))

    def norm_ref(refs):
        out = []
        for ch in range(3):
            d = ceils[ch] - floors[ch]
            if abs(d) < EPS:
                d = EPS if d >= 0 else -EPS
            out.append((refs[ch] - floors[ch]) / d)
        return out

    mid1 = band_refs(*NEUTRAL_MID_BAND, chroma_f, NEUTRAL_FIRST_PASS_CAP)
    sh1 = band_refs(*NEUTRAL_SHADOW_BAND, chroma_f, NEUTRAL_FIRST_PASS_CAP)
    if mid1 is None or sh1 is None:
        return None
    nm, ns = norm_ref(mid1[0]), norm_ref(sh1[0])
    corrected = norm_f.copy()
    for ch in (0, 2):
        du = nm[ch] - ns[ch]
        if abs(du) < EPS:
            a, b = 1.0, nm[1] - nm[ch]
        else:
            a = (nm[1] - ns[1]) / du
            b = nm[1] - a * nm[ch]
        corrected[:, ch] = a * norm_f[:, ch] + b
    chroma2 = _rms_chroma(corrected)
    mid = band_refs(*NEUTRAL_MID_BAND, chroma2, NEUTRAL_CHROMA_CAP)
    shadow = band_refs(*NEUTRAL_SHADOW_BAND, chroma2, NEUTRAL_CHROMA_CAP)
    if mid is None or shadow is None:
        return None
    highlight = band_refs(*NEUTRAL_HIGHLIGHT_BAND, chroma2, NEUTRAL_CHROMA_CAP)
    tight = float(np.clip(1.0 - max(mid[1], shadow[1]) / NEUTRAL_CHROMA_CAP, 0.0, 1.0))
    size_term = mid[2] / (mid[2] + NEUTRAL_CONFIDENCE_N0)
    dm, ds = norm_ref(mid[0]), norm_ref(shadow[0])
    spread = max(abs((dm[ch] - dm[1]) - (ds[ch] - ds[1])) for ch in (0, 2))
    agree = 1.0 - min(max(spread - NEUTRAL_AGREEMENT_DEADZONE, 0.0) / NEUTRAL_AGREEMENT_SCALE, 1.0)
    return (mid[0], shadow[0], highlight[0] if highlight is not None else None, float(np.clip(tight * size_term * agree, 0.0, 1.0)))


def metered_anchor(grid: np.ndarray, floors, ceils) -> float:
    """Auto Density: where the picture's middle sits in 0-1, a fifth of the way from the assumed middle, kept within 0.12 of it."""
    norm = _norm(grid, floors, ceils)
    lum = LUMA[0] * norm[..., 0] + LUMA[1] * norm[..., 1] + LUMA[2] * norm[..., 2]
    measured = float(np.percentile(lum, ANCHOR_METER_PERCENTILE))
    anchor = ASSUMED_ANCHOR + ANCHOR_METER_STRENGTH * (measured - ASSUMED_ANCHOR)
    return float(min(max(anchor, ASSUMED_ANCHOR - ANCHOR_METER_BAND), ASSUMED_ANCHOR + ANCHOR_METER_BAND))


def textural_range(grid: np.ndarray) -> float:
    lum = LUMA[0] * grid[..., 0] + LUMA[1] * grid[..., 1] + LUMA[2] * grid[..., 2]
    lo, hi = np.percentile(lum, [TEXTURAL_RANGE_CLIP, 100.0 - TEXTURAL_RANGE_CLIP])
    return float(abs(hi - lo))


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# the print


def _v_star() -> float:
    t = ANCHOR_TARGET_DENSITY
    v1 = D_MAX - float(_inv_softplus(TOE_SHARPNESS_BASE * (D_MAX - t))) / TOE_SHARPNESS_BASE
    return float(float(_inv_softplus(SHOULDER_SHARPNESS_BASE * v1)) / SHOULDER_SHARPNESS_BASE)


V_STAR = _v_star()


def _pivot(slope: float, density: float, anchor: float | None) -> float:
    ref = ASSUMED_ANCHOR if anchor is None else anchor
    return ref - V_STAR / slope + (1.0 - density) * DENSITY_MULTIPLIER


def _grade_slope(grade: float, density_range: float) -> float:
    er = min(max(grade, ISO_R_MIN), ISO_R_MAX) / 100.0
    rng = min(max(abs(float(density_range)), 0.3), 3.5)
    return float(min(max(GRADE_CONTRAST_SCALE * rng / er, SLOPE_MIN), SLOPE_MAX))


def _effective_range(floor_ceil_range: float, textural: float) -> float:
    measured = abs(float(textural))
    if measured < 1e-6:
        return 3.5
    ratio = abs(float(floor_ceil_range)) / measured
    return AUTO_GRADE_TARGET * (AUTO_GRADE_NOMINAL_RATIO + AUTO_GRADE_STRENGTH * (ratio - AUTO_GRADE_NOMINAL_RATIO))


def curve_params(settings: Settings, lum_range: float, textural: float, anchor: float, neutral, shadow, floors, ceils):
    """Per-channel (slopes, pivots, curvatures): one shared line, or, with Cast Removal and a neutral axis, red and blue fitted to green's through the picture's greys."""
    base_slope = _grade_slope(settings.grade, _effective_range(lum_range, textural))
    strength = settings.cast_removal
    norm_ref = lambda r: [(r[ch] - floors[ch]) / (ceils[ch] - floors[ch] if abs(ceils[ch] - floors[ch]) >= EPS else EPS) for ch in range(3)]   # noqa: E731
    if neutral is not None:
        strength = neutral[3] * strength
        axis = (norm_ref(neutral[0]), norm_ref(neutral[1]), norm_ref(neutral[2]) if neutral[2] is not None else None)
    else:
        axis = None
    shadow_norm = norm_ref(shadow) if shadow is not None else None
    if strength > 0.0 and axis is not None:
        mid_norm, sh_norm, hl_norm = axis
        m_g, s_g = float(mid_norm[1]), float(sh_norm[1])
        slope_g = min(max(base_slope, SLOPE_MIN), SLOPE_MAX)
        pivot_g = _pivot(slope_g, settings.density, anchor)
        target = lambda g: slope_g * (g - pivot_g)   # noqa: E731
        t_m, t_s = target(m_g), target(s_g)
        h_g = float(hl_norm[1]) if hl_norm is not None else None
        clamp_dev = lambda g, v: g + min(max(strength * (v - g), -MIDTONE_CAST_MAX_OFFSET), MIDTONE_CAST_MAX_OFFSET)   # noqa: E731
        slopes, pivots, curvs = [], [], []
        for ch in range(3):
            if ch == 1:
                slopes.append(slope_g), pivots.append(pivot_g), curvs.append(0.0)
                continue
            u_m, u_s = clamp_dev(m_g, float(mid_norm[ch])), clamp_dev(s_g, float(sh_norm[ch]))
            curv = 0.0
            if h_g is not None:
                u_h = clamp_dev(h_g, float(hl_norm[ch]))
                m = np.array([[1.0, u_h, u_h * u_h], [1.0, u_m, u_m * u_m], [1.0, u_s, u_s * u_s]])
                try:
                    curv = float(np.linalg.solve(m, np.array([target(h_g), t_m, t_s]))[2])
                except np.linalg.LinAlgError:
                    curv = 0.0
                curv = min(max(curv, -NEUTRAL_CURV_MAX_RATIO * slope_g), NEUTRAL_CURV_MAX_RATIO * slope_g)
            du = u_m - u_s
            slope_ch = slope_g if abs(du) < EPS else ((t_m - t_s) - curv * (u_m * u_m - u_s * u_s)) / du
            slope_ch = min(max(slope_ch, SLOPE_MIN), SLOPE_MAX)
            pivot_ch = u_m - (t_m - curv * u_m * u_m) / slope_ch if abs(slope_ch) > EPS else pivot_g
            slopes.append(slope_ch), pivots.append(pivot_ch), curvs.append(curv)
        return slopes, pivots, curvs
    if strength > 0.0 and shadow_norm is not None:
        anchor_val = ASSUMED_ANCHOR if anchor is None else anchor
        r_green = float(shadow_norm[1])
        numer = anchor_val - r_green
        slopes, pivots = [], []
        for ch in range(3):
            cast = min(max(strength * (r_green - float(shadow_norm[ch])), -CAST_REMOVAL_MAX_OFFSET), CAST_REMOVAL_MAX_OFFSET)
            denom = anchor_val - (r_green - cast)
            if ch == 1 or abs(denom) < EPS:
                slope_ch = base_slope
            else:
                slope_ch = min(max(base_slope * numer / denom, SLOPE_MIN), SLOPE_MAX)
            slope_ch = min(max(slope_ch, SLOPE_MIN), SLOPE_MAX)
            slopes.append(slope_ch)
            pivots.append(_pivot(slope_ch, settings.density, anchor))
        return slopes, pivots, [0.0, 0.0, 0.0]
    s = min(max(base_slope, SLOPE_MIN), SLOPE_MAX)
    return [s] * 3, [_pivot(s, settings.density, anchor)] * 3, [0.0] * 3


def print_curve(val: np.ndarray, slope: float, pivot: float, curv: float, toe: float, shoulder: float) -> np.ndarray:
    """Normalised log value -> linear reflectance (black point compensated): the straight line, the midtone S, the shoulder into paper white and the toe into paper black."""
    v = slope * (val - pivot) + curv * val * val
    v = v + PAPER_MIDTONE_GAMMA * PAPER_GAMMA_WIDTH * np.tanh((v - V_STAR) / PAPER_GAMMA_WIDTH)
    a_hl = SHOULDER_SHARPNESS_BASE * WIDTH_REF / WIDTH_REF
    toe_s, sh_s = toe * TOE_SHOULDER_STRENGTH, shoulder * TOE_SHOULDER_STRENGTH
    if toe_s >= 0.0:
        d_max_base, a_sh = D_MAX - toe_s * TOE_HEIGHT, TOE_SHARPNESS_BASE
    else:
        d_max_base, a_sh = D_MAX, TOE_SHARPNESS_BASE * (1.0 - toe_s * 4.0)
    d_min_eff = max(0.0 + sh_s * SHOULDER_HEIGHT, 0.0)
    d_max_eff = max(d_max_base, d_min_eff + 0.1)
    db = D_MAX if toe_s >= 0.0 else D_MAX + toe_s * TOE_HEIGHT
    bpc_black = 10.0 ** -db
    v1 = d_min_eff + _softplus(a_hl * (v - d_min_eff)) / a_hl
    dens = d_max_eff - _softplus(a_sh * (d_max_eff - v1)) / a_sh
    t = (10.0 ** -dens - bpc_black) / (1.0 - bpc_black)
    return np.clip(t, 0.0, 1.0)


def srgb_oetf(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return np.where(t <= 0.0031308, t * 12.92, 1.055 * np.power(t, 1 / 2.4) - 0.055)


def toe_shoulder_for(settings: Settings, slope_g: float) -> tuple[float, float]:
    """The grade-coupled roll-offs: a harder grade has a snappier toe and a tighter shoulder."""
    slope_norm = min(max((slope_g - SLOPE_MIN) / (SLOPE_MAX - SLOPE_MIN), 0.0), 1.0)
    t = settings.toe + TOE_GRADE_STRENGTH * slope_norm
    s = settings.shoulder + SHOULDER_GRADE_STRENGTH * slope_norm
    return min(max(t, -1.0), 1.0), min(max(s, -1.0), 1.0)


@dataclass(frozen=True)
class Plan:
    """What the meters found and the curve chosen: everything needed to print any pixel of the picture."""

    floors: tuple
    ceils: tuple
    slopes: tuple
    pivots: tuple
    curvs: tuple
    toe: float
    shoulder: float
    black_and_white: bool
    cast_confidence: float | None = None
    anchor: float = ASSUMED_ANCHOR


def plan_from_grid(grid: np.ndarray, settings: Settings = Settings()) -> Plan:
    """Meter a block-median grid of log10 transmittance (HxWx3) and choose the print curve for it."""
    grid = np.asarray(grid)
    floors, ceils = bounds_of(grid, settings.luma_clip)
    lum_range = LUMA[0] * abs(ceils[0] - floors[0]) + LUMA[1] * abs(ceils[1] - floors[1]) + LUMA[2] * abs(ceils[2] - floors[2])
    shadow = None if settings.black_and_white else shadow_refs(grid)
    neutral = None if settings.black_and_white else neutral_axis(grid, floors, ceils)
    anchor = metered_anchor(grid, floors, ceils)
    tex = textural_range(grid)
    slopes, pivots, curvs = curve_params(settings, lum_range, tex, anchor, neutral, shadow, floors, ceils)
    toe, shoulder = toe_shoulder_for(settings, slopes[1])
    return Plan(tuple(floors), tuple(ceils), tuple(slopes), tuple(pivots), tuple(curvs), toe, shoulder, settings.black_and_white, neutral[3] if neutral is not None else None, anchor)


def reflectance_image(img_log: np.ndarray, plan: Plan) -> np.ndarray:
    """A full-resolution picture of linear reflectance (HxWx3, float32, paper white 1) from log10 transmittance: what NegPy's print stage returns before the display encoding."""
    norm = _norm(np.asarray(img_log), plan.floors, plan.ceils)
    if plan.black_and_white:   # one density before the curve, like paper under a black-and-white negative
        lum = LUMA[0] * norm[..., 0] + LUMA[1] * norm[..., 1] + LUMA[2] * norm[..., 2]
        norm = np.stack([lum, lum, lum], axis=-1)
    out = np.empty(norm.shape, dtype=np.float32)
    for ch in range(3):
        out[..., ch] = print_curve(norm[..., ch], plan.slopes[ch], plan.pivots[ch], plan.curvs[ch], plan.toe, plan.shoulder)
    if plan.black_and_white:
        y = LUMA[0] * out[..., 0] + LUMA[1] * out[..., 1] + LUMA[2] * out[..., 2]
        out = np.stack([y, y, y], axis=-1).astype(np.float32)
    return out


def print_image(img_log: np.ndarray, plan: Plan) -> np.ndarray:
    """A full-resolution 0-1 sRGB picture (HxWx3, float32) from log10 transmittance."""
    return srgb_oetf(reflectance_image(img_log, plan)).astype(np.float32)


def convert_linear(transmittance: np.ndarray, region=None, buffer: float = 0.05, settings: Settings = Settings()) -> np.ndarray:
    """A 0-1 sRGB positive from a scan's linear transmittance (HxWx3), metered on `region` ((y1, y2, x1, x2), default the frame less `buffer` on each side)."""
    img_log = np.log10(np.clip(np.nan_to_num(transmittance, nan=EPS, posinf=1.0, neginf=EPS), EPS, None))
    h, w = img_log.shape[:2]
    if region is None:
        my, mx = int(h * min(max(buffer, 0.0), 0.3)), int(w * min(max(buffer, 0.0), 0.3))
        region = (my, h - my, mx, w - mx)
    y1, y2, x1, x2 = region
    plan = plan_from_grid(block_median_grid(img_log[y1:y2, x1:x2]), settings)
    return print_image(img_log, plan)


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# EFAS: from density codes to a lookup table


def grid_from_codes(codes: np.ndarray, rect=None, buffer: float = 0.05, density_scale: float = 13000.0) -> np.ndarray:
    """The metering grid of a density image (uint16 codes, density = code / density_scale, as printengine.density_codes makes it): the region - `rect` (x1, y1, x2, y2), else the frame less
    `buffer` on each side - reduced by block medians, as log10 transmittance. Done in strips of rows so a full-size scan does not need a float copy of itself."""
    h, w = codes.shape[:2]
    region = None
    if rect is not None:
        x1, x2 = sorted((max(0, min(int(rect[0]), w)), max(0, min(int(rect[2]), w))))
        y1, y2 = sorted((max(0, min(int(rect[1]), h)), max(0, min(int(rect[3]), h))))
        if x2 - x1 >= 2 and y2 - y1 >= 2:
            region = codes[y1:y2, x1:x2]
    if region is None:
        s = min(max(float(buffer), 0.0), 0.3)
        my, mx = int(h * s), int(w * s)
        region = codes[my:h - my, mx:w - mx] if (h - 2 * my >= 2 and w - 2 * mx >= 2) else codes
    rh, rw = region.shape[:2]
    b = int(np.ceil(max(rh, rw) / ANALYSIS_GRID))
    if b <= 1 or rh < b or rw < b:
        return -region.astype(np.float64) / density_scale
    hb, wb = (rh // b) * b, (rw // b) * b
    rows_per = max(1, (1 << 22) // (wb * 3)) * b                  # block-aligned strips of roughly 4 million values
    parts = []
    for y in range(0, hb, rows_per):
        strip = region[y:min(hb, y + rows_per), :wb]
        v = strip.reshape(strip.shape[0] // b, b, wb // b, b, 3)
        parts.append(np.median(v, axis=(1, 3)))
    return -np.concatenate(parts, axis=0) / density_scale


def build_lut(plan: Plan, density_scale: float = 13000.0) -> np.ndarray:
    """(3, 65536) display values, 0-255 (float), indexed by density code: the stretch to the bounds and the print curve of each channel."""
    log = -np.arange(65536, dtype=np.float64) / density_scale
    lut = np.empty((3, 65536), dtype=np.float32)
    for ch in range(3):
        d = plan.ceils[ch] - plan.floors[ch]
        if abs(d) < EPS:
            d = EPS if d >= 0 else -EPS
        norm = (log - plan.floors[ch]) / d
        lut[ch] = srgb_oetf(print_curve(norm, plan.slopes[ch], plan.pivots[ch], plan.curvs[ch], plan.toe, plan.shoulder)) * 255.0
    return lut
