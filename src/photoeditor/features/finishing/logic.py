"""Finishing - a vignette, and a border or film-carrier frame round the picture. numpy + OpenCV only, no Qt/UI imports.

Applied last, over the finished crop (after the histogram is read and the watermark is on), so they are looks of the print, not of the exposure:
the vignette darkens (or lightens) the corners, the border adds a plain frame outside the picture, and the carrier look is the black, slightly
ragged frame an unmasked film carrier prints round the picture."""

import numpy as np

VIGNETTE_RANGE = (-1.0, 1.0)     # + darkens the edges, - lightens them
VIGNETTE_SIZE_RANGE = (0.0, 1.0)  # how much of the picture, from the centre, the vignette leaves alone
BORDER_MAX = 0.2                  # the border's width, as a share of the picture's shorter side
BORDER_COLORS = {"white": (255, 255, 255), "black": (0, 0, 0), "grey": (128, 128, 128), "paper": (240, 233, 214)}
DEFAULT_VIGNETTE_SIZE = 0.5
DEFAULT_BORDER_COLOR = "white"
_CARRIER_COLOR = (6, 6, 6)
_MASK_SIDE = 192  # the vignette mask is made this small and enlarged: it is smooth, so nothing is lost and 30 megapixels cost nothing


def is_active(vignette: float, border: float, carrier: bool) -> bool:
    return bool(vignette) or border > 0 or bool(carrier)


def _smoothstep(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def apply_vignette(image: np.ndarray, amount: float, size: float = DEFAULT_VIGNETTE_SIZE) -> np.ndarray:
    """Darken (amount > 0) or lighten (amount < 0) the picture towards its corners. size is the share of the way out from the centre that stays
    untouched; the effect then grows smoothly to full strength in the corners."""
    if not amount:
        return image
    import cv2

    h, w = image.shape[:2]
    mh, mw = max(8, round(_MASK_SIDE * h / max(h, w))), max(8, round(_MASK_SIDE * w / max(h, w)))
    ys = (np.arange(mh, dtype=np.float32) + 0.5) / mh * 2.0 - 1.0
    xs = (np.arange(mw, dtype=np.float32) + 0.5) / mw * 2.0 - 1.0
    radius = np.sqrt(ys[:, None] ** 2 + xs[None, :] ** 2) / np.sqrt(2.0)  # 0 at the centre, 1 in the corners (the picture's own shape)
    start = float(np.clip(size, 0.0, 0.98))
    weight = _smoothstep((radius - start) / max(1.0 - start, 1e-3))
    weight = cv2.resize(weight, (w, h), interpolation=cv2.INTER_LINEAR)[..., None]
    pixels = image.astype(np.float32)
    strength = float(np.clip(amount, VIGNETTE_RANGE[0], VIGNETTE_RANGE[1]))
    if strength > 0:
        out = pixels * (1.0 - strength * weight)
    else:
        out = pixels + (255.0 - pixels) * (-strength * weight)
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def _wobble(n: int, amplitude: float, rng: np.random.Generator) -> np.ndarray:
    """A slow, irregular offset along one edge: smoothed noise, 0 on average."""
    import cv2

    raw = rng.normal(0.0, 1.0, max(8, n // 24)).astype(np.float32)
    raw = cv2.resize(raw[None, :], (n, 1), interpolation=cv2.INTER_CUBIC)[0]
    raw = cv2.GaussianBlur(raw[None, :], (0, 0), max(1.0, n / 90.0))[0]
    peak = float(np.abs(raw).max()) or 1.0
    return raw / peak * amplitude


def apply_border(image: np.ndarray, border: float, color: str = DEFAULT_BORDER_COLOR, carrier: bool = False) -> np.ndarray:
    """Surround the picture with a frame `border` (a share of its shorter side) wide, in one of BORDER_COLORS. With `carrier` the frame is black and
    the picture's own edge is eaten into unevenly, like the filed-out opening of a negative carrier; the frame is then at least a little wide even
    when `border` is 0. The picture is never resized, so the result is bigger than the input."""
    h, w = image.shape[:2]
    short = min(h, w)
    width = int(round(max(0.0, min(border, BORDER_MAX)) * short))
    if carrier:
        width = max(width, round(0.02 * short))
    if width <= 0 and not carrier:
        return image
    rgb = _CARRIER_COLOR if carrier else BORDER_COLORS.get(color, BORDER_COLORS[DEFAULT_BORDER_COLOR])
    picture = image
    if carrier:  # the ragged opening: each edge of the picture is cut back by a slowly wandering amount, in the carrier's colour
        rng = np.random.default_rng(h * 100003 + w)
        reach = max(2.0, 0.012 * short)
        top, bottom = _wobble(w, reach, rng) + reach, _wobble(w, reach, rng) + reach
        left, right = _wobble(h, reach, rng) + reach, _wobble(h, reach, rng) + reach
        yy, xx = np.arange(h)[:, None], np.arange(w)[None, :]
        inside = (yy >= top[None, :]) & (yy < h - bottom[None, :]) & (xx >= left[:, None]) & (xx < w - right[:, None])
        picture = np.where(inside[..., None], image, np.array(_CARRIER_COLOR, dtype=np.uint8)).astype(np.uint8)
    out = np.empty((h + 2 * width, w + 2 * width, 3), dtype=np.uint8)
    out[:] = rgb
    out[width:width + h, width:width + w] = picture
    return out
