"""Colour in a perceptual space: Vibrance, the Color Mixer and the lab's scanner colour response - numpy only, no Qt.

Colour sliders that work on RGB or HSV values move lightness and hue along with the thing they were asked to move: raising the saturation of blue darkens it, shifting yellow toward
green changes how bright it looks. Here the picture is taken into OKLab (Ottosson, 2020), a space built so that equal steps are equal perceived steps, and polar as OKLCH: L is
lightness, C is chroma (how colourful), h is hue. Vibrance and the mixer then change C, h and L directly, and the result is brought back into the sRGB gamut by reducing chroma, not by
clipping channels (which shifts hue).

* Vibrance raises the chroma of the muted colours more than the vivid ones, and leaves skin hues and greys alone.
* The Color Mixer has eight colour ranges (red, orange, yellow, green, aqua, blue, purple, magenta), each with Hue, Saturation and Lightness. A range has a smooth window on the hue
  wheel and fades out for near-greys, so neighbours blend and a grey never picks up a colour.
* Color Toning tints the shadows, midtones and highlights each toward a hue of your choice (Hue in degrees round the OKLab wheel, Strength 0-1), the way NegPy's split toning does
  but with a third region and in OKLab; it is added to a and b, so the lightness stays where it was. It is applied last, after the mixer and the scanner response.
* The scanner colour response is a small, documented stand-in for what a lab scanner's colour table does: a cast in the shadows, midtones and highlights (in OKLab a, b) and a
  chroma change, scaled by an amount. The directions follow how labs describe each machine (docs/lab-look-research.md); the sizes are estimates."""

import numpy as np

BANDS = ("red", "orange", "yellow", "green", "aqua", "blue", "purple", "magenta")
BAND_HUES = {"red": 29.0, "orange": 55.0, "yellow": 100.0, "green": 145.0, "aqua": 195.0, "blue": 262.0, "purple": 305.0, "magenta": 345.0}   # OKLCH hue, degrees
BAND_WIDTH = 60.0           # half-width of a band's window on the hue wheel, degrees (the windows are then normalised so they always add up to one)
HUE_SHIFT = 30.0            # degrees a band's hue moves at +/-1
LIGHT_SHIFT = 0.12          # OKLab lightness a band moves at +/-1
CHROMA_FLOOR = (0.012, 0.06)  # chroma below which a pixel is grey (untouched) and above which it takes the band's full effect
VIBRANCE_FLOOR = (0.004, 0.025)  # the same for vibrance, which is meant for the muted colours and so lets in much weaker ones
SKIN = (30.0, 75.0)         # hues vibrance protects, degrees
VIBRANCE_REACH = 0.22       # chroma above which a colour is "already vivid" for vibrance

REGIONS = ("shadows", "mids", "highs")
TONING_CHROMA = 0.08        # OKLab chroma a region's tint reaches at full strength
TONING_KEYS = tuple(f"tone_{kind}_{region}" for region in REGIONS for kind in ("hue", "amt"))   # tone_hue_* in degrees (0-360), tone_amt_* 0-1
MIXER_KEYS = tuple(f"mix_{kind}_{band}" for band in BANDS for kind in ("hue", "sat", "lum"))
MIXER_PANEL_KEYS = ("vibrance",) + MIXER_KEYS   # what the Color Mixer module holds; Color Toning holds TONING_KEYS
KEYS = MIXER_PANEL_KEYS + TONING_KEYS
DEFAULTS = {key: 0.0 for key in KEYS}
RANGE = (-1.0, 1.0)

RESPONSES = ("none", "frontier", "noritsu", "pakon", "crystal")
RESPONSE_LABELS = {"none": "None", "frontier": "Frontier", "noritsu": "Noritsu", "pakon": "Pakon", "crystal": "Crystal Archive"}
# Per scanner: (a, b) cast added in the shadows, midtones and highlights (OKLab units; +a is toward red-magenta, +b toward yellow), and a chroma multiplier.
# Frontier: more colour, cooler (cyan-blue) shadows, golden midtones. Noritsu: softer colour, a faint green in the shadows, peach midtones. Pakon: a little more colour,
# clean and neutral. Crystal Archive paper: more colour and a touch of warmth. The directions are from published descriptions; the sizes are estimates.
RESPONSE = {
    "frontier": {"shadows": (-0.010, -0.014), "mids": (0.004, 0.012), "highs": (0.0, 0.006), "chroma": 1.10},
    "noritsu": {"shadows": (-0.010, 0.004), "mids": (0.006, 0.006), "highs": (0.002, 0.002), "chroma": 0.92},
    "pakon": {"shadows": (0.0, 0.0), "mids": (0.0, 0.0), "highs": (0.0, 0.002), "chroma": 1.06},
    "crystal": {"shadows": (0.0, -0.004), "mids": (0.004, 0.008), "highs": (0.0, 0.004), "chroma": 1.12},
}

_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929], [0.2119034982, 0.6806995451, 0.1073969566], [0.0883024619, 0.2817188376, 0.6299787005]], dtype=np.float32)
_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468], [1.9779984951, -2.4285922050, 0.4505937099], [0.0259040371, 0.7827717662, -0.8086757660]], dtype=np.float32)
_M1_INV = np.linalg.inv(_M1).astype(np.float32)
_M2_INV = np.linalg.inv(_M2).astype(np.float32)
_SRGB_TO_LINEAR = np.where((np.arange(256) / 255.0) <= 0.04045, (np.arange(256) / 255.0) / 12.92, (((np.arange(256) / 255.0) + 0.055) / 1.055) ** 2.4).astype(np.float32)


def toning_active(values: dict | None) -> bool:
    """Any region has a strength (a hue alone changes nothing)."""
    return any(abs(float((values or {}).get(f"tone_amt_{r}", 0.0))) > 1e-9 for r in REGIONS)


def is_neutral(values: dict | None = None, response: str = "none") -> bool:
    return response in ("none", "", None) and not toning_active(values) and all(abs(float((values or {}).get(k, 0.0))) < 1e-9 for k in MIXER_PANEL_KEYS)


def tint_swatch(hue: float) -> tuple[int, int, int]:
    """The display colour of a toning hue (degrees): a mid-light, fairly colourful OKLab colour at that angle."""
    rad = np.radians(float(hue))
    lab = np.array([[[0.72, 0.11 * np.cos(rad), 0.11 * np.sin(rad)]]], dtype=np.float32)
    r, g, b = oklab_to_srgb8(lab)[0, 0]
    return int(r), int(g), int(b)


_SRGB_TO_LINEAR16 = np.where((np.arange(65536) / 65535.0) <= 0.04045, (np.arange(65536) / 65535.0) / 12.92, (((np.arange(65536) / 65535.0) + 0.055) / 1.055) ** 2.4).astype(np.float32)


def srgb8_to_oklab(pixels: np.ndarray) -> np.ndarray:
    """(h, w, 3) uint8 sRGB (or uint16, the same colours at 16 bits) -> (h, w, 3) float32 OKLab (L, a, b)."""
    linear = (_SRGB_TO_LINEAR16 if pixels.dtype == np.uint16 else _SRGB_TO_LINEAR)[pixels]
    lms = np.cbrt(np.clip(linear @ _M1.T, 0.0, None))
    return lms @ _M2.T


def _linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def oklab_to_linear(lab: np.ndarray) -> np.ndarray:
    lms = lab @ _M2_INV.T
    return (lms ** 3) @ _M1_INV.T


def oklab_to_srgb8(lab: np.ndarray, wide: bool = False) -> np.ndarray:
    """OKLab -> uint8 sRGB (uint16 when `wide`), with the colours that fall outside the sRGB gamut brought in by reducing their chroma (up to a few steps) before the last clip."""
    lab = lab.copy()
    for _ in range(6):
        rgb = oklab_to_linear(lab)
        outside = (rgb.min(axis=-1) < -0.0005) | (rgb.max(axis=-1) > 1.0005)
        if not outside.any():
            break
        lab[..., 1:][outside] *= 0.85
    top = 65535.0 if wide else 255.0
    return np.clip(np.rint(_linear_to_srgb(oklab_to_linear(lab)) * top), 0, top).astype(np.uint16 if wide else np.uint8)


def _smoothstep(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def band_weights(hue_deg: np.ndarray) -> dict[str, np.ndarray]:
    """How much each colour range counts at each hue (degrees): a raised-cosine window per band, normalised so the eight always add up to one - every hue belongs to its
    neighbouring bands in proportion, with no gaps and no double counting."""
    raw = {}
    for band, centre in BAND_HUES.items():
        d = np.abs((hue_deg - centre + 180.0) % 360.0 - 180.0)
        raw[band] = np.where(d < BAND_WIDTH, 0.5 * (1.0 + np.cos(np.pi * d / BAND_WIDTH)), 0.0).astype(np.float32)
    total = np.maximum(sum(raw.values()), 1e-6)
    return {band: w / total for band, w in raw.items()}


def tone_weights(lightness: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Shadows, midtones and highlights weights from OKLab lightness (0-1), smooth and overlapping."""
    shadows = 1.0 - _smoothstep(0.18, 0.60, lightness)
    highs = _smoothstep(0.50, 0.90, lightness)
    return shadows, np.clip(1.0 - shadows - highs, 0.0, 1.0), highs


def apply_color(pixels: np.ndarray, values: dict | None = None, response: str = "none", amount: float = 1.0) -> np.ndarray:
    """An 8-bit RGB picture (or a 16-bit one, kept at 16 bits) with Vibrance, the Color Mixer and a scanner colour response applied in OKLCH. Neutral settings return the picture untouched."""
    values = values or {}
    amount = float(min(max(amount, 0.0), 1.0))
    use_response = response in RESPONSE and amount > 0.0
    vibrance = float(values.get("vibrance", 0.0))
    mix = {k: float(values.get(k, 0.0)) for k in MIXER_KEYS if abs(float(values.get(k, 0.0))) > 1e-9}
    toning = [(r, float(values.get(f"tone_hue_{r}", 0.0)), float(min(max(values.get(f"tone_amt_{r}", 0.0), 0.0), 1.0))) for r in REGIONS]
    toning = [t for t in toning if t[2] > 1e-9]
    if not use_response and vibrance == 0.0 and not mix and not toning:
        return pixels
    h, w = pixels.shape[:2]
    wide = pixels.dtype == np.uint16
    out = np.empty(pixels.shape, dtype=pixels.dtype)
    step = max(1, (1 << 20) // max(w, 1))
    for y in range(0, h, step):
        lab = srgb8_to_oklab(np.ascontiguousarray(pixels[y:y + step]))
        light, a, b = lab[..., 0].copy(), lab[..., 1].copy(), lab[..., 2].copy()
        chroma = np.hypot(a, b)
        hue = np.degrees(np.arctan2(b, a)) % 360.0
        colourful = _smoothstep(CHROMA_FLOOR[0], CHROMA_FLOOR[1], chroma)
        if mix:
            weights = band_weights(hue)
            d_hue = np.zeros_like(chroma); d_sat = np.zeros_like(chroma); d_lum = np.zeros_like(chroma)
            for band in BANDS:
                wb = weights[band] * colourful
                d_hue += mix.get(f"mix_hue_{band}", 0.0) * wb
                d_sat += mix.get(f"mix_sat_{band}", 0.0) * wb
                d_lum += mix.get(f"mix_lum_{band}", 0.0) * wb
            hue = (hue + d_hue * HUE_SHIFT) % 360.0
            chroma = chroma * np.clip(1.0 + d_sat, 0.0, 3.0)
            light = np.clip(light + d_lum * LIGHT_SHIFT, 0.0, 1.0)
        if vibrance != 0.0:
            muted = 1.0 - _smoothstep(0.03, VIBRANCE_REACH, chroma)
            skin = np.abs((hue - 0.5 * (SKIN[0] + SKIN[1]) + 180.0) % 360.0 - 180.0)
            skin_guard = 1.0 - 0.6 * (1.0 - _smoothstep(0.5 * (SKIN[1] - SKIN[0]), 0.5 * (SKIN[1] - SKIN[0]) + 25.0, skin))
            chroma = chroma * np.clip(1.0 + vibrance * muted * skin_guard * _smoothstep(VIBRANCE_FLOOR[0], VIBRANCE_FLOOR[1], chroma), 0.0, 3.0)
        a, b = chroma * np.cos(np.radians(hue)), chroma * np.sin(np.radians(hue))
        if use_response:
            spec = RESPONSE[response]
            ws, wm, wh = tone_weights(light)
            for weight, key in ((ws, "shadows"), (wm, "mids"), (wh, "highs")):
                a = a + amount * spec[key][0] * weight
                b = b + amount * spec[key][1] * weight
            scale = 1.0 + amount * (spec["chroma"] - 1.0)
            a, b = a * scale, b * scale
        if toning:   # last: a tint of each tonal region, added in OKLab a / b so lightness is kept
            weights = dict(zip(REGIONS, tone_weights(light)))
            for region, degrees, strength in toning:
                rad = np.radians(degrees)
                a = a + np.cos(rad) * TONING_CHROMA * strength * weights[region]
                b = b + np.sin(rad) * TONING_CHROMA * strength * weights[region]
        out[y:y + step] = oklab_to_srgb8(np.stack([light, a, b], axis=-1).astype(np.float32), wide)
    return out
