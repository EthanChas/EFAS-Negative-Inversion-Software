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

import os
import tomllib
from dataclasses import dataclass

import numpy as np

# density image
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
    transfer: str = "srgb"         # how the scan is encoded: "srgb" or "linear"
    film_range: float = FILM_RANGE
    film_gamma: float = FILM_GAMMA


def density_table(dtype, transfer: str = "srgb") -> np.ndarray:
    """The optical density of every code of a scan's depth (256 entries for 8 bits, 65536 for 16)."""
    top = 65535 if dtype == np.uint16 else 255
    c = np.arange(top + 1, dtype=np.float64) / top
    t = c if transfer == "linear" else np.where(c <= 0.04045, c / 12.92, np.power((c + 0.055) / 1.055, 2.4))
    return (-np.log10(np.clip(t, 1e-5, 1.0))).astype(np.float32)


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


def paper(v, toe: float = 0.0, shoulder: float = 0.0):
    """Print density from the straight-line density v: bounded below by paper white and above by paper black, each through a smooth knee."""
    v = np.asarray(v, dtype=np.float64)
    d_min = D_MIN + max(shoulder, 0.0) * 0.3
    d_max = D_MAX - max(toe, 0.0) * 0.8
    a_hi = SHOULDER_SHARPNESS * (1.0 - min(shoulder, 0.0) * 2.0)
    a_lo = TOE_SHARPNESS * (1.0 - min(toe, 0.0) * 2.0)
    v1 = d_min + np.logaddexp(0.0, a_hi * (v - d_min)) / a_hi
    return d_max - np.logaddexp(0.0, a_lo * (d_max - v1)) / a_lo


def reflectance(d_print) -> np.ndarray:
    """Light from print density, measured against the paper itself: paper white reflects as 1 and paper black as 0 (black point compensation, as a display treats it)."""
    t = np.power(10.0, -np.asarray(d_print, dtype=np.float64)) * 10.0 ** D_MIN
    black = 10.0 ** -(D_MAX - D_MIN)
    return np.maximum((t - black) / (1.0 - black), 0.0)


def _oetf(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return np.where(t <= 0.0031308, t * 12.92, 1.055 * np.power(t, 1 / 2.4) - 0.055)


def _value_for(target: float) -> float:
    """The straight-line density the paper maps onto the print density `target`."""
    lo, hi = -2.0, 6.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if float(paper(mid)) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _mid_value() -> float:
    return _value_for(MID_DENSITY)


_V_MID = _mid_value()



def analysis_block(codes: np.ndarray, trim: float = TRIM, max_dim: int = 256) -> np.ndarray:
    """The picture's own part of a density image, thinned out for metering: the frame less its edges."""
    h, w = codes.shape[:2]
    my, mx = int(h * trim), int(w * trim)
    core = codes[my:h - my, mx:w - mx] if (h - 2 * my > 8 and w - 2 * mx > 8) else codes
    step = max(1, int(np.ceil(max(core.shape[:2]) / max_dim)))
    return core[::step, ::step]


def build_lut(block: np.ndarray, settings: Settings = Settings(), base: np.ndarray | None = None) -> np.ndarray:
    """(3, 65536) display values, 0-255 (float), indexed by density code, for a picture whose metering block is `block` (density codes). `base` is the film base density per
    channel when it was sampled; else it is estimated from the block."""
    d = block.astype(np.float32) / DENSITY_SCALE
    known = base is not None
    b = np.asarray(base, dtype=np.float32) if known else estimate_base(d)
    strength = settings.restore * (1.0 if known else UNSURE_BASE)   # the S is only put back as far as the base is trusted
    rest = lambda x, c: restore_exposure(x, b[c], strength, settings.film_range, settings.film_gamma)
    crop_e = np.stack([rest(d[..., c], c) for c in range(3)], axis=-1)
    hi = np.percentile(crop_e.reshape(-1, 3), RANGE_HIGH, axis=0)
    lo = np.percentile(crop_e.reshape(-1, 3), RANGE_LOW, axis=0)
    span = np.maximum(hi - lo, 1e-3)
    mean_span = float(np.mean(span))
    scale = mean_span / span
    shift = float(np.mean(lo)) - lo * scale
    luma = (crop_e * scale + shift).mean(axis=2).ravel()
    lo2, hi2 = np.percentile(luma, [RANGE_LOW, RANGE_HIGH])
    median = float(np.median(luma))
    span2 = max(float(hi2 - lo2), 0.2)
    k_full = (PRINT_HIGH - PRINT_LOW) / span2
    k_norm = (PRINT_HIGH - PRINT_LOW) / 2.2
    anchor = ANCHOR_STRENGTH * median + (1.0 - ANCHOR_STRENGTH) * 0.5 * (lo2 + hi2)
    k = RANGE_STRENGTH * k_full + (1.0 - RANGE_STRENGTH) * k_norm
    if anchor - lo2 > 1e-3:   # shadow reach: a flat negative's dark tail still has to print dark, so the slope is raised to the line through the middle and that tail
        k = min(max(k, (_value_for(SHADOW_REACH) - _V_MID) / (anchor - lo2)), k * REACH_LIMIT)
    k = float(min(max(k + settings.grade, SLOPE_RANGE[0]), SLOPE_RANGE[1]))
    codes = np.arange(65536, dtype=np.float32) / DENSITY_SCALE
    lut = np.empty((3, 65536), dtype=np.float32)
    for c in range(3):
        e = rest(codes, c) * scale[c] + shift[c]
        k_c = min(max(k + min(max(settings.trims[c], TRIM_RANGE[0]), TRIM_RANGE[1]), SLOPE_RANGE[0]), SLOPE_RANGE[1])
        v = k_c * (anchor - e) + _V_MID + settings.density
        lut[c] = _oetf(reflectance(paper(v, settings.toe, settings.shoulder))) * 255.0
    return lut


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
