"""Edge bleed: light from the clear film around a frame (and from the holder's gaps and the sprocket holes) scatters into the picture's edges and lifts them - numpy and OpenCV, no Qt.

A flat-field map (features/flatfield) evens out a light source that falls off smoothly across the whole frame. Edge bleed is a different fault: the rebate and the sprocket holes pass
far more light than the picture does, some of it spreads into the neighbouring picture, and the haze is strongest at the border, dies away a short distance in, and is not the same
on every side. Four tools work on it, in this order:

1. Holder and sprocket fill. Outside the picture, anything that is not the clear film base (the dark edge of a holder, a bright sprocket hole, an edge code) is painted over with the
   film base, so it cannot spill light into the picture or throw the metering off.
2. Edge bleed repair. The light the border passes is spread (a Gaussian blur of the border, wide by "Reach") and a share of it, "Strength", is taken off the picture in linear light.
   An automatic estimate fits the share from how the picture's own edge brightens against the same blur.
3. Edge gradient dodge. For each side the brightness profile running in from the edge is measured (the median along the edge, so the scene does not count) and flattened against the
   level just beyond "Reach": a lift at the edge is dodged down. Needs no clear border: it works from the picture's own edge.
4. Border mask. A soft band over the picture's outer few per cent, in black, grey or white, for what is left; the band can be left out of the metering.

The first three work in linear light on the picture after its geometry (rotation, straightening, flips) and dust repair, before the negative is converted, so the conversion measures
the repaired picture. "Outside the picture" is the crop when there is one (the light round it is what bleeds in: bright clear film and holes count, a dark holder gives off next to
nothing), else the clear film border found round the picture. The mask is laid over the finished picture. Everything is on a downsampled copy except the final multiply and subtract, so it costs a few passes over the full picture, like the flat field.
"""

import numpy as np

KEYS = ("edge_holder", "edge_bleed", "edge_dodge", "edge_reach", "edge_mask", "edge_feather", "edge_mask_color", "edge_mask_meter")
DEFAULTS = {"edge_holder": 0.0, "edge_bleed": 0.0, "edge_dodge": 0.0, "edge_reach": 0.08, "edge_mask": 0.0, "edge_feather": 0.5, "edge_mask_color": "black", "edge_mask_meter": True}
SCAN_KEYS = ("edge_holder", "edge_bleed", "edge_dodge", "edge_reach")
REACH_RANGE = (0.02, 0.30)    # of the picture's shorter side
MASK_RANGE = (0.0, 0.15)      # of the picture's shorter side, on each edge
MASK_COLOURS = {"black": (0, 0, 0), "grey": (128, 128, 128), "white": (255, 255, 255)}
MASK_COLOUR_LABELS = {"black": "Black", "grey": "Grey", "white": "White"}

_GAMMA = 2.2                  # the same stand-in for the scan's encoding as the flat field uses
_WORK = 1024                  # the longest side of the copy the fields are worked out on
BLEED_MAX = 0.60              # the share of the scattered border light taken off at Strength 1
HOLDER_BAND = 0.15            # how far from the picture, as a share of its shorter side, holder fill looks
HOLDER_DEVIATION = 0.25       # how far (relative to the film base) outside the frame a pixel may be from the base before it counts as holder or sprocket
DODGE_LIMITS = (0.7, 1.4)     # the most the dodge may darken or lighten any part of an edge
_cv2 = None


def _cv():
    global _cv2
    if _cv2 is None:
        import cv2

        _cv2 = cv2
    return _cv2


def scan_active(values: dict | None) -> bool:
    """Is any of the tools that work on the raw scan switched on?"""
    v = values or {}
    return any(float(v.get(k, 0.0)) > 1e-9 for k in ("edge_holder", "edge_bleed", "edge_dodge"))


def mask_active(values: dict | None) -> bool:
    return float((values or {}).get("edge_mask", 0.0)) > 1e-9


def is_neutral(values: dict | None) -> bool:
    return not scan_active(values) and not mask_active(values)


def meter_inset(values: dict | None) -> float:
    """The fraction of the picture the metering should leave out on each edge: the mask's band, when it is on and the option is set."""
    v = values or {}
    return float(v.get("edge_mask", 0.0)) if mask_active(v) and bool(v.get("edge_mask_meter", True)) else 0.0


def scan_token(values: dict | None) -> tuple:
    """What a cached repaired scan depends on."""
    v = values or {}
    return tuple(round(float(v.get(k, DEFAULTS[k])), 4) for k in SCAN_KEYS)


# ---------------------------------------------------------------------------------------------------------- the picture's frame
def _to_8bit(pixels: np.ndarray) -> np.ndarray:
    return pixels if pixels.dtype == np.uint8 else (pixels >> 8).astype(np.uint8)


def find_frame(pixels: np.ndarray):
    """(x1, y1, x2, y2) of the picture inside its clear border, in the scan's own pixels, or None when there is no clear border (the picture runs to the edges)."""
    from ..geometry.autocrop import detect_frame

    found = detect_frame(np.ascontiguousarray(_to_8bit(pixels)))
    return None if found is None else tuple(int(v) for v in found.rect)


def _to_linear(pixels: np.ndarray) -> np.ndarray:
    top = 65535.0 if pixels.dtype == np.uint16 else 255.0
    return np.power(pixels.astype(np.float32) * np.float32(1.0 / top), np.float32(_GAMMA))


def _from_linear(lin: np.ndarray, dtype) -> np.ndarray:
    np.clip(lin, 0.0, 1.0, out=lin)
    out = np.power(lin, np.float32(1.0 / _GAMMA))
    top = 65535.0 if dtype == np.uint16 else 255.0
    out *= np.float32(top)
    return (out + np.float32(0.5)).astype(dtype)


def _small(lin: np.ndarray):
    cv2 = _cv()
    h, w = lin.shape[:2]
    k = min(1.0, _WORK / max(h, w))
    if k >= 1.0:
        return lin.copy(), 1.0
    return cv2.resize(lin, (max(8, round(w * k)), max(8, round(h * k))), interpolation=cv2.INTER_AREA), k


def _rect_small(rect, k: float, sh: int, sw: int):
    x1, y1, x2, y2 = (rect[0] * k, rect[1] * k, rect[2] * k, rect[3] * k)
    return max(0, int(round(x1))), max(0, int(round(y1))), min(sw, int(round(x2))), min(sh, int(round(y2)))


def _border_colour(lin: np.ndarray, outside: np.ndarray) -> np.ndarray:
    """The clear film base outside the picture (linear RGB): the median of the pixels within 60-100% of the brightest tone out there, so the dark holder, which can be most of
    what is outside a crop, cannot pull it, and neither can the few blown sprocket holes."""
    pix = lin[outside]
    if pix.shape[0] < 16:
        return np.median(lin.reshape(-1, 3), axis=0)
    lum = pix.mean(axis=1)
    top = float(np.percentile(lum, 99.5))
    sel = pix[(lum >= 0.6 * top) & (lum <= top * 0.995)]
    return np.median(sel if sel.shape[0] >= 8 else pix, axis=0)


def _light_source(lin: np.ndarray, outside: np.ndarray) -> np.ndarray:
    """The light that comes from outside the picture: its pixels that are as bright as the clear film base and the holes (the dark holder and anything dim give off next to
    nothing), faded in between 55% and 85% of that brightness."""
    lum = lin.mean(axis=2)
    if not outside.any():
        return np.zeros_like(lin)
    ref = max(float(np.percentile(lum[outside], 99.5)), 1e-4)   # the brightest tone out there is the clear base (or the holes), however much of the outside is dark
    t = np.clip((lum / ref - 0.55) / 0.30, 0.0, 1.0)
    return lin * (outside * (t * t * (3.0 - 2.0 * t)))[..., None]


# ---------------------------------------------------------------------------------------------------------- the three scan tools
def _holder_mask(lin: np.ndarray, outside: np.ndarray, base: np.ndarray, rect) -> np.ndarray:
    """Soft 0-1 mask of what is outside the frame but not clear film base. A guard band round the frame is left alone: the detected edge is only good to a few pixels, and the
    picture's own first pixels must not be taken for holder."""
    cv2 = _cv()
    dev = (np.abs(lin - base[None, None, :]) / (base[None, None, :] + 0.02)).max(axis=2)
    guard = max(3, int(min(lin.shape[:2]) * 0.012))
    far = np.ones(outside.shape, dtype=bool)
    far[max(0, rect[1] - guard):rect[3] + guard, max(0, rect[0] - guard):rect[2] + guard] = False
    band = max(guard + 1, int(min(lin.shape[:2]) * HOLDER_BAND))   # only the strip round the picture: further out is the holder's body, which does no harm
    near = np.zeros(outside.shape, dtype=bool)
    near[max(0, rect[1] - band):rect[3] + band, max(0, rect[0] - band):rect[2] + band] = True
    hard = ((dev > HOLDER_DEVIATION) & outside & far & near).astype(np.float32)
    k = max(3, int(min(lin.shape[:2]) * 0.012)) | 1
    hard = cv2.dilate(hard, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    return np.clip(cv2.GaussianBlur(hard, (0, 0), max(1.0, k / 3.0)), 0.0, 1.0)


def _bleed_field(source: np.ndarray, sigma: float) -> np.ndarray:
    """The border's light spread by a Gaussian of this sigma (pixels): what lands on the picture, per unit of share."""
    return _cv().GaussianBlur(source, (0, 0), sigmaX=sigma, sigmaY=sigma)


def _sigma(reach: float, sh: int, sw: int) -> float:
    return max(1.0, float(reach) * min(sh, sw) * 0.5)


def _side_profiles(plane: np.ndarray, rect, depth: int) -> dict[str, np.ndarray]:
    """For each side, the median along the edge (the middle 80%) of `plane` at 0 .. depth-1 pixels in from the frame's edge."""
    x1, y1, x2, y2 = rect
    w, h = x2 - x1, y2 - y1
    ya, yb = y1 + int(h * 0.1), y2 - int(h * 0.1)
    xa, xb = x1 + int(w * 0.1), x2 - int(w * 0.1)
    out = {}
    if yb > ya:
        out["left"] = np.median(plane[ya:yb, x1:x1 + depth], axis=0)
        out["right"] = np.median(plane[ya:yb, x2 - depth:x2], axis=0)[::-1]
    if xb > xa:
        out["top"] = np.median(plane[y1:y1 + depth, xa:xb], axis=1)
        out["bottom"] = np.median(plane[y2 - depth:y2, xa:xb], axis=1)[::-1]
    return {side: prof for side, prof in out.items() if prof.shape[0] == depth}


def estimate_bleed(pixels: np.ndarray, reach: float, rect=None) -> float:
    """The Strength (0-1) that best explains how the picture's edge brightens toward a clear border, or 0.0 when there is no border to measure. A guess: a bright scene edge reads as bleed."""
    rect = rect if rect is not None else find_frame(pixels)
    if rect is None:
        return 0.0
    lin, k = _small(_to_linear(pixels))
    sh, sw = lin.shape[:2]
    r = _rect_small(rect, k, sh, sw)
    outside = np.ones((sh, sw), dtype=bool)
    outside[r[1]:r[3], r[0]:r[2]] = False
    if outside.sum() < 16 or (r[2] - r[0]) < 24 or (r[3] - r[1]) < 24:
        return 0.0
    field = _bleed_field(_light_source(lin, outside), _sigma(reach, sh, sw)).mean(axis=2)
    depth = max(6, int(min(r[2] - r[0], r[3] - r[1]) * 0.25))
    seen, model = _side_profiles(lin.mean(axis=2), r, depth), _side_profiles(field, r, depth)
    shares = []
    for side in seen:
        far = slice(depth * 3 // 4, depth)
        o = seen[side] - seen[side][far].mean()
        f = model[side] - model[side][far].mean()
        denom = float((f * f).sum())
        # the border has to reach into the model for the side to say anything
        if denom > 1e-9 and (f[0] - f[-1]) > 0.002:
            shares.append(float((o * f).sum()) / denom)
    if not shares:
        return 0.0
    return float(np.clip(np.median(shares) / BLEED_MAX, 0.0, 1.0))


def _dodge_gain(lum: np.ndarray, rect, reach: float, strength: float) -> np.ndarray:
    """(h, w) gain that flattens each edge's brightness profile to the level beyond `reach`, scaled by strength."""
    cv2 = _cv()
    sh, sw = lum.shape
    x1, y1, x2, y2 = rect
    depth = max(4, int(reach * min(x2 - x1, y2 - y1)))
    gain = np.ones((sh, sw), dtype=np.float32)
    if 2 * depth >= min(x2 - x1, y2 - y1) // 2:
        return gain
    taper = np.clip((depth - np.arange(depth)) / (depth * 0.25), 0.0, 1.0)   # the last quarter of the reach fades back to no change
    lo, hi = DODGE_LIMITS
    for side, prof in _side_profiles(lum, rect, 2 * depth).items():
        ref = float(np.median(prof[depth:]))
        inside = np.clip(prof[:depth], 1e-4, None)
        g = np.clip(ref / cv2.GaussianBlur(inside.astype(np.float32)[None, :], (0, 0), max(1.0, depth / 8.0))[0], lo, hi)
        g = (1.0 + (g - 1.0) * taper * float(strength)).astype(np.float32)
        if side == "left":
            gain[:, x1:x1 + depth] *= g[None, :]
        elif side == "right":
            gain[:, x2 - depth:x2] *= g[::-1][None, :]
        elif side == "top":
            gain[y1:y1 + depth, :] *= g[:, None]
        else:
            gain[y2 - depth:y2, :] *= g[::-1][:, None]
    return gain


def correct_scan(pixels: np.ndarray, values: dict, rect=None) -> np.ndarray:
    """The scan with Holder and sprocket fill, Edge bleed repair and Edge gradient dodge applied, at the scan's own depth. Returns the same array when nothing is on or nothing can be done."""
    if not scan_active(values):
        return pixels
    cv2 = _cv()
    rect = rect if rect is not None else find_frame(pixels)
    h, w = pixels.shape[:2]
    holder_s = float(np.clip(values.get("edge_holder", 0.0), 0.0, 1.0))
    bleed_s = float(np.clip(values.get("edge_bleed", 0.0), 0.0, 1.0))
    dodge_s = float(np.clip(values.get("edge_dodge", 0.0), 0.0, 1.0))
    reach = float(np.clip(values.get("edge_reach", DEFAULTS["edge_reach"]), *REACH_RANGE))
    has_border = rect is not None and (rect[2] - rect[0]) > 24 and (rect[3] - rect[1]) > 24 and (rect[0] > 2 or rect[1] > 2 or rect[2] < w - 2 or rect[3] < h - 2)
    if not has_border:
        if dodge_s <= 0.0:
            return pixels
        rect = (0, 0, w, h)   # no clear border: the dodge works from the picture's own edge
    lin_full = _to_linear(pixels)
    lin, k = _small(lin_full)
    sh, sw = lin.shape[:2]
    r = _rect_small(rect, k, sh, sw)
    inside = np.zeros((sh, sw), dtype=bool)
    inside[r[1]:r[3], r[0]:r[2]] = True
    outside = ~inside
    changed = False
    light = _light_source(lin, outside) if has_border and bleed_s > 0.0 else None   # the real light round the picture, before any fill paints over it
    if has_border and holder_s > 0.0:
        base = _border_colour(lin, outside)
        mask = _holder_mask(lin, outside, base, r) * holder_s
        mask_full = cv2.resize(mask, (w, h), interpolation=cv2.INTER_LINEAR) if mask.shape != (h, w) else mask
        mask_full[rect[1]:rect[3], rect[0]:rect[2]] = 0.0
        lin_full *= (1.0 - mask_full)[..., None]
        lin_full += mask_full[..., None] * base[None, None, :].astype(np.float32)
        lin = lin * (1.0 - (mask * outside)[..., None]) + base[None, None, :] * (mask * outside)[..., None]
        changed = True
    if light is not None:
        field = _bleed_field(light, _sigma(reach, sh, sw)) * (bleed_s * BLEED_MAX)
        field *= inside[..., None]
        field_full = cv2.resize(field, (w, h), interpolation=cv2.INTER_LINEAR) if field.shape[:2] != (h, w) else field
        lin_full -= field_full
        lin = lin - field
        changed = True
    if dodge_s > 0.0:
        gain = _dodge_gain(np.clip(lin.mean(axis=2), 1e-4, None), r, reach, dodge_s)
        if gain.shape != (h, w):
            gain = cv2.resize(gain, (w, h), interpolation=cv2.INTER_LINEAR)
        lin_full *= gain[..., None]
        changed = True
    return _from_linear(lin_full, pixels.dtype) if changed else pixels


# ---------------------------------------------------------------------------------------------------------- the border mask
def apply_edge_mask(image: np.ndarray, amount: float, feather: float, colour: str) -> np.ndarray:
    """The finished picture with a soft band over its outer `amount` (a fraction of the shorter side, on each edge), `feather` (0 hard, 1 the whole band fading) in `colour`."""
    if amount <= 0.0:
        return image
    h, w = image.shape[:2]
    band = max(1.0, float(amount) * min(h, w))
    soft = float(np.clip(feather, 0.0, 1.0)) * band + 1e-6

    def profile(n: int) -> np.ndarray:
        dist = np.minimum(np.arange(n), np.arange(n)[::-1]).astype(np.float32)
        t = np.clip((band - dist) / soft, 0.0, 1.0)
        return t * t * (3.0 - 2.0 * t)

    alpha = np.maximum(profile(w)[None, :], profile(h)[:, None])
    scale = 257.0 if image.dtype == np.uint16 else 1.0
    rgb = np.array(MASK_COLOURS.get(colour, MASK_COLOURS["black"]), dtype=np.float32) * scale
    out = image.astype(np.float32) * (1.0 - alpha[..., None]) + rgb[None, None, :image.shape[2]] * alpha[..., None]
    return (out + 0.5).astype(image.dtype)
