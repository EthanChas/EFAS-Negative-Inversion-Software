"""Color Balance RGB, ported from darktable's module of that name (src/iop/colorbalancergb.c and the colour-space helpers it uses, GPL-3.0) - numpy only, no Qt.

darktable's colour grading module, by Aurelien Pierre. The picture is taken to Filmlight Yrg (a luminance and a chromaticity pair, made from the CIE 2006 cone responses), where:
  * the hue is rotated, the chroma is raised or lowered (globally, by tone range, and "vibrance" for the colours that have little), and a colour that falls outside the gamut is brought back
    along its own hue at the same luminance;
  * the four-way grading is done in the Filmlight RGB of those cones: a global offset, "lift" (a slope in the shadows), "gain" (a slope in the highlights) and "power" (an exponent in the
    midtones), each with a hue and a chroma of its own, the shadows / midtones / highlights being three overlapping masks of the luminance;
  * the luminance has a power and a contrast about a grey fulcrum;
and last, perceptual saturation and brilliance, in either the JzAzBz space (the 2021 formula) or darktable's own UCS (2022, the default), each with its own gamut map.

The 8-bit sRGB picture is made linear (and taken as Rec. 709 primaries with a D65 white, which is what darktable's pipeline has after its own D50 to D65 adaptation of an sRGB profile), worked in
float and brought back clipped to the sRGB gamut. Every slider is darktable's, with the same name, range and meaning.
"""
import math

import numpy as np

from ..lut.strips import _POOL, _WORKERS

# ---------------------------------------------------------------------------------------------------------------------------------------------- the parameters
SLICES = ("shadows", "midtones", "highlights", "global")
KEYS = tuple(
    [f"cbr_{r}_{c}" for r in SLICES for c in ("Y", "C", "H")]
    + ["cbr_shadows_weight", "cbr_white_fulcrum", "cbr_highlights_weight"]
    + [f"cbr_chroma_{r}" for r in ("shadows", "highlights", "global", "midtones")]
    + [f"cbr_saturation_{r}" for r in ("global", "highlights", "midtones", "shadows")]
    + ["cbr_hue_angle"]
    + [f"cbr_brilliance_{r}" for r in ("global", "highlights", "midtones", "shadows")]
    + ["cbr_mask_grey_fulcrum", "cbr_vibrance", "cbr_grey_fulcrum", "cbr_contrast", "cbr_formula"]
)
DEFAULTS = {k: 0.0 for k in KEYS}
DEFAULTS.update({"cbr_shadows_weight": 1.0, "cbr_highlights_weight": 1.0, "cbr_mask_grey_fulcrum": 0.1845, "cbr_grey_fulcrum": 0.1845, "cbr_formula": 1.0})
RANGES = {k: (-1.0, 1.0) for k in KEYS}
RANGES.update({f"cbr_{r}_{c}": ((0.0, 360.0) if c == "H" else (0.0, 1.0) if c == "C" else (-1.0, 1.0)) for r in SLICES for c in ("Y", "C", "H")})
RANGES.update({"cbr_shadows_weight": (0.0, 3.0), "cbr_highlights_weight": (0.0, 3.0), "cbr_white_fulcrum": (-16.0, 16.0), "cbr_hue_angle": (-180.0, 180.0),
               "cbr_mask_grey_fulcrum": (0.0, 1.0), "cbr_grey_fulcrum": (0.0, 1.0), "cbr_formula": (0.0, 1.0)})
FORMULA_JZAZBZ, FORMULA_DTUCS = 0, 1
FORMULA_LABELS = {FORMULA_JZAZBZ: "JzAzBz (2021)", FORMULA_DTUCS: "darktable UCS (2022)"}
# the sliders that change the picture (the others only say where the shadows / midtones / highlights are)
_EFFECT = tuple(k for k in KEYS if k not in ("cbr_shadows_weight", "cbr_highlights_weight", "cbr_mask_grey_fulcrum", "cbr_grey_fulcrum", "cbr_formula"))

# darktable's own presets
PRESETS: dict[str, dict] = {
    "basic colorfulness | legacy": {"cbr_formula": 0.0, "cbr_chroma_global": 0.2, "cbr_saturation_shadows": 0.1, "cbr_saturation_midtones": 0.05, "cbr_saturation_highlights": -0.05},
    "basic colorfulness | natural skin": {"cbr_formula": 1.0, "cbr_saturation_global": 0.2, "cbr_saturation_shadows": 0.30, "cbr_saturation_midtones": 0.0, "cbr_saturation_highlights": -0.5},
    "basic colorfulness | vibrant colors": {"cbr_formula": 1.0, "cbr_saturation_global": 0.2, "cbr_saturation_shadows": 0.5, "cbr_saturation_midtones": 0.0, "cbr_saturation_highlights": -0.25},
    "basic colorfulness | standard": {"cbr_formula": 1.0, "cbr_saturation_global": 0.2, "cbr_saturation_shadows": 0.25, "cbr_saturation_midtones": 0.0, "cbr_saturation_highlights": -0.25},
}

LIVE = "colorbalancergb"


def is_neutral(values: dict | None) -> bool:
    v = values or {}
    return all(abs(float(v.get(k, 0.0))) <= 1e-9 for k in _EFFECT)


# ---------------------------------------------------------------------------------------------------------------------------------------------- colour spaces (darktable's constants)
_SRGB_TO_XYZ = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]], dtype=np.float64)
_XYZ_TO_SRGB = np.array([[3.2404542, -1.5371385, -0.4985314], [-0.9692660, 1.8760108, 0.0415560], [0.0556434, -0.2040259, 1.0572252]], dtype=np.float64)
_XYZ_TO_LMS = np.array([[0.257085, 0.859943, -0.031061], [-0.394427, 1.175800, 0.106423], [0.064856, -0.076250, 0.559067]], dtype=np.float64)
_LMS_TO_XYZ = np.array([[1.80794659, -1.29971660, 0.34785879], [0.61783960, 0.39595453, -0.04104687], [-0.12546960, 0.20478038, 1.74274183]], dtype=np.float64)
_GRADING_TO_LMS = np.array([[0.95, 0.38, 0.0], [0.05, 0.62, 0.03], [0.0, 0.0, 0.97]], dtype=np.float64)      # Filmlight RGB -> LMS (the printed matrix is the transpose)
_LMS_TO_GRADING = np.array([[1.08771930, -0.66666667, 0.02061856], [-0.0877193, 1.66666667, -0.05154639], [0.0, 0.0, 1.03092784]], dtype=np.float64)
_RGB_TO_LMS = _XYZ_TO_LMS @ _SRGB_TO_XYZ
_D65_R, _D65_G = 0.21902143, 0.54371398          # the r, g of the D65 white in normalised Filmlight Yrg
_Y_LMS = (0.68990272, 0.34832189)
_ANGLE_SHIFT = -30.0
_GREY_MASK_EXPONENT = 0.4101205819200422
LUT_ELEM = 512
_D65_XY = (0.3127, 0.3290)

_f32 = np.float32


def _tables():
    from ..diffuse import logic as _d

    return _d._tables()


def _to_linear(pixels: np.ndarray) -> np.ndarray:
    return _tables()[0][pixels]


def _from_linear(linear: np.ndarray) -> np.ndarray:
    from ..diffuse import logic as _d

    return _d._from_linear(linear)


# ---------------------------------------------------------------------------------------------------------------------------------------------- darktable UCS 2022
_UCS_L_RANGE = 2.098883786377
_UCS_L_UPPER = 2.09885


def _y_to_ucs_l(Y):
    y_hat = np.power(np.maximum(Y, 0.0), 0.631651345306265)
    return _UCS_L_RANGE * y_hat / (y_hat + 1.12426773749357)


def _ucs_l_to_y(L):
    return np.power(1.12426773749357 * L / (_UCS_L_RANGE - L), 1.5831518565279648)


def _xy_to_ucs_uv(x, y):
    """xyY_to_dt_UCS_UV with Y = 1: the colourfulness plane (U*', V*')."""
    d0 = -0.783941002840055 * x + 0.277512987809202 * y + 0.153836578598858
    d1 = 0.745273540913283 * x - 0.205375866083878 * y - 0.165478376301988
    d2 = 0.318707282433486 * x + 2.16743692732158 * y + 0.291320554395942
    tiny = np.finfo(np.float32).tiny
    div = np.where(d2 >= 0.0, np.maximum(tiny, d2), np.minimum(-tiny, d2))
    u, v = d0 / div, d1 / div
    us = 1.39656225667 * u / (np.abs(u) + 1.49217352929)
    vs = 1.4513954287 * v / (np.abs(v) + 1.52488637914)
    return -1.124983854323892 * us - 0.980483721769325 * vs, 1.86323315098672 * us + 1.971853092390862 * vs


def _soft_clip(x, soft, hard):
    norm = np.maximum(hard - soft, 1e-12)
    return np.where(x > soft, soft + (1.0 - np.exp(-(x - soft) / norm)) * norm, x)


def _delta_h(h1, h2):
    diff = h1 - h2
    diff = diff + np.where(diff < -math.pi, 2 * math.pi, 0.0)
    diff = diff - np.where(diff > math.pi, 2 * math.pi, 0.0)
    return diff


def _xyz_to_xy(xyz):
    xyz = np.maximum(xyz, 0.0)
    s = xyz.sum(axis=-1)
    ok = s > 0
    safe = np.where(ok, s, 1.0)
    return np.where(ok, xyz[..., 0] / safe, _D65_XY[0]), np.where(ok, xyz[..., 1] / safe, _D65_XY[1])


def _build_ucs_gamut_lut() -> np.ndarray:
    """dt_UCS_22_build_gamut_LUT: the squared colourfulness M^2 of the sRGB gamut boundary at each hue of darktable UCS."""
    red, green, blue = (_xyz_to_xy(_SRGB_TO_XYZ[:, i]) for i in range(3))
    x0, y0 = _D65_XY
    h_red, h_green, h_blue = (math.atan2(p[1] - y0, p[0] - x0) for p in (red, green, blue))
    n = 50 * LUT_ELEM
    angle = -math.pi + np.arange(n, dtype=np.float64) / n * 2 * math.pi
    tan = np.tan(angle)
    t1 = _delta_h(angle, h_blue) / _delta_h(h_red, h_blue)
    t2 = _delta_h(angle, h_red) / _delta_h(h_green, h_red)
    t3 = _delta_h(angle, h_green) / _delta_h(h_blue, h_green)
    x_t = np.zeros(n)
    y_t = np.zeros(n)
    taken = np.zeros(n, dtype=bool)
    for t, a, b in ((t1, blue, red), (t2, red, green), (t3, green, blue)):
        sel = (t >= 0) & (t <= 1) & ~taken
        with np.errstate(all="ignore"):
            k = (y0 - a[1] + tan * (a[0] - x0)) / (b[1] - a[1] + tan * (a[0] - b[0]))
        x_t = np.where(sel, a[0] + k * (b[0] - a[0]), x_t)
        y_t = np.where(sel, a[1] + k * (b[1] - a[1]), y_t)
        taken |= sel
    u, v = _xy_to_ucs_uv(x_t, y_t)
    hue = np.arctan2(v, u)
    index = np.rint((LUT_ELEM - 1) * (hue + math.pi) / (2 * math.pi)).astype(int)
    index = np.where(index < 0, index + LUT_ELEM, index)
    index = np.where(index >= LUT_ELEM, index - LUT_ELEM, index)
    lut = np.zeros(LUT_ELEM)
    count = np.zeros(LUT_ELEM)
    np.add.at(lut, index, u * u + v * v)
    np.add.at(count, index, 1.0)
    return (lut / np.maximum(1.0, count)).astype(np.float32)


# ---------------------------------------------------------------------------------------------------------------------------------------------- JzAzBz
_JZ_B, _JZ_G = 1.15, 0.66
_JZ_C1, _JZ_C2, _JZ_C3 = 0.8359375, 18.8515625, 18.6875
_JZ_N, _JZ_P = 0.159301758, 134.034375
_JZ_D, _JZ_D0 = -0.56, 1.6295499532821566e-11
_JZ_M = np.array([[0.41478972, 0.57999900, 0.01464800], [-0.2015100, 1.1206490, 0.0531008], [-0.0166008, 0.2648000, 0.6684799]], dtype=np.float64)
_JZ_A = np.array([[0.5, 0.5, 0.0], [3.524000, -4.066708, 0.542708], [0.199076, 1.096799, -1.295875]], dtype=np.float64)
_JZ_AI = np.array([[1.0, 0.1386050432715393, 0.0580473161561189], [1.0, -0.1386050432715393, -0.0580473161561189], [1.0, -0.0960192420263190, -0.8118918960560390]], dtype=np.float64)   # rows: L', M', S'
_JZ_MI = np.array([[1.9242264357876067, -1.0047923125953657, 0.0376514040306180], [0.3503167620949991, 0.7264811939316552, -0.0653844229480850],
                   [-0.0909828109828475, -0.3127282905230739, 1.5227665613052603]], dtype=np.float64)


def _xyz_to_jzazbz(X, Y, Z):
    Xp = _JZ_B * X - (_JZ_B - 1.0) * Z
    Yp = _JZ_G * Y - (_JZ_G - 1.0) * X
    lms = np.stack([Xp, Yp, Z], axis=-1) @ _JZ_M.T * 1e-4
    t = np.power(np.maximum(lms, 0.0), _JZ_N)
    q = np.power((_JZ_C1 + _JZ_C2 * t) / (1.0 + _JZ_C3 * t), _JZ_P)
    iaz = q @ _JZ_A.T
    iz = iaz[..., 0]
    jz = np.maximum(((1.0 + _JZ_D) * iz) / (1.0 + _JZ_D * iz) - _JZ_D0, 0.0)
    return jz, iaz[..., 1], iaz[..., 2]


def _jzazbz_to_xyz(Jz, az, bz):
    iz = Jz + _JZ_D0
    iz = np.maximum(iz / (1.0 + _JZ_D - _JZ_D * iz), 0.0)
    lms = np.maximum(np.stack([iz, az, bz], axis=-1) @ _JZ_AI.T, 0.0)
    lms = np.power(lms, 1.0 / _JZ_P)
    lms = (_JZ_C1 - lms) / (_JZ_C3 * lms - _JZ_C2)
    lms = np.maximum(lms, 0.0)
    lms = 10000.0 * np.power(lms, 1.0 / _JZ_N)
    xyz = lms @ _JZ_MI.T
    X = (xyz[..., 0] + (_JZ_B - 1.0) * xyz[..., 2]) / _JZ_B
    Y = (xyz[..., 1] + (_JZ_G - 1.0) * X) / _JZ_G
    return X, Y, xyz[..., 2]


def _build_jzazbz_gamut_lut() -> np.ndarray:
    steps = 92
    g = np.linspace(0.0, 1.0, steps)
    rgb = np.stack(np.meshgrid(g, g, g, indexing="ij"), axis=-1).reshape(-1, 3)
    xyz = rgb @ _SRGB_TO_XYZ.T
    jz, az, bz = _xyz_to_jzazbz(xyz[:, 0], xyz[:, 1], xyz[:, 2])
    chroma = np.hypot(az, bz)
    saturation = np.where(jz > 0, chroma / np.maximum(jz, 1e-30), 0.0)
    hue = np.arctan2(bz, az)
    index = np.rint((LUT_ELEM - 1) * (hue + math.pi) / (2 * math.pi)).astype(int) % LUT_ELEM
    sampler = np.zeros(LUT_ELEM)
    np.maximum.at(sampler, index, saturation)
    # a 5-tap box average round the hue circle (darktable leaves the bounds as it wraps them)
    lut = sum(np.roll(sampler, k) for k in (-2, -1, 0, 1, 2)) / 5.0
    return lut.astype(np.float32)


_LUTS: dict[int, np.ndarray] = {}


def _gamut_lut(formula: int) -> np.ndarray:
    if formula not in _LUTS:
        _LUTS[formula] = _build_jzazbz_gamut_lut() if formula == FORMULA_JZAZBZ else _build_ucs_gamut_lut()
    return _LUTS[formula]


def _lookup_gamut(lut: np.ndarray, hue):
    x = LUT_ELEM * (hue + math.pi) / (2 * math.pi)
    lo = np.floor(x)
    i0 = lo.astype(np.int64) & (LUT_ELEM - 1)
    i1 = np.ceil(x).astype(np.int64) & (LUT_ELEM - 1)
    y0 = lut[i0]
    return y0 + np.where(i0 != i1, (x - lo) * (lut[i1] - y0), 0.0)


# ---------------------------------------------------------------------------------------------------------------------------------------------- the module
def _yrg_from_lms(lms):
    """Filmlight Yrg of a cone response (luminance, then the normalised r and g)."""
    L, M, S = lms[..., 0], lms[..., 1], lms[..., 2]
    Y = _Y_LMS[0] * L + _Y_LMS[1] * M
    a = L + M + S
    ok = a != 0
    safe = np.where(ok, a, 1.0)
    n = np.stack([np.where(ok, L / safe, 0.0), np.where(ok, M / safe, 0.0), np.where(ok, S / safe, 0.0)], axis=-1)
    grading = n @ _LMS_TO_GRADING.astype(lms.dtype).T
    return Y, grading[..., 0], grading[..., 1]


def _lms_from_yrg(Y, r, g):
    b = 1.0 - r - g
    lms_n = np.stack([r, g, b], axis=-1)
    lms_n = lms_n @ _GRADING_TO_LMS.astype(lms_n.dtype).T
    denom = _Y_LMS[0] * lms_n[..., 0] + _Y_LMS[1] * lms_n[..., 1]
    ok = denom != 0
    scale = np.where(ok, Y / np.where(ok, denom, 1.0), 0.0)
    return lms_n * scale[..., None]


def _grading_rgb_of_ych(Y, c, h_rad):
    """Ych_to_gradingRGB for a scalar (Y, chroma, hue in radians)."""
    r = c * math.cos(h_rad) + _D65_R
    g = c * math.sin(h_rad) + _D65_G
    lms = _lms_from_yrg(np.float64(Y), np.float64(r), np.float64(g))
    return _LMS_TO_GRADING @ lms


def _commit(p: dict) -> dict:
    """The numbers the pixel loop needs (commit_params)."""
    def conv(h):
        return math.radians(h + _ANGLE_SHIFT)

    white = _grading_rgb_of_ych(1.0, 0.0, 0.0)
    d: dict = {}
    d["vibrance"] = float(p["cbr_vibrance"])
    d["contrast"] = 1.0 + float(p["cbr_contrast"])
    d["grey_fulcrum"] = float(p["cbr_grey_fulcrum"])
    d["chroma_global"] = float(p["cbr_chroma_global"])
    d["chroma"] = tuple(float(p[k]) for k in ("cbr_chroma_shadows", "cbr_chroma_midtones", "cbr_chroma_highlights"))
    d["saturation_global"] = float(p["cbr_saturation_global"])
    d["saturation"] = tuple(float(p[k]) for k in ("cbr_saturation_shadows", "cbr_saturation_midtones", "cbr_saturation_highlights"))
    d["brilliance_global"] = float(p["cbr_brilliance_global"])
    d["brilliance"] = tuple(float(p[k]) for k in ("cbr_brilliance_shadows", "cbr_brilliance_midtones", "cbr_brilliance_highlights"))
    d["hue_angle"] = math.radians(float(p["cbr_hue_angle"]))
    glob = _grading_rgb_of_ych(1.0, float(p["cbr_global_C"]), conv(float(p["cbr_global_H"])))
    d["global"] = (glob - white) + white * float(p["cbr_global_Y"])
    sh = _grading_rgb_of_ych(1.0, float(p["cbr_shadows_C"]), conv(float(p["cbr_shadows_H"])))
    d["shadows"] = 1.0 + (sh - white) + float(p["cbr_shadows_Y"])
    d["shadows_weight"] = 2.0 + float(p["cbr_shadows_weight"]) * 2.0
    hi = _grading_rgb_of_ych(1.0, float(p["cbr_highlights_C"]), conv(float(p["cbr_highlights_H"])))
    d["highlights"] = 1.0 + (hi - white) + float(p["cbr_highlights_Y"])
    d["highlights_weight"] = 2.0 + float(p["cbr_highlights_weight"]) * 2.0
    mid = _grading_rgb_of_ych(1.0, float(p["cbr_midtones_C"]), conv(float(p["cbr_midtones_H"])))
    d["midtones"] = 1.0 / np.maximum(1.0 + (mid - white), 0.01)       # (darktable divides by what may be zero and gets an infinite exponent; held to a very large one here)
    d["midtones_Y"] = 1.0 / max(1.0 + float(p["cbr_midtones_Y"]), 0.01)
    d["white_fulcrum"] = 2.0 ** float(p["cbr_white_fulcrum"])
    d["midtones_weight"] = d["shadows_weight"] ** 2 * d["highlights_weight"] ** 2 / (d["shadows_weight"] ** 2 + d["highlights_weight"] ** 2)
    d["mask_grey_fulcrum"] = max(float(p["cbr_mask_grey_fulcrum"]), 1e-6) ** _GREY_MASK_EXPONENT
    d["formula"] = FORMULA_DTUCS if float(p["cbr_formula"]) >= 0.5 else FORMULA_JZAZBZ
    return d


def hue_swatch(hue_degrees: float, chroma: float = 0.1, luminance: float = 0.4) -> tuple[int, int, int]:
    """The sRGB colour of a hue of the grading sliders (red at 0 degrees, as in the module's hue sliders), at a given chroma and luminance - to paint a hue slider's groove."""
    h = math.radians(hue_degrees + _ANGLE_SHIFT)
    r = chroma * math.cos(h) + _D65_R
    g = chroma * math.sin(h) + _D65_G
    xyz = _lms_from_yrg(np.float64(luminance), np.float64(r), np.float64(g)) @ _LMS_TO_XYZ.T
    lin = np.clip(xyz @ _XYZ_TO_SRGB.T, 0.0, 1.0)
    srgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)
    return tuple(int(round(float(v) * 255)) for v in np.clip(srgb, 0.0, 1.0))


def _block(linear: np.ndarray, d: dict, lut: np.ndarray) -> np.ndarray:
    """process(): a block of linear sRGB (n, w, 3) through the grading, back to linear sRGB. In single precision, except for the JzAzBz formula whose exponents of 134 need double."""
    dt = np.float64 if d["formula"] == FORMULA_JZAZBZ else np.float32
    rgb = np.maximum(linear, 0.0).astype(dt)
    lms = rgb @ _RGB_TO_LMS.astype(dt).T
    Y, r, g = _yrg_from_lms(lms)
    Y = np.maximum(Y, 0.0)
    rr, gg = r - _D65_R, g - _D65_G
    c = np.hypot(rr, gg)
    nz = c != 0
    cos_h = np.where(nz, rr / np.where(nz, c, 1.0), 1.0)
    sin_h = np.where(nz, gg / np.where(nz, c, 1.0), 0.0)

    # the three overlapping masks of the luminance
    x_off = np.power(Y, _GREY_MASK_EXPONENT) - d["mask_grey_fulcrum"]
    x_norm = x_off / d["mask_grey_fulcrum"]
    alpha = 1.0 / (1.0 + np.exp(np.clip(x_norm * d["shadows_weight"], -80, 80)))
    beta = 1.0 / (1.0 + np.exp(np.clip(-x_norm * d["highlights_weight"], -80, 80)))
    gamma = np.exp(-(x_off ** 2) * d["midtones_weight"] / 4.0) * (1.0 - alpha) ** 2 * (1.0 - beta) ** 2 * 8.0
    op = (alpha, gamma, beta)

    # hue rotation, then chroma
    ca, sa = math.cos(d["hue_angle"]), math.sin(d["hue_angle"])
    cos_h, sin_h = ca * cos_h - sa * sin_h, sa * cos_h + ca * sin_h
    boost = d["chroma_global"] + op[0] * d["chroma"][0] + op[1] * d["chroma"][1] + op[2] * d["chroma"][2]
    vib = d["vibrance"]
    vibrance = vib * (1.0 - np.power(c, abs(vib))) if vib != 0.0 else 0.0
    c = c * np.maximum(1.0 + boost + vibrance, 0.0)
    # clip the chroma at constant hue and luminance if it left Yrg
    r2 = c * cos_h + _D65_R
    g2 = c * sin_h + _D65_G
    max_c = c.copy()
    with np.errstate(all="ignore"):
        max_c = np.where(r2 < 0, np.minimum(-_D65_R / cos_h, max_c), max_c)
        max_c = np.where(g2 < 0, np.minimum(-_D65_G / sin_h, max_c), max_c)
        max_c = np.where(r2 + g2 > 1.0, np.minimum((1.0 - _D65_R - _D65_G) / (cos_h + sin_h), max_c), max_c)
    c = np.nan_to_num(max_c, nan=0.0, posinf=0.0, neginf=0.0)
    r2 = c * cos_h + _D65_R
    g2 = c * sin_h + _D65_G
    lms = _lms_from_yrg(Y, r2, g2)
    grading = lms @ _LMS_TO_GRADING.astype(dt).T

    # the four-way grading, in Filmlight RGB
    grading = grading + d["global"].astype(dt)
    slope = (1.0 - op[2])[..., None] * ((1.0 - op[0])[..., None] + op[0][..., None] * d["shadows"].astype(dt)) + op[2][..., None] * d["highlights"].astype(dt)
    grading = grading * slope
    sign = np.where(grading < 0, -1.0, 1.0)
    with np.errstate(all="ignore"):
        grading = np.power(np.abs(grading) / d["white_fulcrum"], d["midtones"].astype(dt)) * sign * d["white_fulcrum"]
    lms = grading @ _GRADING_TO_LMS.astype(dt).T
    Y, r, g = _yrg_from_lms(lms)
    with np.errstate(all="ignore"):
        Y = np.power(np.maximum(Y / d["white_fulcrum"], 0.0), d["midtones_Y"]) * d["white_fulcrum"]
        Y = d["grey_fulcrum"] * np.power(Y / d["grey_fulcrum"], d["contrast"])
    xyz = np.nan_to_num(_lms_from_yrg(Y, r, g) @ _LMS_TO_XYZ.astype(dt).T, nan=0.0, posinf=1e6, neginf=0.0)      # (an extreme setting can overflow: a number is made of it, not a hole)

    if d["formula"] == FORMULA_JZAZBZ:
        xyz = _saturation_jzazbz(xyz, d, op, lut)
    else:
        xyz = _saturation_ucs(xyz, d, op, lut)
    out = xyz @ _XYZ_TO_SRGB.astype(xyz.dtype).T
    return np.maximum(np.nan_to_num(out, nan=0.0, posinf=1.0, neginf=0.0), 0.0).astype(np.float32)


def _saturation_jzazbz(xyz, d, op, lut):
    X, Y, Z = xyz[..., 0], xyz[..., 1], xyz[..., 2]
    Jz, az, bz = _xyz_to_jzazbz(X, Y, Z)
    J, C = Jz, np.hypot(az, bz)
    h = np.arctan2(bz, az)
    T = np.arctan2(C, J)
    sin_T, cos_T = np.sin(T), np.cos(T)
    boost_s = 1.0 + d["brilliance_global"] + op[0] * d["brilliance"][0] + op[1] * d["brilliance"][1] + op[2] * d["brilliance"][2]
    boost_o = d["saturation_global"] + op[0] * d["saturation"][0] + op[1] * d["saturation"][1] + op[2] * d["saturation"][2]
    S = J * cos_T + C * sin_T
    O = S * np.minimum(np.maximum(T * boost_o, -T), math.pi / 2 - T)
    S = np.maximum(S * boost_s, 0.0)
    J2 = np.maximum(S * cos_T - O * sin_T, 0.0)
    C2 = np.maximum(S * sin_T + O * cos_T, 0.0)
    out_max_sat = _lookup_gamut(lut, h)
    with np.errstate(all="ignore"):
        sat = np.where(J2 > 0, _soft_clip(C2 / np.where(J2 > 0, J2, 1.0), 0.8 * out_max_sat, out_max_sat), out_max_sat)
        max_c_at_sat = J2 * sat
        max_j_at_sat = np.where(sat > 0, C2 / np.where(sat > 0, sat, 1.0), J2)
    J2 = (J2 + max_j_at_sat) / 2.0
    C2 = (C2 + max_c_at_sat) / 2.0
    # clip the chroma at constant hue and lightness so no cone response goes negative
    cos_H, sin_H = np.cos(h), np.sin(h)
    iz = np.maximum((J2 + _JZ_D0) / (1.0 + _JZ_D - _JZ_D * (J2 + _JZ_D0)), 0.0)
    lms = np.stack([iz, C2 * cos_H, C2 * sin_H], axis=-1) @ _JZ_AI.T
    max_C = C2.copy()
    with np.errstate(all="ignore"):
        for k in range(3):
            slope = _JZ_AI[k, 1] * cos_H + _JZ_AI[k, 2] * sin_H
            max_C = np.where(lms[..., k] < 0, np.minimum(-iz / slope, max_C), max_C)
    max_C = np.nan_to_num(max_C, nan=0.0, posinf=0.0, neginf=0.0)
    Xn, Yn, Zn = _jzazbz_to_xyz(J2, max_C * cos_H, max_C * sin_H)
    return np.stack([Xn, Yn, Zn], axis=-1)


def _saturation_ucs(xyz, d, op, lut):
    L_white = float(_y_to_ucs_l(d["white_fulcrum"]))
    x, y = _xyz_to_xy(xyz)
    Y = np.maximum(xyz[..., 1], 0.0)
    U, V = _xy_to_ucs_uv(x, y)
    L_star = _y_to_ucs_l(Y)
    M2 = U * U + V * V
    J = L_star / L_white
    with np.errstate(all="ignore"):
        C = 15.932993652962535 * np.power(L_star, 0.6523997524738018) * np.power(M2, 0.6007557017508491) / L_white
    h = np.arctan2(V, U)
    # JCH -> HCB (hue, chroma, brightness)
    B = J * (np.power(C, 1.33654221029386) + 1.0)
    radius = np.hypot(C, B)
    ok = radius > 0
    safe = np.where(ok, radius, 1.0)
    sin_T = np.where(ok, C / safe, 0.0)
    cos_T = np.where(ok, B / safe, 0.0)
    P = np.maximum(np.finfo(np.float32).tiny, C)
    W = sin_T * C + cos_T * B
    a = np.maximum(1.0 + d["saturation_global"] + op[0] * d["saturation"][0] + op[1] * d["saturation"][1] + op[2] * d["saturation"][2], 0.0)
    b = np.maximum(1.0 + d["brilliance_global"] + op[0] * d["brilliance"][0] + op[1] * d["brilliance"][1] + op[2] * d["brilliance"][2], 0.0)
    max_a = np.hypot(P, W) / P
    a = _soft_clip(a, 0.5 * max_a, max_a)
    P2 = (a - 1.0) * P
    W2 = np.sqrt(np.maximum(P * P * (1.0 - a * a) + W * W, 0.0)) * b
    C2 = np.maximum(cos_T * P2 + sin_T * W2, 0.0)
    B2 = np.maximum(-sin_T * P2 + cos_T * W2, 0.0)
    J2 = B2 / (np.power(C2, 1.33654221029386) + 1.0)
    # gamut map: soft-clip the saturation at constant brightness
    max_colorfulness = _lookup_gamut(lut, h)
    with np.errstate(all="ignore"):
        max_chroma = 15.932993652962535 * np.power(J2 * L_white, 0.6523997524738018) * np.power(max_colorfulness, 0.6007557017508491) / L_white
        B_b = J2 * (np.power(max_chroma, 1.33654221029386) + 1.0)
        S_b = np.where(B_b > 0, max_chroma / np.where(B_b > 0, B_b, 1.0), 0.0)
        S = np.where(B2 > 0, C2 / np.where(B2 > 0, B2, 1.0), 0.0)
        S = _soft_clip(S, 0.8 * S_b, S_b)
        C3 = S * B2
        J3 = B2 / (np.power(C3, 1.33654221029386) + 1.0)
        # JCH -> xyY
        L3 = np.clip(J3 * L_white, 0.0, _UCS_L_UPPER)
        M = np.where(L3 != 0, np.power(C3 * L_white / (15.932993652962535 * np.power(np.where(L3 != 0, L3, 1.0), 0.6523997524738018)), 0.8322850678616855), 0.0)
        Ustar = M * np.cos(h)
        Vstar = M * np.sin(h)
        UVs0 = -5.037522385190711 * Ustar - 2.504856328185843 * Vstar
        UVs1 = 4.760029407436461 * Ustar + 2.874012963239247 * Vstar
        Uu = -1.49217352929 * UVs0 / (np.abs(UVs0) - 1.39656225667)
        Vv = -1.52488637914 * UVs1 / (np.abs(UVs1) - 1.4513954287)
        xd0 = 0.167171472114775 * Uu + 0.141299802443708 * Vv - 0.00801531300850582
        xd1 = -0.150959086409163 * Uu - 0.155185060382272 * Vv - 0.00843312433578007
        xd2 = 0.940254742367256 * Uu + 1.0 * Vv - 0.0256325967652889
        tiny = np.finfo(np.float32).tiny
        div = np.where(xd2 >= 0.0, np.maximum(tiny, xd2), np.minimum(-tiny, xd2))
        xo, yo = xd0 / div, xd1 / div
        Yo = _ucs_l_to_y(L3)
        bad = yo == 0
        Xo = np.where(bad, 0.0, Yo * xo / np.where(bad, 1.0, yo))
        Zo = np.where(bad, 0.0, Yo * (1.0 - xo - yo) / np.where(bad, 1.0, yo))
        Yo = np.where(bad, 0.0, Yo)
    return np.nan_to_num(np.stack([Xo, Yo, Zo], axis=-1), nan=0.0, posinf=0.0, neginf=0.0)


def apply_color_balance(pixels: np.ndarray, values: dict | None, use_gpu: bool = True) -> np.ndarray:
    """The picture (uint8 RGB) graded by `values`. The graphics card does it when there is one and the formula is darktable UCS (features/gpu/colorbalance.py); the processor does it
    otherwise, and always when `use_gpu` is False."""
    if is_neutral(values):
        return pixels
    full = {**DEFAULTS, **{k: float(v) for k, v in (values or {}).items() if k in DEFAULTS}}
    if use_gpu:
        from ..gpu import colorbalance as gpu_colorbalance

        on_card = gpu_colorbalance.process(pixels, full)
        if on_card is not None:
            return on_card
    d = _commit(full)
    lut = _gamut_lut(d["formula"])
    h, w = pixels.shape[:2]
    out = np.empty_like(pixels)
    step = max(8, 40_000 // max(1, w))
    bounds = list(range(0, h, step)) + [h]

    def work(i: int) -> None:
        a, b = bounds[i], bounds[i + 1]
        with np.errstate(all="ignore"):
            out[a:b] = _from_linear(_block(_to_linear(pixels[a:b]), d, lut))

    n = len(bounds) - 1
    if n <= 1 or _WORKERS <= 1:
        for i in range(n):
            work(i)
    else:
        list(_POOL.map(work, range(n)))
    return out


APPLY = apply_color_balance           # what the renderer calls (desktop/render.py)
