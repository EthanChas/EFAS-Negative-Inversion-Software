"""Edge Color: a colour and brightness correction that grows toward the picture's edges - numpy only, no Qt.

A flash (or a lens, or a light that only reaches the middle of the scene) lights the middle of a picture and little of its edges, so the edges are lit by whatever else is there: a room's
fluorescent tubes give a green edge, tungsten an orange one, and the edges are also darker. Flat Field cannot fix that: it corrects the scanner's light, and this is in the picture. This
module shifts the colour and the brightness of the edges back, in OKLab (features/colormix/logic.py), with a soft mask that is 0 in the middle and 1 at the edges.

    Tint      toward magenta (+) or green (-), at the edges       (OKLab a, TINT_SCALE at 1)
    Warmth    toward yellow (+) or blue (-), at the edges         (OKLab b, WARMTH_SCALE at 1)
    Light     brighter (+) or darker (-) at the edges             (OKLab L, LIGHT_SCALE at 1)
    Size      where the correction starts, from the centre (0) to the edge (1): a bigger Size leaves more of the middle alone
    Shape     0 follows an ellipse (a flash's falloff), 1 follows the picture's rectangle (an even band round all four sides)

It works on the finished, cropped picture, so "the edges" are the edges you see. Auto measures how far the outer band's colour is from the middle's and sets Tint and Warmth to bring it back
(Light is left to you, unless asked for)."""
import numpy as np

from ..colormix import logic as cm

KEYS = ("ec_tint", "ec_warmth", "ec_light", "ec_size", "ec_shape")
DEFAULTS = {"ec_tint": 0.0, "ec_warmth": 0.0, "ec_light": 0.0, "ec_size": 0.5, "ec_shape": 0.0}
SIZE_RANGE = (0.0, 0.95)
TINT_SCALE = 0.06       # OKLab a at Tint = 1 (a strong cast: a green or magenta edge is a few hundredths)
WARMTH_SCALE = 0.06
LIGHT_SCALE = 0.15      # OKLab lightness at Light = 1
SHAPE_POWER = 14.0      # the exponent of the distance measure at Shape = 1 (2 is a circle, large is a square)
RING = 0.08             # the outer band Auto measures, as a share of each side
MIDDLE = (0.30, 0.70)   # the middle it compares with
AVERAGE_WEIGHT = 0.9    # how much of the full correction the outer band gets, on average, at the default size


def is_neutral(values: dict | None) -> bool:
    v = values or {}
    return all(abs(float(v.get(k, 0.0))) < 1e-9 for k in ("ec_tint", "ec_warmth", "ec_light"))


def _smoothstep(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def edge_weight(height: int, width: int, size: float, shape: float, work: int = 256) -> np.ndarray:
    """(height, width) float32 weight, 0 in the middle and 1 at the edges, on a small grid scaled up (it is smooth)."""
    import cv2

    k = work / max(height, width)
    mh, mw = max(8, int(round(height * k))), max(8, int(round(width * k)))
    ys = (np.arange(mh, dtype=np.float32) + 0.5) / mh * 2.0 - 1.0
    xs = (np.arange(mw, dtype=np.float32) + 0.5) / mw * 2.0 - 1.0
    p = 2.0 + (SHAPE_POWER - 2.0) * float(np.clip(shape, 0.0, 1.0)) ** 2
    distance = (np.abs(ys[:, None]) ** p + np.abs(xs[None, :]) ** p) ** (1.0 / p)   # 1 at the middle of each edge
    start = float(np.clip(size, SIZE_RANGE[0], SIZE_RANGE[1]))
    weight = _smoothstep((distance - start) / max(1.0 - start, 1e-3)).astype(np.float32)
    return cv2.resize(weight, (width, height), interpolation=cv2.INTER_LINEAR) if (mh, mw) != (height, width) else weight


def apply_edge_color(pixels: np.ndarray, values: dict | None) -> np.ndarray:
    """The 8-bit RGB picture with the edge correction applied; neutral settings return it untouched."""
    v = values or {}
    tint, warmth, light = (float(np.clip(v.get(k, 0.0), -1.0, 1.0)) for k in ("ec_tint", "ec_warmth", "ec_light"))
    if is_neutral(v):
        return pixels
    h, w = pixels.shape[:2]
    weight = edge_weight(h, w, float(v.get("ec_size", DEFAULTS["ec_size"])), float(v.get("ec_shape", DEFAULTS["ec_shape"])))
    out = np.empty(pixels.shape, dtype=np.uint8)
    step = max(1, (1 << 20) // max(w, 1))
    for y in range(0, h, step):
        lab = cm.srgb8_to_oklab(np.ascontiguousarray(pixels[y:y + step]))
        wt = weight[y:y + step]
        lab[..., 0] = np.clip(lab[..., 0] + light * LIGHT_SCALE * wt, 0.0, 1.0)
        lab[..., 1] = lab[..., 1] + tint * TINT_SCALE * wt
        lab[..., 2] = lab[..., 2] + warmth * WARMTH_SCALE * wt
        out[y:y + step] = cm.oklab_to_srgb8(lab.astype(np.float32))
    return out


def _band_means(pixels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mean OKLab (L, a, b) of the outer band and of the middle of a picture."""
    import cv2

    h, w = pixels.shape[:2]
    k = min(1.0, 400.0 / max(h, w))
    small = cv2.resize(np.ascontiguousarray(pixels), (max(8, int(w * k)), max(8, int(h * k))), interpolation=cv2.INTER_AREA) if k < 1.0 else pixels
    lab = cm.srgb8_to_oklab(np.ascontiguousarray(small[..., :3]))
    sh, sw = lab.shape[:2]
    ring_h, ring_w = max(2, int(sh * RING)), max(2, int(sw * RING))
    inside = np.zeros((sh, sw), dtype=bool)
    inside[ring_h:sh - ring_h, ring_w:sw - ring_w] = True
    middle = np.zeros((sh, sw), dtype=bool)
    middle[int(sh * MIDDLE[0]):int(sh * MIDDLE[1]), int(sw * MIDDLE[0]):int(sw * MIDDLE[1])] = True
    return lab[~inside].mean(axis=0), lab[middle].mean(axis=0)


def suggest(pixels: np.ndarray, values: dict | None = None, light: bool = False) -> dict:
    """New Tint and Warmth (and, with light=True, Light) that bring the outer band's colour (and brightness) to the middle's, added to the current ones so a second Auto improves the
    first. Brightness is left to you by default: a picture often has bright or dark things at its edges, and matching them to the middle would darken or lighten real content."""
    v = {**DEFAULTS, **(values or {})}
    ring, middle = _band_means(pixels)
    delta = middle - ring
    scales = (LIGHT_SCALE, TINT_SCALE, WARMTH_SCALE)
    keys = ("ec_light", "ec_tint", "ec_warmth")
    out = {k: float(np.clip(float(v[k]) + float(d) / (s * AVERAGE_WEIGHT), -1.0, 1.0)) for k, d, s in zip(keys, delta, scales)}
    if not light:
        out["ec_light"] = float(v["ec_light"])
    return out


def band_difference(pixels: np.ndarray) -> dict:
    """How far the outer band is from the middle: {"light", "tint", "warmth"} in the same units as the sliders at weight 1 (0 = matched)."""
    ring, middle = _band_means(pixels)
    d = ring - middle
    return {"light": float(d[0] / LIGHT_SCALE), "tint": float(d[1] / TINT_SCALE), "warmth": float(d[2] / WARMTH_SCALE)}
