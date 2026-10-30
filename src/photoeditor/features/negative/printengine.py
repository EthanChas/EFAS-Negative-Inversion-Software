"""The Print Engine: a negative converted the way the film and the paper actually behave - numpy only, no Qt.

The standard conversion stretches each channel's density linearly between its darkest and lightest readings. That is a good first guess and it is what keeps it robust, but it
treats three different things as one: the film, the scene and the paper. This engine keeps them apart.

1. Density. The scan is made linear (undoing the display encoding) and turned into optical density, D = -log10(T). Equal density steps are then equal steps of the film's
   response, which is what every later stage assumes.
2. Dye crosstalk. A dye layer also absorbs in its neighbours' bands, so the three measured densities are mixed copies of the three dye densities. Beer-Lambert makes the mixing
   linear in density, so a 3x3 matrix applied there takes it out. Greys stay grey because every row of the matrix sums to 1.
3. The film. Net density above the film's base is not proportional to the log of the light that exposed it: the toe flattens the shadows and the shoulder the highlights.
   Putting the S-shaped characteristic curve back (an inverse logistic, the shape the film simulator uses) returns log exposure, the scene as the film saw it. How much of it to
   put back is a control, because the base density is only an estimate unless a rebate was sampled.
4. Balance. Each channel's log exposure is scaled and shifted so the three channels cover the same range (the picture's 2nd to 98th percentile): this removes the film's orange
   mask and any difference between the layers.
5. The print. Log exposure goes through a paper curve: a straight line of slope k (the grade) between a toe that rolls the shadows into paper black and a shoulder that rolls the
   highlights into paper white. The slope is set so the picture's own range (2nd to 98th percentile) fills the paper's usable range, and the picture's middle prints near a middle
   grey, both only partly, so a plainly dark or bright picture keeps its mood.
6. Light. The print density becomes reflectance measured against the paper (paper white is 1, paper black is 0) and is encoded for the display.

Stages 3 to 6 are one curve per channel of the unmixed density, so they are built as a lookup table over density codes, which is how the rest of the editor applies tone."""

import json
import os
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

# density image
TRANSFER_CURVES = ("srgb", "bt709", "linear")   # how a scan's codes were encoded from light (see density_table)
DENSITY_SCALE = 13000.0     # density codes per unit of density (uint16: densities up to 5.04)
# paper
D_MIN = 0.06                # density of paper white
D_MAX = 2.3                 # density of paper black
TOE_SHARPNESS = 5.0         # how tight the roll-off into paper black is (higher is tighter)
SHOULDER_SHARPNESS = 3.0
MID_DENSITY = 0.75          # the density the picture's middle prints at (about 18% reflectance)
PRINT_LOW, PRINT_HIGH = 0.12, 1.95   # the print densities the picture's 2nd and 98th percentile aim at
SLOPE_RANGE = (0.5, 2.2)
TRIM_RANGE = (-0.3, 0.3)
SHADOW_REACH = 1.9          # the print density the picture's darkest tail should reach
REACH_LIMIT = 1.25          # how much harder than the range-fitted grade shadow reach may make it
# film
FILM_RANGE = 2.5            # density a layer gains from its base to its maximum
FILM_GAMMA = 0.62           # slope of the layer's curve at its middle
UNSURE_BASE = 0.35          # how much of the restore applies when the base was only estimated
RESTORE_MARGIN = 0.05       # net density (as a share of the range) beyond which the S is not restored: the base is only an estimate
# metering
RANGE_LOW, RANGE_HIGH = 2.0, 98.0
ANCHOR_STRENGTH = 0.65
RANGE_STRENGTH = 0.8
TRIM = 0.1                  # share of each side of the frame left out of the metering

GENERIC_UNMIX = ((1.0, -0.04, 0.0), (-0.10, 1.0, -0.04), (-0.03, -0.14, 1.0))
GRADE_RANGE = (-0.5, 0.5)
DENSITY_RANGE = (-1.0, 1.0)
TOE_RANGE = (-1.0, 1.0)
SHOULDER_RANGE = (-1.0, 1.0)
RESTORE_RANGE = (0.0, 1.0)
STRENGTH_RANGE = (0.0, 1.0)
_LN10 = float(np.log(10.0))


@dataclass(frozen=True)
class Settings:
    unmix_strength: float = 1.0    # 0 leaves the dyes' crosstalk alone
    unmix_matrix: tuple = GENERIC_UNMIX
    restore: float = 0.6           # 0 leaves the film's curve alone, 1 puts the whole S back
    grade: float = 0.0             # added to the automatic slope (log units); 0 is the automatic grade
    density: float = 0.0           # print density shift: positive prints darker
    trims: tuple = (0.0, 0.0, 0.0)  # per-layer grade (red, green, blue), added to the slope: corrects colour crossover without moving the middle
    toe: float = 0.0               # positive lifts the shadows' roll-off into paper black, negative sharpens it
    shoulder: float = 0.0          # positive holds the highlights back from paper white, negative sharpens the roll-off
    transfer: str = "srgb"         # how the scan is encoded: "srgb", "bt709" (a RAW file decoded with libraw's default curve) or "linear"
    film_range: float = FILM_RANGE
    film_gamma: float = FILM_GAMMA
    hold_black: bool = False       # with a toe lift, the paper's black stays where it was and only the shadows above it are lifted
    stock: str = ""                # a print stock (see STOCKS_FILE): "" is the engine's own paper
    grey_balance: float = 0.0      # how much of the frame's own greys' cast is taken out, shadows to highlights (0 off)
    contrast_mask: float = 0.0     # the darkroom's unsharp contrast mask, as the Fujifilm Frontier's HyperTone does it (0 off)
    bw_weights: tuple | None = None  # B&W from a colour negative: the weights of the three layers' densities in the one density printed (None: colour)
    film: object = None            # a film profile's curve (features/negative/filmcurve.FilmCurve): the film's real toe and shoulder are put back in place of the engine's own S-curve


def _libraw_curve() -> tuple[float, float, float, float]:
    """libraw's default output curve (power 2.222, toe slope 4.5), which is what a RAW decode that is not told otherwise carries: a straight toe, then a power law
    (1 + a) * v**p - a, joined where value and slope agree. These are the rounded numbers of Rec. BT.709 (1.099, 0.099, 0.018), but solved exactly, as libraw's gamma_curve
    does, so the two parts meet without a step. -> (power, slope, knee, offset a), the knee being the encoded value where the toe ends."""
    power, slope = 1.0 / 2.222, 4.5
    lo, hi = 0.0, 1.0
    for _ in range(80):
        knee = 0.5 * (lo + hi)
        join_slope = (1.0 + knee * (1.0 / power - 1.0)) * power * (knee / slope) ** (power - 1.0)
        if join_slope > slope:
            lo = knee
        else:
            hi = knee
    return power, slope, knee, knee * (1.0 / power - 1.0)


_LR_POWER, _LR_SLOPE, _LR_KNEE, _LR_OFFSET = _libraw_curve()


def density_table(dtype, transfer: str = "srgb") -> np.ndarray:
    """The optical density of every code of a scan's depth (256 entries for 8 bits, 65536 for 16). The codes are turned back into light with the curve that made them: sRGB, the
    BT.709 curve (what libraw puts on a RAW file unless told otherwise, so what EFAS's own RAW decode carries), or none for a linear scan. The three differ most in the darkest
    codes - on a negative, the densest parts, which become the positive's highlights - where reading BT.709 codes as sRGB overstates density by up to 0.46."""
    top = 65535 if dtype == np.uint16 else 255
    c = np.arange(top + 1, dtype=np.float64) / top
    if transfer == "linear":
        t = c
    elif transfer == "bt709":
        t = np.where(c < _LR_KNEE, c / _LR_SLOPE, np.power((c + _LR_OFFSET) / (1.0 + _LR_OFFSET), 1.0 / _LR_POWER))
    else:
        t = np.where(c <= 0.04045, c / 12.92, np.power((c + 0.055) / 1.055, 2.4))
    return (-np.log10(np.clip(t, 1e-5, 1.0))).astype(np.float32)


# B&W from a colour negative (NegPy's features/exposure/bw_filter.py): the weights of the red, green and blue layers' densities in the one density that is printed, a least-squares fit of
# a panchromatic film (Tri-X / HP5 like) behind each Wratten filter on Portra 400's layer sensitivities under 5500 K. Each row sums to 1, so a grey does not move.
BW_FILTERS = {
    "": None,
    "none": (0.31, 0.39, 0.30),
    "yellow8": (0.47, 0.57, -0.04),
    "deepyellow15": (0.56, 0.50, -0.06),
    "orange21": (0.72, 0.32, -0.04),
    "red25": (1.06, -0.06, 0.00),
    "yellowgreen11": (0.25, 0.78, -0.03),
    "green58": (0.04, 1.08, -0.12),
}
BW_FILTER_NAMES = {"": "Off (colour print)", "none": "Panchromatic (no filter)", "yellow8": "Yellow (Wratten 8)", "deepyellow15": "Deep yellow (15)", "orange21": "Orange (21)",
                   "red25": "Red (25)", "yellowgreen11": "Yellow-green (11)", "green58": "Green (58)"}


def mixing_matrix(matrix, strength: float) -> np.ndarray:
    """The unmixing matrix blended toward the identity by `strength`, each row summing to 1 so greys stay grey."""
    s = min(max(float(strength), 0.0), 1.0)
    m = np.eye(3) * (1.0 - s) + np.asarray(matrix, dtype=np.float64) * s
    sums = m.sum(axis=1, keepdims=True)
    return m / np.where(np.abs(sums) < 1e-6, 1.0, sums)


def density_codes(pixels: np.ndarray, settings: Settings = Settings()) -> np.ndarray:
    """The scan as a density image: uint16 codes, density = code / DENSITY_SCALE, with the dyes' crosstalk taken out."""
    table = density_table(pixels.dtype, settings.transfer)
    m = mixing_matrix(settings.unmix_matrix, settings.unmix_strength).astype(np.float32)
    unmix = not np.allclose(m, np.eye(3), atol=1e-6)
    h, w = pixels.shape[:2]
    out = np.empty((h, w, 3), dtype=np.uint16)
    step = max(1, (1 << 21) // max(w, 1))
    for y in range(0, h, step):
        d = table[pixels[y:y + step]]
        if unmix:
            d = d @ m.T
        if settings.bw_weights is not None:      # B&W from colour: one density, from the layers' own through the filter's weights, on all three channels
            d = np.repeat((d @ np.asarray(settings.bw_weights, dtype=np.float32))[..., None], 3, axis=-1)
        out[y:y + step] = np.clip(np.rint(d * DENSITY_SCALE), 0, 65535).astype(np.uint16)
    return out


def base_density(rgb, settings: Settings = Settings(), top: float = 255.0) -> np.ndarray:
    """The density of a sampled film base (a colour as the picture shows it), through the same unmixing as the picture."""
    dtype = np.uint16 if top > 255 else np.uint8
    table = density_table(dtype, settings.transfer)
    d = np.array([table[int(round(min(max(float(v), 0.0), top)))] for v in rgb], dtype=np.float32)
    return d @ mixing_matrix(settings.unmix_matrix, settings.unmix_strength).T.astype(np.float32)


def restore_exposure(density: np.ndarray, base, strength: float, film_range: float, film_gamma: float) -> np.ndarray:
    """Log10 exposure (up to a constant) from density above the base: the inverse of the layer's S-shaped curve, blended with a straight line by `strength`."""
    net = density - base
    s = 4.0 * film_gamma / (film_range * _LN10)
    straight = net / film_gamma
    if strength <= 0.0:
        return straight
    lo = RESTORE_MARGIN * film_range
    n = np.clip(net, lo, film_range - lo)
    s_curve = np.log10(n / (film_range - n)) / s
    # beyond the clipped ends carry on along the straight line so the order of tones never reverses
    s_curve = s_curve + np.where(net < lo, (net - lo) / film_gamma, 0.0) + np.where(net > film_range - lo, (net - (film_range - lo)) / film_gamma, 0.0)
    return strength * s_curve + (1.0 - strength) * straight


def estimate_base(density: np.ndarray) -> np.ndarray:
    """Each channel's base density, taken as just under its thinnest readings (a scene's deepest shadow is never quite clear film)."""
    return np.percentile(density.reshape(-1, 3), 0.3, axis=0) - 0.04


STOCKS_FILE = Path(__file__).resolve().parents[2] / "assets" / "print_stocks" / "stocks.json"
HOLD_TAPER = 0.6            # Hold Black: the density (below the lifted black) over which the lift fades out, so the black point stays and the curve stays rising


@dataclass(frozen=True)
class Curve:
    """A paper's (or print stock's) character: its density at white and at black, how tight the knees are, the straight line's slope against the engine's own, the layers' slopes
    against green's, and the colour of its dyes as a density matrix (rows sum to 1)."""
    d_min: float = D_MIN
    d_max: float = D_MAX
    toe: float = TOE_SHARPNESS
    shoulder: float = SHOULDER_SHARPNESS
    slope_gain: float = 1.0
    channel_gamma: tuple = (1.0, 1.0, 1.0)
    matrix: tuple | None = None


DEFAULT_CURVE = Curve()


@lru_cache(maxsize=1)
def stocks() -> dict:
    """The print stocks that come with EFAS (assets/print_stocks/stocks.json, from NegPy's profiles): {key: {label, short, kind, medium, d_max, ...}}; {} when the file is not there."""
    try:
        return json.loads(STOCKS_FILE.read_text(encoding="utf-8"))["stocks"]
    except (OSError, ValueError, KeyError):
        return {}


def stock_groups() -> list[tuple[str, list[tuple[str, str]]]]:
    """The stocks for a menu, grouped as NegPy groups them: Digital, Paper (colour then black-and-white) and Print film -> [(group, [(key, label)])]."""
    out: dict[str, list[tuple[str, str]]] = {"Digital": [], "Colour paper": [], "Black-and-white paper": [], "Print film": []}
    for key, s in stocks().items():
        if key == "neutral":
            continue
        group = "Digital" if s["medium"] == "digital" else "Print film" if s["medium"] == "film" else "Black-and-white paper" if s["kind"] == "bw" else "Colour paper"
        out[group].append((key, s["label"]))
    return [(g, items) for g, items in out.items() if items]


def curve_for(stock: str) -> Curve:
    """The Curve of a print stock (the engine's own paper for "" or a stock that is not there). The knees are NegPy's sharpness figures against its neutral paper's (6 and 3), here
    against this engine's (5 and 3); a black-and-white stock is tonal only."""
    s = stocks().get(stock)
    if not s or stock == "neutral":
        return DEFAULT_CURVE
    return Curve(d_min=float(s["d_min"]), d_max=float(s["d_max"]), toe=TOE_SHARPNESS * float(s["toe_sharpness_base"]) / 6.0, shoulder=SHOULDER_SHARPNESS * float(s["shoulder_sharpness_base"]) / 3.0,
                 slope_gain=float(s["slope_gain"] or 1.0), channel_gamma=tuple(float(x) for x in (s["channel_gamma"] or (1.0, 1.0, 1.0))),
                 matrix=tuple(tuple(float(x) for x in row) for row in s["matrix"]) if s.get("matrix") and s["kind"] != "bw" else None)


def paper(v, toe: float = 0.0, shoulder: float = 0.0, curve: Curve = DEFAULT_CURVE, hold_black: bool = False):
    """Print density from the straight-line density v: bounded below by paper white and above by paper black, each through a smooth knee. With `hold_black` a toe lift fades out toward
    the black, so the paper's black stays where it was and only the shadows above it are lifted."""
    v = np.asarray(v, dtype=np.float64)
    d_min = curve.d_min + max(shoulder, 0.0) * 0.3
    d_max = curve.d_max - max(toe, 0.0) * 0.8
    a_hi = curve.shoulder * (1.0 - min(shoulder, 0.0) * 2.0)
    a_lo = curve.toe * (1.0 - min(toe, 0.0) * 2.0)
    v1 = d_min + np.logaddexp(0.0, a_hi * (v - d_min)) / a_hi
    out = d_max - np.logaddexp(0.0, a_lo * (d_max - v1)) / a_lo
    if hold_black and toe > 0.0:
        plain = paper(v, 0.0, shoulder, curve)
        t = np.clip((d_max - out) / HOLD_TAPER, 0.0, 1.0)
        out = plain + (t * t * (3.0 - 2.0 * t)) * (out - plain)
    return out


def reflectance(d_print, curve: Curve = DEFAULT_CURVE) -> np.ndarray:
    """Light from print density, measured against the paper itself: paper white reflects as 1 and paper black as 0 (black point compensation, as a display treats it)."""
    t = np.power(10.0, -np.asarray(d_print, dtype=np.float64)) * 10.0 ** curve.d_min
    black = 10.0 ** -(curve.d_max - curve.d_min)
    return np.maximum((t - black) / (1.0 - black), 0.0)


def _oetf(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return np.where(t <= 0.0031308, t * 12.92, 1.055 * np.power(t, 1 / 2.4) - 0.055)


@lru_cache(maxsize=64)
def _value_for(target: float, curve: Curve = DEFAULT_CURVE) -> float:
    """The straight-line density the paper maps onto the print density `target`."""
    lo, hi = -2.0, 6.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if float(paper(mid, curve=curve)) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _mid_value(curve: Curve = DEFAULT_CURVE) -> float:
    return _value_for(MID_DENSITY, curve)


_V_MID = _mid_value()



def analysis_block(codes: np.ndarray, trim: float = TRIM, max_dim: int = 256) -> np.ndarray:
    """The picture's own part of a density image, thinned out for metering: the frame less its edges."""
    h, w = codes.shape[:2]
    my, mx = int(h * trim), int(w * trim)
    core = codes[my:h - my, mx:w - mx] if (h - 2 * my > 8 and w - 2 * mx > 8) else codes
    step = max(1, int(np.ceil(max(core.shape[:2]) / max_dim)))
    return core[::step, ::step]


CAST_BAND_QUANTILES = ((5, 30), (35, 65), (70, 95))     # the shadows, the middle and the highlights, as shares of the frame's brightness
CAST_MIN_PIXELS = 150                                   # a band with fewer neutral pixels than this has no say
CAST_CONFIDENCE_N0 = 400.0                              # how many neutral pixels it takes to be half sure
CAST_FIRST_CAP = 0.35                                   # the loose first pass: a strong but correctable cast keeps its greys
CAST_STRICT_CAP = 0.10                                  # the strict second pass: a grey is this close to the first pass's grey (log exposure), or it is not a grey
CAST_FOLIAGE = 0.06                                     # a pixel this much greener than the grey in both of its colour differences is leaves or grass, not a grey
CAST_SKY = (0.08, 0.03)                                 # bluer than the grey by the first and redder by the second at once is sky or water
MASK_BLUR_PERCENT = 4.0                                 # the contrast mask's blur: this share of the frame's short side
MASK_CODES_PER_DENSITY = 145.0                          # the Frontier's 10-bit print codes in one unit of density (set by eye, as NegPy sets it)
MASK_TABLE_CAP = 407.0                                  # the Frontier's HyperTone table is capped at 819 codes, 407 above its middle grey at 412
MASK_SHARE = 0.25                                       # a quarter of the table is added, times the slider


class Cast:
    """The cast the frame's own greys carry, as an offset of red and of blue against green at each brightness (so it is a function of the exposure alone, which a table of one layer can hold)."""

    def __init__(self, centres, red, blue, confidence: float, strength: float):
        self.centres, self.red, self.blue = np.asarray(centres), np.asarray(red), np.asarray(blue)
        self.weight = float(strength) * float(confidence)

    def shift(self, channel: int, e: np.ndarray) -> np.ndarray:
        """How far a layer's exposure `e` is moved: its cast offset at that brightness, times the share to take out."""
        if channel == 1 or self.weight <= 0.0:
            return np.zeros_like(e)
        offsets = self.red if channel == 0 else self.blue
        return (self.weight * np.interp(e, self.centres, offsets)).astype(e.dtype)


def neutral_cast(es: np.ndarray, strength: float) -> "Cast | None":
    """The cast of a frame's greys, found as NegPy's Cast Removal finds it: in a band of the shadows, of the middle and of the highlights, the pixels whose colour is closest to the
    band's own (the lowest chroma), a loose first pass to find where the greys lie and a strict second one that leaves out leaves and grass (greener than the grey on both counts) and sky
    and water (bluer and less red); the median offset of what is left, per band, and how sure it can be (the pixels it stands on, and how well the bands agree). None for a frame with
    no neutral to read. `es` is the frame's balanced exposures, (n, 3)."""
    if strength <= 0.0 or es.shape[0] < 4 * CAST_MIN_PIXELS:
        return None
    luma = es.mean(axis=1)
    a, b = es[:, 0] - es[:, 1], es[:, 2] - es[:, 1]
    found = []
    for lo_q, hi_q in CAST_BAND_QUANTILES:
        lo, hi = np.percentile(luma, [lo_q, hi_q])
        m = (luma >= lo) & (luma <= hi)
        if int(m.sum()) < 2 * CAST_MIN_PIXELS:
            continue
        aa, bb = a[m], b[m]
        chroma = np.hypot(aa, bb)
        first = chroma <= min(float(np.quantile(chroma, 0.30)), CAST_FIRST_CAP)
        if int(first.sum()) < CAST_MIN_PIXELS // 2:
            continue
        a1, b1 = float(np.median(aa[first])), float(np.median(bb[first]))
        da, db = aa - a1, bb - b1
        second = np.hypot(da, db)
        keep = second <= min(float(np.quantile(second, 0.30)), CAST_STRICT_CAP)
        keep &= ~((da < -CAST_FOLIAGE) & (db < -CAST_FOLIAGE))
        keep &= ~((db > CAST_SKY[0]) & (da < -CAST_SKY[1]))
        if int(keep.sum()) < CAST_MIN_PIXELS:
            continue
        found.append((float(np.median(luma[m])), float(np.median(aa[keep])), float(np.median(bb[keep])), int(keep.sum())))
    if not found:
        return None
    n = sum(f[3] for f in found)
    spread = float(np.hypot(np.std([f[1] for f in found]), np.std([f[2] for f in found]))) if len(found) > 1 else 0.05
    confidence = (n / (n + CAST_CONFIDENCE_N0)) * float(np.exp(-spread / 0.15))
    found.sort()
    return Cast([f[0] for f in found], [f[1] for f in found], [f[2] for f in found], confidence, strength)


@dataclass(frozen=True, eq=False)
class PrintBuild:
    """What a picture's metering gave: the conversion's table, and the numbers that made it, which the stages that work on each pixel before the table (the contrast mask, a stock's
    dyes) read: the exposure each density code stands for, the slope and where the middle sits."""
    lut: np.ndarray            # (3, 65536) display values, 0-255
    e_tables: np.ndarray       # (3, 65536) the (balanced, cast-removed) exposure of every density code
    k: float
    anchor: float
    v_mid: float
    curve: Curve
    settings: Settings


def build_print(block: np.ndarray, settings: Settings = Settings(), base: np.ndarray | None = None) -> PrintBuild:
    """The table (and what it was made from) for a picture whose metering block is `block` (density codes). `base` is the film base density per channel when it was sampled; else it
    is estimated from the block."""
    curve = curve_for(settings.stock)
    v_mid = _mid_value(curve)
    d = block.astype(np.float32) / DENSITY_SCALE
    known = base is not None
    b = np.asarray(base, dtype=np.float32) if known else estimate_base(d)
    strength = settings.restore * (1.0 if known else UNSURE_BASE)   # the S is only put back as far as the base is trusted
    film = settings.film
    if film is not None:
        # the exposure each density implies through the profile's curve, laid on its straight line (the table already counts for less with an estimated base): `restore` blends it with plain density
        rest = lambda x, c: ((x - b[c]) + settings.restore * (film(x, c) - x)) / float(film.slopes[c])
    else:
        rest = lambda x, c: restore_exposure(x, b[c], strength, settings.film_range, settings.film_gamma)
    crop_e = np.stack([rest(d[..., c], c) for c in range(3)], axis=-1)
    hi = np.percentile(crop_e.reshape(-1, 3), RANGE_HIGH, axis=0)
    lo = np.percentile(crop_e.reshape(-1, 3), RANGE_LOW, axis=0)
    span = np.maximum(hi - lo, 1e-3)
    mean_span = float(np.mean(span))
    scale = mean_span / span
    shift = float(np.mean(lo)) - lo * scale
    balanced = crop_e * scale + shift
    cast = neutral_cast(balanced.reshape(-1, 3)[:: max(1, balanced.shape[0] * balanced.shape[1] // 60000)], settings.grey_balance) if settings.grey_balance > 0 else None
    if cast is not None:
        balanced = np.stack([balanced[..., c] - cast.shift(c, balanced[..., c]) for c in range(3)], axis=-1)
    luma = balanced.mean(axis=2).ravel()
    lo2, hi2 = np.percentile(luma, [RANGE_LOW, RANGE_HIGH])
    median = float(np.median(luma))
    span2 = max(float(hi2 - lo2), 0.2)
    k_full = (PRINT_HIGH - PRINT_LOW) / span2
    k_norm = (PRINT_HIGH - PRINT_LOW) / 2.2
    anchor = ANCHOR_STRENGTH * median + (1.0 - ANCHOR_STRENGTH) * 0.5 * (lo2 + hi2)
    k = RANGE_STRENGTH * k_full + (1.0 - RANGE_STRENGTH) * k_norm
    if anchor - lo2 > 1e-3:   # shadow reach: a flat negative's dark tail still has to print dark, so the slope is raised to the line through the middle and that tail
        k = min(max(k, (_value_for(SHADOW_REACH, curve) - v_mid) / (anchor - lo2)), k * REACH_LIMIT)
    k = float(min(max((k + settings.grade) * curve.slope_gain, SLOPE_RANGE[0]), SLOPE_RANGE[1]))
    codes = np.arange(65536, dtype=np.float32) / DENSITY_SCALE
    lut = np.empty((3, 65536), dtype=np.float32)
    tables = np.empty((3, 65536), dtype=np.float32)
    for c in range(3):
        e = rest(codes, c) * scale[c] + shift[c]
        if cast is not None:
            e = e - cast.shift(c, e)
        tables[c] = np.maximum.accumulate(e)
        k_c = min(max(k * curve.channel_gamma[c] + min(max(settings.trims[c], TRIM_RANGE[0]), TRIM_RANGE[1]), SLOPE_RANGE[0]), SLOPE_RANGE[1])
        v = k_c * (anchor - tables[c]) + v_mid + settings.density
        lut[c] = _oetf(reflectance(paper(v, settings.toe, settings.shoulder, curve, settings.hold_black), curve)) * 255.0
    return PrintBuild(lut, tables, k, anchor, v_mid, curve, settings)


def build_lut(block: np.ndarray, settings: Settings = Settings(), base: np.ndarray | None = None) -> np.ndarray:
    """(3, 65536) display values, 0-255 (float), indexed by density code, for a picture whose metering block is `block` (density codes): see build_print."""
    return build_print(block, settings, base).lut


def mask_plane(codes: np.ndarray, built: PrintBuild, max_dim: int = 512) -> np.ndarray:
    """The contrast mask's plane: the frame's brightness (the mean of its layers' exposures) blurred over MASK_BLUR_PERCENT of its short side, on a grid thinned to `max_dim`. Expensive
    enough to keep while a slider moves; mask_shift turns it into the exposure shift."""
    import cv2

    step = max(1, int(np.ceil(max(codes.shape[:2]) / max_dim)))
    small = codes[::step, ::step]
    e = sum(built.e_tables[c][small[..., c]] for c in range(3)) / 3.0
    sigma = max(1.0, MASK_BLUR_PERCENT / 100.0 * min(e.shape))
    return cv2.GaussianBlur(np.ascontiguousarray(e, dtype=np.float32), (0, 0), sigma, borderType=cv2.BORDER_REPLICATE)


def mask_shift(plane: np.ndarray, built: PrintBuild, strength: float) -> np.ndarray:
    """The exposure each point of the plane is moved by, for a contrast mask of `strength` (0 to 1): the Fujifilm Frontier's HyperTone table, which opens up large dark areas and holds back
    large bright ones. The print density the blurred picture would have, against the middle grey's, goes through sign(x) (145 x)^2 / 256 (capped), a quarter of it times the slider is
    added to the print density of the other side (so a dark area is lightened), and that shift in print density becomes a shift in exposure at the print's slope."""
    s = built.settings
    v = built.k * (built.anchor - plane) + built.v_mid + s.density
    dev = paper(v, s.toe, s.shoulder, built.curve, s.hold_black) - MID_DENSITY
    table = np.sign(dev) * np.minimum((MASK_CODES_PER_DENSITY * np.abs(dev)) ** 2 / 256.0, MASK_TABLE_CAP)
    return (strength * MASK_SHARE * table / MASK_CODES_PER_DENSITY / built.k).astype(np.float32)


def shape_codes(codes: np.ndarray, built: PrintBuild, shift: np.ndarray | None = None, matrix: np.ndarray | None = None) -> np.ndarray:
    """The density image with each pixel's exposure moved before the conversion's table reads it: by `shift` (an exposure plane the size of the picture: the contrast mask) and mixed by
    `matrix` (3 x 3, rows summing to 1: a print stock's dyes). Works in strips of rows so a large picture needs no large float copy."""
    axis = np.arange(65536, dtype=np.float32)
    out = np.empty_like(codes)
    step = max(1, (1 << 20) // max(codes.shape[1], 1))
    for y in range(0, codes.shape[0], step):
        strip = codes[y:y + step]
        e = np.stack([built.e_tables[c][strip[..., c]] for c in range(3)], axis=-1)
        if shift is not None:
            e = e + shift[y:y + step][..., None]
        if matrix is not None:
            e = e @ matrix.T.astype(np.float32)
        for c in range(3):
            out[y:y + step, :, c] = np.clip(np.rint(np.interp(e[..., c], built.e_tables[c], axis)), 0, 65535).astype(np.uint16)
    return out


def apply_lut(codes: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """An 8-bit picture from density codes and a lookup table."""
    out = np.empty(codes.shape, dtype=np.uint8)
    for c in range(3):
        out[..., c] = np.clip(np.rint(lut[c][codes[..., c]]), 0, 255)
    return out


def convert(scan: np.ndarray, settings: Settings = Settings(), base_rgb=None) -> np.ndarray:
    """An 8-bit positive from a scan (uint16 or uint8, HxWx3); `base_rgb` is a sampled film base in the scan's own codes."""
    codes = density_codes(scan, settings)
    base = None if base_rgb is None else base_density(base_rgb, settings, 65535.0 if scan.dtype == np.uint16 else 255.0)
    return apply_lut(codes, build_lut(analysis_block(codes), settings, base))


def benchmark_converters() -> dict:
    """The engine's variants for tools/benchmark_conversion.py."""
    variants = {
        "print": (Settings(), False),
        "print restore0": (Settings(restore=0.0), False),
        "print +rebate": (Settings(), True),
        "print restore1 +rebate": (Settings(restore=1.0), True),
    }

    def make(s, with_base):
        def run(scan16, info):
            codes = density_codes(scan16, s)
            film = info.get("film")
            base = None
            if with_base and film is not None:   # a sampled rebate: the film's own base density, as the scan measured it
                base = (np.asarray(film.d_min, dtype=np.float32) @ mixing_matrix(s.unmix_matrix, s.unmix_strength).T.astype(np.float32))
            return apply_lut(codes, build_lut(analysis_block(codes), s, base))
        return run

    return {name: make(*v) for name, v in variants.items()}


# ---------------------------------------------------------------- film profiles
GENERIC_ID, NONE_ID = "generic", "none"
_BUNDLED = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "crosstalk")


def _read_folder(folder: str, prefix: str) -> dict[str, dict]:
    found: dict[str, dict] = {}
    if not os.path.isdir(folder):
        return found
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith(".toml"):
            continue
        try:
            with open(os.path.join(folder, name), "rb") as fh:
                data = tomllib.load(fh)
            matrix = np.asarray(data["matrix"], dtype=float)
            if matrix.shape == (3, 3) and np.all(np.isfinite(matrix)):
                found[prefix + name[:-5]] = {"name": str(data.get("name") or name[:-5]), "matrix": tuple(tuple(float(v) for v in row) for row in matrix),
                                             "source": "yours" if prefix else "bundled"}
        except (OSError, ValueError, KeyError, TypeError, tomllib.TOMLDecodeError):
            continue
    return found


def user_folder() -> str:
    from ..datadir import app_data_dir

    return os.path.join(app_data_dir(), "crosstalk")


def profiles() -> dict[str, dict]:
    """Every crosstalk profile there is, in the order a menu lists them: id -> {"name", "matrix", "source"}. The generic colour negative and "none" come first, then the
    bundled film profiles by name, then any the user put in the data folder's crosstalk folder (ids start with "user:")."""
    out = {GENERIC_ID: {"name": "Generic colour negative", "matrix": GENERIC_UNMIX, "source": "built in"},
           NONE_ID: {"name": "None (no crosstalk correction)", "matrix": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), "source": "built in"}}
    bundled = _read_folder(_BUNDLED, "")
    out.update(dict(sorted(bundled.items(), key=lambda kv: kv[1]["name"].casefold())))
    try:
        out.update(dict(sorted(_read_folder(user_folder(), "user:").items(), key=lambda kv: kv[1]["name"].casefold())))
    except OSError:
        pass
    return out


def matrix_for(profile_id: str) -> tuple:
    """The matrix of a profile; the generic one for an id that is not there (a profile file that was removed)."""
    found = profiles().get(profile_id)
    return found["matrix"] if found else GENERIC_UNMIX
