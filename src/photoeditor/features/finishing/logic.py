"""Finishing - a vignette, and a border round the picture."""

import numpy as np

VIGNETTE_RANGE = (-1.0, 1.0)
VIGNETTE_SIZE_RANGE = (0.0, 1.0)
BORDER_MAX = 0.2
BORDER_COLORS = {"white": (255, 255, 255), "black": (0, 0, 0), "grey": (128, 128, 128), "paper": (240, 233, 214)}
DEFAULT_VIGNETTE_SIZE = 0.5
DEFAULT_BORDER_COLOR = "white"
_MASK_SIDE = 192


def is_active(vignette: float, border: float) -> bool:
    return bool(vignette) or border > 0


def _smoothstep(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def apply_vignette(image: np.ndarray, amount: float, size: float = DEFAULT_VIGNETTE_SIZE) -> np.ndarray:
    """Darken (amount > 0) or lighten (amount < 0) the picture towards its corners."""
    if not amount:
        return image
    import cv2

    h, w = image.shape[:2]
    mh, mw = max(8, round(_MASK_SIDE * h / max(h, w))), max(8, round(_MASK_SIDE * w / max(h, w)))
    ys = (np.arange(mh, dtype=np.float32) + 0.5) / mh * 2.0 - 1.0
    xs = (np.arange(mw, dtype=np.float32) + 0.5) / mw * 2.0 - 1.0
    radius = np.sqrt(ys[:, None] ** 2 + xs[None, :] ** 2) / np.sqrt(2.0)
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


def apply_border(image: np.ndarray, border: float, color: str = DEFAULT_BORDER_COLOR) -> np.ndarray:
    """Surround the picture with a frame `border` (a share of its shorter side) wide, in one of BORDER_COLORS."""
    h, w = image.shape[:2]
    width = border_pixels(image.shape, border)
    if width <= 0:
        return image
    out = np.empty((h + 2 * width, w + 2 * width, 3), dtype=np.uint8)
    out[:] = BORDER_COLORS.get(color, BORDER_COLORS[DEFAULT_BORDER_COLOR])
    out[width:width + h, width:width + w] = image
    return out


def border_pixels(shape, border: float) -> int:
    """How wide the frame is, in pixels, for a picture of this shape (the same sum apply_border uses)."""
    short = min(shape[0], shape[1])
    return int(round(max(0.0, min(border, BORDER_MAX)) * short))
