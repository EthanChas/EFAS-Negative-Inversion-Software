"""The Noritsu look: a numpy port of noritsu-tool (github.com/rohanpandula/noritsu-tool, MIT, "noritsu-tool contributors").

noritsu-tool inverts a C-41 scan in density space the way a Noritsu LS-600 minilab scanner does and renders it with a Noritsu-flavoured tone curve and colour correction. This file follows
its modules one for one: invert.py (density, Dmin / Dmax, the rebate, the film crop), render.py (the tone curve, white balance, saturation), tables.py (the LS-600's base tone curve),
calibrate.py (a fitted per-channel LUT, for its per-stock profiles) and autoparam.py (a thin / normal / dense reading of the negative and the settings it suggests). Each function keeps its
name, its maths and its numbers; what differs is only where it reads its pixels from: EFAS holds a scan as density codes (code / DENSITY_SCALE is the density), so the density step is
already done and the per-channel stages (normalize, white balance, tone) are folded into one table over those codes (`build_lut`), as every other conversion does.

Also here: fitting a profile from a negative and the lab's own positive of it (calibrate.py's calibrate, `fit_profile`), profiles of your own that sit beside the three that come with
noritsu-tool (`stocks`, `import_profile`; they are the same .npz files noritsu-tool writes), and the tone curve of each of the LS-600's IQ variants (`VARIANTS`, tables.py's CommonCalcPara).
Reading an LS-600 FULL*.RAW dump (ls600raw.py) is features/open_image/ls600raw.py. Not ported: its ICE (infrared dust) clean-up (ice.py: it needs the scan's infrared channel, which EFAS
does not read; EFAS has its own dust tools). noritsu-tool's per_film_tables.json is only a record of the headers and first numbers of the vendor's per-film table files (its README says no
code loads it), so there is nothing in it to use. The licence text is in assets/noritsu/LICENSE.
"""

import os
from dataclasses import dataclass, replace

import numpy as np

EPS = 1e-6
DENSITY_SCALE = 13000.0      # printengine.DENSITY_SCALE: the density codes this works on are density * DENSITY_SCALE
STOCKS = ("portra160", "portra400", "superia800")
STOCK_NAMES = {"portra160": "Kodak Portra 160", "portra400": "Kodak Portra 400", "superia800": "Fujifilm Superia 800"}
LOOKS = ("balanced", "punchy", "soft")

# --- tables.py: the LS-600 EZ Controller's CommonCalcPara base tone curve, 20 points (u32, 0..65535) at evenly spaced inputs i / 19, for each IQ variant ---
BASE_CURVES = {
    "00000000": [0, 3449, 6898, 10348, 13797, 17246, 20695, 24144, 27594, 31043, 34492, 37941, 41391, 44840, 48289, 51738, 55187, 58637, 62086, 65535],
    "00000001": [0, 76, 203, 445, 880, 1583, 2633, 4108, 6187, 9214, 13545, 19538, 27390, 36346, 45295, 53128, 58736, 61539, 63657, 65535],
    "00000002": [0, 4, 72, 277, 702, 1434, 2555, 4153, 6382, 9512, 13821, 19588, 26969, 35382, 43975, 51894, 58283, 62386, 64542, 65776],
    "00000003": [0, 76, 203, 445, 880, 1583, 2633, 4108, 6187, 9214, 13545, 19538, 27390, 36346, 45295, 53128, 58736, 61539, 63657, 65535],
    "00000004": [0, 76, 203, 445, 880, 1583, 2633, 4108, 6187, 9214, 13545, 19538, 27390, 36346, 45295, 53128, 58736, 61539, 63657, 65535],
    "00000005": [0, 76, 203, 445, 880, 1583, 2633, 4108, 6187, 9214, 13545, 19538, 27390, 36346, 45295, 53128, 58736, 61539, 63657, 65535],
    "00000006": [0, 76, 203, 445, 880, 1583, 2633, 4108, 6187, 9214, 13545, 19538, 27390, 36346, 45295, 53128, 58736, 61539, 63657, 65535],
}
BASE_CURVE_SCALE = 65535.0
DEFAULT_VARIANT = "00000005"
VARIANTS = {      # the tone curves that really differ (IQ variants 1 and 3 to 6 are the same curve: the LS-600's own, which variant 5, noritsu-tool's default, is one of)
    "00000005": "Standard (the LS-600's own: IQ 1, 3 to 6)",
    "00000002": "IQ 2 (lifted toe, highlights a touch over)",
    "00000000": "Linear (no tone curve)",
}

# --- autoparam.py ---
THIN_DMAX = 0.9       # density range below this = thin negative
DENSE_DMIN = 1.5      # density range above this = dense negative
LOOK_PRESETS = {
    "balanced": {"label": "Balanced (default Noritsu character)", "contrast": 1.05, "sat": 1.0, "toe": 0.02, "gamma_offset": 0.0, "dmax_pct_offset": 0.0},
    "punchy": {"label": "Punchy (more contrast, higher saturation)", "contrast": 1.15, "sat": 1.2, "toe": 0.01, "gamma_offset": -0.05, "dmax_pct_offset": 0.0},
    "soft": {"label": "Soft (lifted shadows, gentle color)", "contrast": 0.95, "sat": 0.9, "toe": 0.04, "gamma_offset": 0.05, "dmax_pct_offset": -0.5},
}
CLASS_BASE = {
    "thin": {"gamma": 0.75, "dmax_pct": 98.0, "description": "Thin/underexposed negative: low gamma + narrow Dmax"},
    "normal": {"gamma": 0.98, "dmax_pct": 99.5, "description": "Normal negative: standard parameters"},
    "dense": {"gamma": 1.0, "dmax_pct": 99.8, "description": "Dense/overexposed negative: higher gamma + wider Dmax"},
}

# the largest picture the statistics are read from, in pixels (a bigger scan is read at every k-th pixel of every k-th row, which gives the same percentiles and means)
ANALYSIS_PIXELS = 2_000_000

# film_valid_mask works on the brightest channel's transmittance; in density that is the smallest channel's: a pixel is on film when it is darker than the clear margin (transmittance < 0.9)
CLEAR_DENSITY = -np.log10(0.9)


@dataclass(frozen=True)
class Settings:
    """cli.py's options: the render group (--contrast --toe --gamma --sat --real-curve --lab --stock, auto white balance) and the inversion group (--dmin-pct --dmax-pct --no-border)."""
    stock: str = ""                  # "" (none) or one of STOCKS: noritsu-tool's per-stock calibration profile, which replaces the white balance and the tone curve
    lab: bool = False                # "lab mode": contrast 0.90, gamma 0.90, toe 0.04, saturation 0.95 and the real tone curve
    real_curve: bool = False         # the LS-600's own 20-point curve instead of the synthetic S-curve
    variant: str = DEFAULT_VARIANT   # which IQ variant's 20-point curve the real curve is (VARIANTS)
    contrast: float = 1.05
    toe: float = 0.02
    gamma: float = 0.98
    saturation: float = 1.0
    dmin_pct: float = 0.5
    dmax_pct: float = 99.8           # (cli.py's default; process_negative's own is 99.95)
    use_border: bool = True          # Dmin from the film rebate when it looks like the orange mask
    auto_wb: bool = True

    def effective(self) -> "Settings":
        """Lab mode overrides the tone settings, as cli.run_one does."""
        if not self.lab:
            return self
        return replace(self, contrast=0.90, gamma=0.90, toe=0.04, saturation=0.95, real_curve=True)


# ---------------------------------------------------------------------------
# tables.py
# ---------------------------------------------------------------------------

def load_base_tone_curve(variant: str = DEFAULT_VARIANT) -> list[float] | None:
    """The base tone curve normalized to [0,1] (a couple of variants overshoot full scale by <0.4%: clamped)."""
    u32 = BASE_CURVES.get(variant)
    if u32 is None:
        return None
    return [min(1.0, max(0.0, v / BASE_CURVE_SCALE)) for v in u32]


def tone_curve_lut(n: int = 4096, variant: str = DEFAULT_VARIANT) -> list[float] | None:
    """An n-entry LUT from the real base tone curve (linear interpolation)."""
    curve = load_base_tone_curve(variant)
    if curve is None:
        return None
    m = len(curve)
    lut = []
    for i in range(n):
        x = i / (n - 1) * (m - 1)
        i0 = int(x)
        i1 = min(i0 + 1, m - 1)
        t = x - i0
        lut.append(curve[i0] * (1 - t) + curve[i1] * t)
    return lut


# ---------------------------------------------------------------------------
# invert.py (on density: D = -log10(transmittance), here code / DENSITY_SCALE)
# ---------------------------------------------------------------------------

def estimate_dmin(density: np.ndarray, percentile: float = 0.5, mask: np.ndarray | None = None) -> np.ndarray:
    """Per-channel Dmin (film base + fog = orange mask): a low percentile of the clearest film areas."""
    d = density if mask is None else density[mask]
    return np.percentile(d.reshape(-1, 3), percentile, axis=0)


def estimate_dmax(density: np.ndarray, percentile: float = 99.8, mask: np.ndarray | None = None) -> np.ndarray:
    """Per-channel Dmax (the densest meaningful image area)."""
    d = density if mask is None else density[mask]
    return np.percentile(d.reshape(-1, 3), percentile, axis=0)


def border_mask(shape, frac: float = 0.03) -> np.ndarray:
    """Boolean mask of the outer ring (film rebate / border)."""
    h, w = shape[0], shape[1]
    m = np.zeros((h, w), dtype=bool)
    bh = max(1, int(h * frac))
    bw = max(1, int(w * frac))
    m[:bh, :] = True
    m[-bh:, :] = True
    m[:, :bw] = True
    m[:, -bw:] = True
    return m


def film_valid_mask(density: np.ndarray, black_th: float = 0.005, clear_th: float = 0.9) -> np.ndarray:
    """On-film pixels, without the clear (non-film) margins and the black scan borders, so density statistics reflect the film only. invert.film_valid_mask takes the brightest channel's
    transmittance: mx < clear_th and mx > black_th, which is the smallest channel's density above -log10(clear_th) and below -log10(black_th)."""
    low = density.min(axis=2)
    on = low > -np.log10(clear_th)
    if black_th > 0:
        on &= low < -np.log10(black_th)
    return on


def crop_to_film(density: np.ndarray, pad: int = 0, min_frac: float = 0.3, row_thresh: float = 0.5):
    """The film frame without clear margins and black scan borders: rows and columns where a majority of pixels are on film. -> (cropped, (r0, r1, c0, c1))."""
    h, w = density.shape[:2]
    whole = (0, h, 0, w)
    m = film_valid_mask(density, black_th=0.03)
    if m.mean() < min_frac:
        return density, whole
    rows = np.where(m.mean(axis=1) > row_thresh)[0]
    cols = np.where(m.mean(axis=0) > row_thresh)[0]
    if rows.size == 0 or cols.size == 0:
        return density, whole
    r0, r1 = rows[0], rows[-1] + 1
    c0, c1 = cols[0], cols[-1] + 1
    r0 = max(0, r0 - pad)
    c0 = max(0, c0 - pad)
    r1 = min(h, r1 + pad)
    c1 = min(w, c1 + pad)
    return density[r0:r1, c0:c1], (int(r0), int(r1), int(c0), int(c1))


def estimate_dmin_border(density: np.ndarray, frac: float = 0.03):
    """Dmin from the film rebate (the outer ring). A true rebate is uniform (low spread) and reads as orange mask, the blue channel densest; otherwise None (the percentile is used)."""
    m = border_mask(density.shape, frac)
    d = density[m]
    med = np.median(d, axis=0)
    std = d.std(axis=0)
    if med[2] > med[1] >= med[0] - 1e-3 and med.mean() > 0.1 and std.mean() < 0.15:
        return med.astype(np.float32)
    return None


def normalize(density: np.ndarray, dmin, rng, clip_shadow: float = 0.0, clip_highlight: float = 0.0) -> np.ndarray:
    """Scene density with the mask removed, normalized to [0,1] (high = bright scene)."""
    norm = (density - np.asarray(dmin)[None, None, :]) / np.asarray(rng)[None, None, :]
    lo = clip_shadow
    hi = 1.0 + clip_highlight
    norm = (norm - lo) / (hi - lo)
    return np.clip(norm, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# render.py
# ---------------------------------------------------------------------------

def noritsu_tone_curve(x, contrast: float = 1.0, toe: float = 0.0, gamma: float = 1.0) -> np.ndarray:
    """A Noritsu-flavoured S-curve: a slightly lifted toe, a long straight section and a soft shoulder, from control points. contrast > 1 is punchier; toe lifts the shadows; gamma is applied
    after the S-curve."""
    x = np.clip(x, 0.0, 1.0)
    k = contrast
    pts_x = np.array([0.0, 0.08, 0.25, 0.5, 0.75, 0.92, 1.0], dtype=np.float32)
    mid = 0.5
    pts_y = mid + (pts_x - mid) * k
    pts_y = pts_y + toe * (1.0 - pts_x) * np.exp(-pts_x * 4.0)
    pts_y = np.clip(pts_y, 0.0, 1.0)
    for i in range(1, len(pts_y)):
        if pts_y[i] < pts_y[i - 1]:
            pts_y[i] = pts_y[i - 1]
    out = np.interp(x, pts_x, pts_y)
    if gamma != 1.0:
        out = out ** gamma
    return out.astype(np.float32)


def white_balance(img: np.ndarray, gains) -> np.ndarray:
    """Per-channel multiplicative white-balance gains (R, G, B)."""
    g = np.asarray(gains, dtype=np.float32).reshape(1, 1, 3)
    return np.clip(img * g, 0.0, 1.0)


def to_ycbcr_like(img: np.ndarray):
    """RGB -> YCbCr-ish (BT.601) for the saturation work."""
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cb = (b - y) * 0.564 + 0.0
    cr = (r - y) * 0.713 + 0.0
    return y, cb, cr


def from_ycbcr_like(y, cb, cr) -> np.ndarray:
    b = y + cb / 0.564
    r = y + cr / 0.713
    g = (y - 0.299 * r - 0.114 * b) / 0.587
    return np.stack([r, g, b], axis=-1)


def adjust_saturation(img: np.ndarray, sat: float) -> np.ndarray:
    """Saturation around luma (sat = 1 is neutral), on a float picture in [0,1]."""
    y, cb, cr = to_ycbcr_like(img)
    cb *= sat
    cr *= sat
    out = from_ycbcr_like(y, cb, cr)
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def saturate_pixels(pixels: np.ndarray, sat: float) -> np.ndarray:
    """adjust_saturation on an 8-bit or 16-bit picture (the same maths, in strips so a big picture needs no float copy of itself)."""
    if abs(sat - 1.0) <= 1e-4:
        return pixels
    top = 65535.0 if pixels.dtype == np.uint16 else 255.0
    out = np.empty_like(pixels)
    step = max(1, (1 << 21) // max(1, pixels.shape[1]))
    for y in range(0, pixels.shape[0], step):
        strip = pixels[y:y + step, :, :3].astype(np.float32) / np.float32(top)
        out[y:y + step, :, :3] = np.clip(np.rint(adjust_saturation(strip, sat) * np.float32(top)), 0, top).astype(pixels.dtype)
        if pixels.shape[2] > 3:
            out[y:y + step, :, 3:] = pixels[y:y + step, :, 3:]
    return out


def _interp_table(values: np.ndarray, table) -> np.ndarray:
    """render.render's LUT lookup: the table is indexed at value * (n - 1) with linear interpolation between its entries."""
    arr = np.asarray(table, dtype=np.float32)
    idx = np.clip(values, 0, 1) * (arr.size - 1)
    i0 = np.floor(idx).astype(int)
    i1 = np.minimum(i0 + 1, arr.size - 1)
    t = (idx - i0).astype(np.float32)
    return arr[i0] * (1 - t) + arr[i1] * t


def render_channel(positive: np.ndarray, settings: Settings, gain: float = 1.0) -> np.ndarray:
    """render.render for one channel of a density-normalized positive: white balance, then the tone curve (the real 20-point one, or the synthetic S-curve)."""
    out = positive
    if abs(gain - 1.0) > 1e-4:
        out = np.clip(out * np.float32(gain), 0.0, 1.0)
    if settings.real_curve:
        return np.clip(_interp_table(out, tone_curve_lut(variant=settings.variant)), 0.0, 1.0).astype(np.float32)
    return np.clip(noritsu_tone_curve(out, settings.contrast, settings.toe, settings.gamma), 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# calibrate.py (the per-stock profiles)
# ---------------------------------------------------------------------------

def profile_path(stock: str) -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "noritsu", f"{stock}_calib.npz")


_PROFILES: dict[str, dict | None] = {}


def load_calib(path: str) -> dict:
    z = np.load(path, allow_pickle=False)
    return {"lut": z["lut"], "dmin": z["dmin"], "dmax": z["dmax"]}


def user_folder() -> str:
    """Where profiles of your own are kept (the same .npz files noritsu-tool's calibrate writes): their ids start with "user:"."""
    from ..datadir import app_data_dir

    return os.path.join(app_data_dir(), "noritsu")


def stocks() -> dict[str, str]:
    """Every profile there is: id -> name. The three that come with noritsu-tool, then your own by name."""
    out = dict(STOCK_NAMES)
    try:
        for name in sorted(os.listdir(user_folder()), key=str.casefold):
            if name.lower().endswith(".npz"):
                out["user:" + name] = os.path.splitext(name)[0]
    except OSError:
        pass
    return out


def _valid_calib(z) -> bool:
    try:
        lut = np.asarray(z["lut"])
        return lut.ndim == 2 and lut.shape[0] == 3 and lut.shape[1] >= 2 and np.asarray(z["dmin"]).size == 3 and np.asarray(z["dmax"]).size == 3
    except (KeyError, ValueError):
        return False


def import_profile(path: str) -> str:
    """Copy a calibration .npz (noritsu-tool's calibrate writes one: lut, dmin, dmax) into your folder; its id. ValueError when it is not one."""
    import shutil

    try:
        with np.load(path, allow_pickle=False) as z:
            if not _valid_calib(z):
                raise ValueError("this is not a calibration profile (it needs lut, dmin and dmax)")
    except (OSError, ValueError, EOFError) as exc:
        raise ValueError(str(exc) or "this is not a calibration profile") from exc
    os.makedirs(user_folder(), exist_ok=True)
    name = os.path.basename(path)
    shutil.copyfile(path, os.path.join(user_folder(), name))
    _PROFILES.pop("user:" + name, None)
    return "user:" + name


def stock_profile(stock: str) -> dict | None:
    """A calibration profile ({lut: (3, n), dmin, dmax}), or None when there is none of that name."""
    if stock.startswith("user:"):
        path = os.path.join(user_folder(), os.path.basename(stock[5:]))
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            return None
        cached = _PROFILES.get(stock)
        if cached is None or cached.get("stamp") != stamp:
            try:
                with np.load(path, allow_pickle=False) as z:
                    cached = {**load_calib(path), "stamp": stamp} if _valid_calib(z) else {"lut": None, "stamp": stamp}
            except (OSError, ValueError, EOFError):
                cached = {"lut": None, "stamp": stamp}
            _PROFILES[stock] = cached
        return cached if cached["lut"] is not None else None
    if stock not in STOCKS:
        return None
    if stock not in _PROFILES:
        path = profile_path(stock)
        _PROFILES[stock] = load_calib(path) if os.path.exists(path) else None
    return _PROFILES[stock]


def fit_lut(src: np.ndarray, dst: np.ndarray, n: int = 1024) -> np.ndarray:
    """A per-channel mapping src -> dst from pixel correspondence: src binned into n bins, the mean dst of each (empty bins interpolated). (3, n)."""
    lut = np.zeros((3, n), dtype=np.float32)
    for c in range(3):
        s = np.clip(src[:, c], 0, 1)
        d = np.clip(dst[:, c], 0, 1)
        idx = np.clip((s * (n - 1)).astype(int), 0, n - 1)
        sums = np.zeros(n, dtype=np.float64)
        cnts = np.zeros(n, dtype=np.float64)
        np.add.at(sums, idx, d)
        np.add.at(cnts, idx, 1)
        valid = cnts > 0
        xs = np.where(valid, sums / np.maximum(cnts, 1), np.nan)
        good = np.where(valid)[0]
        if good.size == 0:
            lut[c] = np.linspace(0, 1, n)
            continue
        lut[c] = np.interp(np.arange(n), good, xs[good])
    return lut


def fit_profile(codes: np.ndarray, target: np.ndarray, settings: "Settings | None" = None, density_scale: float = DENSITY_SCALE) -> dict:
    """calibrate.py's calibrate: a profile from a negative's density codes (HxWx3) and the positive a lab made from the same frame (HxWx3, 8 or 16 bit, the same picture: it is resized to
    the scan if it differs in size). The scan's density is normalized to [Dmin, Dmax] as the conversion does, and each colour's table is the mean of the lab's values at each level of that
    (`fit_lut`). -> {lut: (3, 1024), dmin, dmax}, which `save_profile` keeps and `stock_profile` reads."""
    import cv2

    plan = plan_from_density(analysis_density(codes, None, density_scale), settings or Settings())
    k = max(1, int(np.ceil(np.sqrt(codes.shape[0] * codes.shape[1] / ANALYSIS_PIXELS))))
    positive = normalize(codes[::k, ::k, :3].astype(np.float32) / np.float32(density_scale), plan.dmin, plan.rng)
    top = 255.0 if target.dtype == np.uint8 else 65535.0
    aligned = cv2.resize(np.ascontiguousarray(target[..., :3]), (positive.shape[1], positive.shape[0]), interpolation=cv2.INTER_AREA).astype(np.float32) / np.float32(top)
    return {"lut": fit_lut(positive.reshape(-1, 3), aligned.reshape(-1, 3)), "dmin": plan.dmin, "dmax": plan.dmax}


def save_profile(name: str, profile: dict) -> str:
    """Keep a fitted profile in your folder as `name`.npz; its id."""
    safe = "".join(ch for ch in name.strip() if ch.isalnum() or ch in " -_.()") or "profile"
    os.makedirs(user_folder(), exist_ok=True)
    np.savez(os.path.join(user_folder(), safe + ".npz"), lut=np.asarray(profile["lut"], dtype=np.float32), dmin=np.asarray(profile["dmin"], dtype=np.float32), dmax=np.asarray(profile["dmax"], dtype=np.float32))
    _PROFILES.pop("user:" + safe + ".npz", None)
    return "user:" + safe + ".npz"


def fit_profile_from_files(scan_path: str, lab_path: str, name: str) -> str:
    """Fit and keep a profile from a negative scan on disk and the lab's positive of it (what calibrate.py's command line does): the id. An LS-600 dump is cropped and resized to the
    geometry of the machine's own TIFF first, as noritsu-tool does."""
    import cv2

    from ..open_image import ls600raw
    from ..open_image.logic import is_ls600, is_raw, source_encoding
    from ..open_image.processor import load_image_rgb
    from . import printengine

    scan = load_image_rgb(scan_path)
    if is_ls600(scan_path):
        scan = ls600raw.align_to_machine(scan)
    encoding = source_encoding(scan_path) or ("bt709" if is_raw(scan_path) else "srgb")
    codes = printengine.density_codes(scan, printengine.Settings(transfer=encoding, unmix_strength=0.0))
    lab = cv2.imread(lab_path, cv2.IMREAD_UNCHANGED | cv2.IMREAD_ANYDEPTH | cv2.IMREAD_ANYCOLOR)
    if lab is None:
        raise ValueError("the lab's picture could not be read")
    if lab.ndim == 2:
        lab = np.repeat(lab[:, :, None], 3, axis=2)
    return save_profile(name, fit_profile(codes, np.ascontiguousarray(lab[..., :3][..., ::-1])))


def apply_calib(positive: np.ndarray, calib: dict) -> np.ndarray:
    """A calibrated per-channel LUT applied to a density-normalized positive."""
    lut = calib["lut"]
    n = lut.shape[1]
    out = np.empty_like(positive)
    for c in range(3):
        x = np.clip(positive[..., c], 0, 1) * (n - 1)
        i0 = np.floor(x).astype(int)
        i1 = np.minimum(i0 + 1, n - 1)
        t = (x - i0).astype(np.float32)
        out[..., c] = lut[c][i0] * (1 - t) + lut[c][i1] * t
    return np.clip(out, 0, 1).astype(np.float32)


# ---------------------------------------------------------------------------
# autoparam.py
# ---------------------------------------------------------------------------

def estimate_neg_density(density: np.ndarray, dmin_pct: float = 0.5, dmax_pct: float = 99.5) -> dict:
    """A thin / normal / dense reading of a negative's density: the mean per-channel range (Dmax - Dmin), its classification, how thin it feels (0 = thick, 1 = very thin) and the spread."""
    border_dmin = estimate_dmin_border(density, frac=0.03)
    if border_dmin is not None:
        dmin = border_dmin
    else:
        mask = film_valid_mask(density)
        dmin = estimate_dmin(density, dmin_pct, mask if mask.any() else None)
    mask_dmax = film_valid_mask(density, black_th=0.0005)
    dmax = estimate_dmax(density, dmax_pct, mask_dmax if mask_dmax.any() else None)

    rng = dmax - dmin
    mean_range = float(rng.mean())
    if mean_range < THIN_DMAX:
        classification = "thin"
    elif mean_range > DENSE_DMIN:
        classification = "dense"
    else:
        classification = "normal"
    thin_score = np.clip(1.0 - (mean_range - 0.4) / 1.6, 0.0, 1.0)

    flat = density.reshape(-1, 3)
    normed = np.clip((flat - dmin[None, :]) / np.maximum(rng[None, :], 0.05), 0.0, 1.0)
    mean_spread = float(np.mean([float(normed[:, c].std()) for c in range(3)]))
    return {"density_range": mean_range, "dmin": dmin, "dmax": dmax, "classification": classification, "thin_score": float(thin_score),
            "details": {"per_channel_ranges": [float(rng[c]) for c in range(3)], "histogram_spread": mean_spread, "border_dmin_available": border_dmin is not None}}


def suggest_params(estimate: dict, preferred_look="balanced") -> dict:
    """The settings suggested for a negative's density reading and a preferred look (a LOOK_PRESETS key, or a dict of contrast, sat, toe, gamma_offset and dmax_pct_offset)."""
    classification = estimate["classification"]
    thin_score = estimate["thin_score"]
    preset = LOOK_PRESETS.get(preferred_look, LOOK_PRESETS["balanced"]) if isinstance(preferred_look, str) else preferred_look
    cb = CLASS_BASE[classification]

    gamma = cb["gamma"] + preset["gamma_offset"]
    dmax_pct = cb["dmax_pct"] + preset["dmax_pct_offset"]
    contrast = preset["contrast"]
    sat = preset["sat"]
    toe = preset["toe"]

    if classification == "thin":
        gamma = 0.70 + (1.0 - thin_score) * 0.20      # 0.70 (very thin) to 0.90 (barely thin)
        if thin_score > 0.7:
            contrast *= 0.95
    elif classification == "dense":
        dense_score = 1.0 - thin_score
        gamma = 1.0 + dense_score * 0.15
        sat *= 1.0 + dense_score * 0.1

    gamma = round(gamma, 2)
    dmax_pct = round(dmax_pct, 1)
    contrast = round(contrast, 3)
    sat = round(sat, 2)

    if classification == "thin":
        confidence = max(0.6, 1.0 - thin_score * 0.4)
    elif classification == "dense":
        confidence = max(0.65, 1.0 - (1.0 - thin_score) * 0.3)
    else:
        confidence = 0.85
    return {"gamma": gamma, "dmax_pct": dmax_pct, "contrast": contrast, "saturation": sat, "toe": toe, "classification": classification,
            "look": preset.get("label", preferred_look) if isinstance(preferred_look, str) else "custom", "description": cb["description"], "confidence": round(confidence, 3)}


# ---------------------------------------------------------------------------
# pipeline.py, on a scan held as density codes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Plan:
    dmin: np.ndarray
    dmax: np.ndarray
    rng: np.ndarray
    gains: tuple[float, float, float]
    settings: Settings
    film: object = None      # a film curve (features/negative/filmcurve) that straightens the scan's density before it is normalized: dmin, dmax and rng are in its units


def analysis_density(codes: np.ndarray, rect=None, density_scale: float = DENSITY_SCALE) -> np.ndarray:
    """The density (float32, H x W x 3) the statistics are read from: the drawn region, else the whole frame cropped to the film (pipeline's crop). A picture bigger than ANALYSIS_PIXELS is
    read at every k-th pixel of every k-th row first."""
    h, w = codes.shape[:2]
    if rect is not None:
        x1, x2 = sorted((max(0, min(int(rect[0]), w)), max(0, min(int(rect[2]), w))))
        y1, y2 = sorted((max(0, min(int(rect[1]), h)), max(0, min(int(rect[3]), h))))
        if x2 - x1 >= 2 and y2 - y1 >= 2:
            codes, rect = codes[y1:y2, x1:x2], True
        else:
            rect = None
    k = max(1, int(np.ceil(np.sqrt(codes.shape[0] * codes.shape[1] / ANALYSIS_PIXELS))))
    sub = codes[::k, ::k, :3]
    density = sub.astype(np.float32) / np.float32(density_scale)
    if rect is None:
        density, _bbox = crop_to_film(density)
    return density


def plan_from_density(density: np.ndarray, settings: Settings, border: bool = True, film=None) -> Plan:
    """invert_negative's Dmin / Dmax and process_negative's automatic white balance for a (cropped) density picture. `border` False leaves the rebate out (a drawn region has none).
    `film` is a film curve (features/negative/filmcurve): the scan's density is read as usual, then Dmin, Dmax and the white balance are worked out on the straightened density (a
    percentile keeps its place through a rising curve, so the two readings are the same pixels)."""
    s = settings.effective()
    mask_dmin = film_valid_mask(density, black_th=0.0)      # (black bars don't affect the minimum)
    mask_dmax = film_valid_mask(density, black_th=0.0005)   # (only true scan black is left out, not dense film: the densest negative pixels are the scene's brightest highlights)
    dmin = estimate_dmin_border(density) if (s.use_border and border) else None
    if dmin is None:
        dmin = estimate_dmin(density, s.dmin_pct, mask_dmin if mask_dmin.any() else None)
    dmax = estimate_dmax(density, s.dmax_pct, mask_dmax if mask_dmax.any() else None)
    dmin = np.asarray(dmin, dtype=np.float32)
    dmax = np.asarray(dmax, dtype=np.float32)
    if film is not None:
        dmin, dmax = film.values(dmin), film.values(dmax)
        density = film.remap(density)
    rng = dmax - dmin
    rng = np.where(rng < 0.05, 0.05, rng).astype(np.float32)

    gains = (1.0, 1.0, 1.0)
    calibrated = bool(s.stock) and stock_profile(s.stock) is not None
    if s.auto_wb and not calibrated:
        positive = normalize(density, dmin, rng) if film is None else np.stack([film.print_positive(density[..., c], dmin[c], dmax[c], c) for c in range(3)], axis=-1)
        mean = np.clip(positive.reshape(-1, 3).mean(axis=0), 1e-4, None)
        target = mean.mean()
        gains = tuple(float(target / mean[c]) for c in range(3))
    return Plan(dmin, dmax, rng, gains, settings, film)


def plan_from_codes(codes: np.ndarray, rect=None, settings: Settings | None = None, density_scale: float = DENSITY_SCALE, film=None) -> Plan:
    settings = settings or Settings()
    return plan_from_density(analysis_density(codes, rect, density_scale), settings, border=rect is None, film=film)


def build_lut(plan: Plan, density_scale: float = DENSITY_SCALE) -> np.ndarray:
    """(3, 65536) display values, 0-255 (float), indexed by density code: normalize to [Dmin, Dmax], white balance and the tone curve (or the stock's profile) of each channel. The
    saturation is not here (it mixes the channels): see saturate_pixels."""
    s = plan.settings.effective()
    density = (np.arange(65536, dtype=np.float32) / np.float32(density_scale))
    profile = stock_profile(s.stock) if s.stock else None
    lut = np.empty((3, 65536), dtype=np.float32)
    for c in range(3):
        if plan.film is not None:
            positive = plan.film.print_positive(plan.film(density, c), plan.dmin[c], plan.dmax[c], c)
        else:
            positive = np.clip((density - plan.dmin[c]) / plan.rng[c], 0.0, 1.0).astype(np.float32)
        if profile is not None:
            lut[c] = np.clip(_interp_table(positive, profile["lut"][c]), 0.0, 1.0) * 255.0      # (apply_calib's lookup, one channel)
        else:
            lut[c] = render_channel(positive, s, plan.gains[c]) * 255.0
    return lut
