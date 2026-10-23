"""Blending a module's result through a mask: what a module's "Mask" box does - numpy and OpenCV, no Qt. Ported from darktable's blend (src/develop/blend.c, blend_gui.c).

Each module can be blended into the picture it was given. `Blend.mode` is darktable's mask mode: **off** (the module acts on everything, as it always did), **uniform** (everywhere, at
`opacity`) or **drawn** (only where the drawn mask named by `mask_id` is). For a drawn mask the mask is made in darktable's order:

    1. the drawn mask (a shape or a group, see raster.py), turned over if `invert` (darktable's "invert mask polarity"), times `opacity` (0..100 %)
    2. `blur`: a Gaussian blur of the mask, in pixels of the 1600 pixel editing preview (so it looks the same on a full-size export)
    3. `feather`: the mask pulled to the edges of the picture with a guided filter, of this radius
    4. `contrast` and `brightness`: darktable's mask tone curve (the S-curve and shift of the mask's own values), then back to the opacity

and the picture is `base + (module's result - base) x mask`: darktable's "normal" blend. There is no parametric (colour-range) mask here yet: only the drawn mask and the opacity."""
import math
from dataclasses import dataclass

import cv2
import numpy as np

OFF, UNIFORM, DRAWN = "off", "uniform", "drawn"
MODES = (OFF, UNIFORM, DRAWN)
MODE_LABELS = {OFF: "Off", UNIFORM: "Uniformly", DRAWN: "Drawn mask"}
PREVIEW_WIDTH = 1600      # blur and feather radii are given in pixels of a picture this wide


def _num(value, low: float, high: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, v)) if math.isfinite(v) else default


@dataclass(frozen=True)
class Blend:
    mode: str = OFF
    mask_id: int = 0            # the shape or group of the photo's MaskSet that the drawn mask is
    opacity: float = 100.0      # per cent
    invert: bool = False        # the mask's polarity
    blur: float = 0.0           # pixels (at 1600 across)
    feather: float = 0.0        # guided-filter radius, pixels (at 1600 across)
    brightness: float = 0.0     # -1 .. 1
    contrast: float = 0.0       # -1 .. 1

    def active(self) -> bool:
        return self.mode in (UNIFORM, DRAWN)

    def uses_mask(self) -> bool:
        return self.mode == DRAWN

    def to_dict(self) -> dict:
        return {"mode": self.mode, "mask_id": self.mask_id, "opacity": self.opacity, "invert": self.invert, "blur": self.blur, "feather": self.feather,
                "brightness": self.brightness, "contrast": self.contrast}

    @staticmethod
    def from_dict(d) -> "Blend":
        if not isinstance(d, dict):
            return Blend()
        try:
            mask_id = int(d.get("mask_id", 0))
        except (TypeError, ValueError):
            mask_id = 0
        return Blend(d.get("mode") if d.get("mode") in MODES else OFF, max(0, mask_id), _num(d.get("opacity"), 0.0, 100.0, 100.0), bool(d.get("invert", False)),
                     _num(d.get("blur"), 0.0, 100.0, 0.0), _num(d.get("feather"), 0.0, 100.0, 0.0), _num(d.get("brightness"), -1.0, 1.0, 0.0), _num(d.get("contrast"), -1.0, 1.0, 0.0))


def blends_from_dict(d) -> dict:
    """{module key: Blend} from what was saved; only the active ones are kept."""
    out = {}
    if isinstance(d, dict):
        for key, value in d.items():
            blend = Blend.from_dict(value)
            if blend.active() and isinstance(key, str):
                out[key] = blend
    return out


def blends_to_dict(blends: dict) -> dict:
    return {key: b.to_dict() for key, b in blends.items() if b.active()}


# ------------------------------------------------------------------ making the mask
def guided_filter(guide: np.ndarray, source: np.ndarray, radius: int, eps: float) -> np.ndarray:
    """A guided filter (He et al.) of `source` by `guide`, both float32 (h, w): it smooths the source but keeps its edges where the guide has them."""
    r = max(1, int(radius))
    k = (2 * r + 1, 2 * r + 1)
    mean = lambda a: cv2.boxFilter(a, cv2.CV_32F, k, borderType=cv2.BORDER_REFLECT)
    mg, ms = mean(guide), mean(source)
    var = mean(guide * guide) - mg * mg
    cov = mean(guide * source) - mg * ms
    a = cov / (var + eps)
    b = ms - a * mg
    return mean(a) * guide + mean(b)


def tone_curve(mask: np.ndarray, contrast: float, brightness: float, opacity: float) -> np.ndarray:
    """darktable's mask tone curve (_develop_blend_process_mask_tone_curve): the mask's values are put through an S-curve of `contrast` after a `brightness` shift, then scaled by opacity."""
    e = math.exp(3.0 * contrast)
    eps = 16.0 * float(np.finfo(np.float32).eps)
    x = 2.0 * (mask / max(opacity, 1e-6)) - 1.0
    if 1.0 - brightness <= 0.0:
        x = np.where(mask <= eps, -1.0, 1.0)
    elif 1.0 + brightness <= 0.0:
        x = np.where(mask >= 1.0 - eps, 1.0, -1.0)
    elif brightness > 0.0:
        x = np.minimum((x + brightness) / (1.0 - brightness), 1.0)
    else:
        x = np.maximum((x + brightness) / (1.0 + brightness), -1.0)
    return np.clip(((x * e / (1.0 + (e - 1.0) * np.abs(x))) / 2.0 + 0.5) * opacity, 0.0, 1.0).astype(np.float32)


def make_mask(blend: Blend, shape: tuple, drawn: np.ndarray | None = None, scale: float = 1.0, guide: np.ndarray | None = None) -> np.ndarray:
    """The per-pixel opacity (float32 (h, w), 0..1) a module's result is blended in with. `drawn` is the drawn mask already laid out on the picture (or None: no such mask, which
    darktable treats as everywhere, or nowhere when inverted); `scale` is this picture's pixels per pixel of the 1600 wide preview; `guide` is the picture (uint8 RGB) the feathering follows."""
    h, w = shape[:2]
    opacity = max(0.0, min(1.0, blend.opacity / 100.0))
    if blend.mode == UNIFORM:
        return np.full((h, w), opacity, np.float32)
    if drawn is None:
        base = np.full((h, w), 0.0 if blend.invert else 1.0, np.float32)
    else:
        base = (1.0 - drawn) if blend.invert else drawn.astype(np.float32, copy=True)
    mask = base * opacity
    if blend.blur > 0.1:
        sigma = blend.blur * scale
        if sigma >= 0.3:
            mask = cv2.GaussianBlur(mask, (0, 0), sigma)
    if blend.feather > 0.1 and guide is not None:
        radius = max(1, int(2.0 * blend.feather * scale + 0.5))
        luma = cv2.cvtColor(guide, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
        mask = np.clip(guided_filter(luma * 100.0, mask, radius, 1.0), 0.0, 1.0)
    if (abs(blend.contrast) >= 0.01 or abs(blend.brightness) >= 0.01) and opacity > 1e-4:
        mask = tone_curve(mask, blend.contrast, blend.brightness, opacity)
    return mask


def blend_images(base: np.ndarray, result: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """`base` where the mask is 0, `result` where it is 1 and a mixture between (darktable's normal blend), as the same type as `base`."""
    if mask.shape[:2] != base.shape[:2]:
        mask = cv2.resize(mask, (base.shape[1], base.shape[0]), interpolation=cv2.INTER_LINEAR)
    top = 255.0 if base.dtype == np.uint8 else 65535.0
    b = base.astype(np.float32)
    out = b + (result.astype(np.float32) - b) * mask[..., None]
    return np.clip(out + 0.5, 0.0, top).astype(base.dtype)


def mask_overlay(image: np.ndarray, mask: np.ndarray, strength: float = 0.75) -> np.ndarray:
    """darktable's mask display: the picture in grey with the mask laid over it in yellow (uint8 RGB in and out)."""
    grey = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY).astype(np.float32)
    if mask.shape[:2] != grey.shape[:2]:
        mask = cv2.resize(mask, (grey.shape[1], grey.shape[0]), interpolation=cv2.INTER_LINEAR)
    a = (np.clip(mask, 0.0, 1.0) * strength)[..., None]
    yellow = np.array([255.0, 230.0, 0.0], np.float32)
    out = grey[..., None] * (1.0 - a) + yellow * a
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)
