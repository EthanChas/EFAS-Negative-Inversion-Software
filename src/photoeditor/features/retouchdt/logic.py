"""Retouch: darktable's retouch module, ported (src/iop/retouch.c) - numpy and OpenCV, no Qt.

Shapes drawn on the picture (the masks of features/masks) are each given an algorithm and a wavelet scale:

  clone   copy the picture from the shape's *source* (the spot it was dragged to) over the shape
  heal    the same, but the source's detail is fitted to the colours round the shape (heal.py)
  blur    blur what is inside the shape: Gaussian, or bilateral (smooths the lightness but keeps edges)
  fill    paint the shape with a colour (or erase it: black), plus a brightness

and the scale says what they act on: 0 the picture as it is, 1..N one of N wavelet detail layers (dwt.py; fine detail first), and the residual (the blur that is left after N layers) - so
a blemish's texture and its colour can be dealt with apart ("frequency separation"). Layers from `merge_from` on are added together and acted on as one. The picture is worked on as linear
light, the shape's opacity is the one it has in the Retouch group.

What Retouch is told of the picture is in `Context`: the mask of each shape laid on the picture, how far each shape's source is from it, and how big this picture is compared with the scan."""
import copy
import json
import math
from functools import lru_cache
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import bilateral, dwt
from .heal import heal

NONE, CLONE, HEAL, BLUR, FILL = "none", "clone", "heal", "blur", "fill"
ALGORITHMS = (CLONE, HEAL, BLUR, FILL)
GAUSSIAN, BILATERAL = "gaussian", "bilateral"
ERASE, COLOR = "erase", "color"
MAX_SCALES = 15
PREVIEW_LVL_MIN, PREVIEW_LVL_MAX = -3.0, 3.0
MAX_FORMS = 300
HEAL_ITERATIONS = 2000
VIEWS = ("", "scale", "mask", "suppress")     # normal; the wavelet scale being worked on; where the shapes act; the picture without Retouch


def _num(value, low: float, high: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, v)) if math.isfinite(v) else default


def _colour(value) -> list:
    try:
        return [_num(c, -10.0, 10.0, 0.0) for c in list(value)[:3]] + [0.0] * (3 - len(list(value)[:3]))
    except TypeError:
        return [0.0, 0.0, 0.0]


@dataclass
class FormSetting:
    """What one shape does."""
    formid: int
    scale: int = 0                      # 0 the picture, 1..MAX_SCALES a detail layer, num_scales + 1 the residual
    algorithm: str = HEAL
    blur_type: str = GAUSSIAN
    blur_radius: float = 10.0
    fill_mode: str = ERASE
    fill_color: list = field(default_factory=lambda: [0.0, 0.0, 0.0])   # linear light
    fill_brightness: float = 0.0

    def to_dict(self) -> dict:
        return {"formid": self.formid, "scale": self.scale, "algorithm": self.algorithm, "blur_type": self.blur_type, "blur_radius": self.blur_radius, "fill_mode": self.fill_mode,
                "fill_color": list(self.fill_color), "fill_brightness": self.fill_brightness}

    @staticmethod
    def from_dict(d) -> "FormSetting | None":
        if not isinstance(d, dict):
            return None
        try:
            formid = int(d.get("formid"))
        except (TypeError, ValueError):
            return None
        if formid <= 0:
            return None
        return FormSetting(formid, int(_num(d.get("scale"), 0, MAX_SCALES + 1, 0)), d.get("algorithm") if d.get("algorithm") in ALGORITHMS else HEAL,
                           d.get("blur_type") if d.get("blur_type") in (GAUSSIAN, BILATERAL) else GAUSSIAN, _num(d.get("blur_radius"), 0.1, 200.0, 10.0),
                           d.get("fill_mode") if d.get("fill_mode") in (ERASE, COLOR) else ERASE, _colour(d.get("fill_color", [0, 0, 0])), _num(d.get("fill_brightness"), -1.0, 1.0, 0.0))


@dataclass
class Settings:
    """The Retouch module's settings for a photo: its shapes, and what a new one is given."""
    forms: list = field(default_factory=list)      # FormSetting, in the order of the Retouch group
    group: int = 0                                  # the group of the photo's masks that holds Retouch's shapes (their opacity lives there)
    algorithm: str = HEAL                           # for the next shape
    num_scales: int = 0
    curr_scale: int = 0
    merge_from_scale: int = 0
    preview_levels: list = field(default_factory=lambda: [PREVIEW_LVL_MIN, 0.0, PREVIEW_LVL_MAX])
    preview_auto: bool = True                       # the levels for looking at a detail scale are fitted to it (darktable's auto levels button) rather than the ones above
    blur_type: str = GAUSSIAN
    blur_radius: float = 10.0
    fill_mode: str = ERASE
    fill_color: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    fill_brightness: float = 0.0
    max_heal_iter: int = HEAL_ITERATIONS

    def active(self) -> bool:
        return bool(self.forms)

    def form(self, formid: int) -> FormSetting | None:
        return next((f for f in self.forms if f.formid == formid), None)

    def to_dict(self) -> dict:
        return {"forms": [f.to_dict() for f in self.forms], "group": self.group, "algorithm": self.algorithm, "num_scales": self.num_scales, "curr_scale": self.curr_scale,
                "merge_from_scale": self.merge_from_scale, "preview_levels": list(self.preview_levels), "preview_auto": self.preview_auto, "blur_type": self.blur_type, "blur_radius": self.blur_radius,
                "fill_mode": self.fill_mode, "fill_color": list(self.fill_color), "fill_brightness": self.fill_brightness, "max_heal_iter": self.max_heal_iter}

    @staticmethod
    def from_dict(d) -> "Settings":
        if not isinstance(d, dict):
            return Settings()
        forms, seen = [], set()
        for raw in d.get("forms") or []:
            f = FormSetting.from_dict(raw)
            if f is not None and f.formid not in seen and len(forms) < MAX_FORMS:
                seen.add(f.formid)
                forms.append(f)
        num = int(_num(d.get("num_scales"), 0, MAX_SCALES, 0))
        levels = d.get("preview_levels")
        try:
            lv = [_num(levels[0], PREVIEW_LVL_MIN, PREVIEW_LVL_MAX, PREVIEW_LVL_MIN), _num(levels[1], PREVIEW_LVL_MIN, PREVIEW_LVL_MAX, 0.0), _num(levels[2], PREVIEW_LVL_MIN, PREVIEW_LVL_MAX, PREVIEW_LVL_MAX)]
        except (TypeError, IndexError, KeyError):
            lv = [PREVIEW_LVL_MIN, 0.0, PREVIEW_LVL_MAX]
        try:
            group = max(0, int(d.get("group", 0)))
        except (TypeError, ValueError):
            group = 0
        return Settings(forms, group, d.get("algorithm") if d.get("algorithm") in ALGORITHMS else HEAL, num, int(_num(d.get("curr_scale"), 0, MAX_SCALES + 1, 0)),
                        int(_num(d.get("merge_from_scale"), 0, num, 0)), lv, bool(d.get("preview_auto", True)), d.get("blur_type") if d.get("blur_type") in (GAUSSIAN, BILATERAL) else GAUSSIAN,
                        _num(d.get("blur_radius"), 0.1, 200.0, 10.0), d.get("fill_mode") if d.get("fill_mode") in (ERASE, COLOR) else ERASE, _colour(d.get("fill_color", [0, 0, 0])),
                        _num(d.get("fill_brightness"), -1.0, 1.0, 0.0), int(_num(d.get("max_heal_iter"), 1, 100000, HEAL_ITERATIONS)))

    def copy(self) -> "Settings":
        return copy.deepcopy(self)


def is_neutral(d) -> bool:
    return not Settings.from_dict(d).active()


def to_json(d) -> str:
    """The renderer's copy of the settings (so any change of them draws the picture again): JSON, "" when they are all as they start."""
    s = Settings.from_dict(d)
    return json.dumps(s.to_dict(), sort_keys=True, separators=(",", ":")) if s != Settings() else ""


@lru_cache(maxsize=16)
def _from_json(text: str) -> Settings:
    try:
        return Settings.from_dict(json.loads(text))
    except ValueError:
        return Settings()


def from_json(text: str) -> Settings:
    """The settings for the renderer's JSON (cached). Treat it as read-only."""
    return _from_json(text) if text else Settings()


# ------------------------------------------------------------------ the picture, in linear light
_SRGB_TO_LINEAR = None


def to_linear(pixels: np.ndarray) -> np.ndarray:
    global _SRGB_TO_LINEAR
    if _SRGB_TO_LINEAR is None:
        v = np.arange(256, dtype=np.float32) / 255.0
        _SRGB_TO_LINEAR = np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4).astype(np.float32)
    return _SRGB_TO_LINEAR[pixels]


def to_srgb8(linear: np.ndarray) -> np.ndarray:
    v = np.clip(linear, 0.0, 1.0)
    enc = np.where(v <= 0.0031308, v * 12.92, 1.055 * np.power(v, 1.0 / 2.4) - 0.055)
    return np.clip(np.rint(enc * 255.0), 0, 255).astype(np.uint8)


@dataclass
class Context:
    """What Retouch needs to know of the picture it is working on."""
    mask_of: object             # (form id) -> float mask (height, width) laid on this picture, or None
    delta_of: object            # (form id) -> (dx, dy): from the source to the shape, in this picture's pixels, or None
    opacity_of: object          # (form id) -> opacity of the shape in the Retouch group, 0.05..1
    preview_scale: float = 1.0  # this picture's size compared with the scan's (darktable's roi scale / input scale)
    view: str = ""              # one of VIEWS


# ------------------------------------------------------------------ the algorithms, each on the area of one shape
def _bbox(mask: np.ndarray):
    ys, xs = np.nonzero(mask > 0)
    if ys.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _area(bbox, size, dx: int, dy: int, padding: int):
    """The part of the picture both the shape (plus a ring of `padding` pixels) and its source lie in (darktable's rt_intersect_2_rois): (x0, y0, x1, y1), or None when it is too small."""
    h, w = size
    x0, y0 = max(bbox[0] - padding, 0, dx), max(bbox[1] - padding, 0, dy)
    x1, y1 = min(bbox[2] + padding, w, w + dx), min(bbox[3] + padding, h, h + dy)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    return x0, y0, x1, y1


def _mix(dest: np.ndarray, patch: np.ndarray, f: np.ndarray) -> np.ndarray:
    """darktable's rt_copy_image_masked: the patch over the destination where f is."""
    return dest * (1.0 - f[..., None]) + patch * f[..., None]


def _blur_area(patch: np.ndarray, kind: str, sigma: float) -> np.ndarray:
    if kind == BILATERAL:
        lab = bilateral.rgb_to_lab(patch)
        return bilateral.lab_to_rgb(bilateral.bilateral_lightness(lab, sigma)).astype(np.float32)
    return cv2.GaussianBlur(np.ascontiguousarray(patch), (0, 0), sigma, borderType=cv2.BORDER_CONSTANT)


def process_form(layer: np.ndarray, setting: FormSetting, mask: np.ndarray, opacity: float, delta, preview_scale: float, max_heal_iter: int) -> bool:
    """One shape's algorithm on one layer (changed in place). True when something was done."""
    algo = setting.algorithm
    box = _bbox(mask)
    if box is None:
        return False
    size = layer.shape[:2]
    dx = dy = 0
    if algo in (CLONE, HEAL):
        if delta is None:
            return False
        dx, dy = int(round(delta[0])), int(round(delta[1]))      # whole pixels (darktable cuts the fraction off; rounding keeps the copy on the source that is drawn)
        if dx == 0 and dy == 0:
            return False
    area = _area(box, size, dx, dy, 1 if algo == HEAL else 0)
    if area is None:
        return False
    x0, y0, x1, y1 = area
    f = (mask[y0:y1, x0:x1] * opacity).astype(np.float32)
    dest = layer[y0:y1, x0:x1]
    if algo == CLONE:
        source = layer[y0 - dy:y1 - dy, x0 - dx:x1 - dx].copy()          # copied first: the shape may lie over its own source
        layer[y0:y1, x0:x1] = _mix(dest, source, f)
    elif algo == HEAL:
        source = layer[y0 - dy:y1 - dy, x0 - dx:x1 - dx].copy()
        healed = heal(source, dest.copy(), mask[y0:y1, x0:x1], max_heal_iter)
        layer[y0:y1, x0:x1] = _mix(dest, healed, f)
    elif algo == BLUR:
        if abs(setting.blur_radius) <= 0.1:
            return False
        sigma = setting.blur_radius * preview_scale
        layer[y0:y1, x0:x1] = _mix(dest, _blur_area(dest.copy(), setting.blur_type, sigma), f)
    else:
        base = setting.fill_brightness if setting.fill_mode == ERASE else None
        colour = np.full(3, setting.fill_brightness, np.float32) if base is not None else np.asarray(setting.fill_color[:3], np.float32) + setting.fill_brightness
        layer[y0:y1, x0:x1] = _mix(dest, np.broadcast_to(colour, dest.shape), f)
    return True


# ------------------------------------------------------------------ the preview of a wavelet scale
def _lab(rgb: np.ndarray) -> np.ndarray:
    xyz = (rgb.astype(np.float64) @ bilateral._TO_XYZ.T) / bilateral._WHITE
    f = np.where(xyz > bilateral._EPS, np.cbrt(xyz), (bilateral._KAPPA * xyz + 16.0) / 116.0)   # (signed, as darktable's: a detail layer has negative values)
    return np.stack([116.0 * f[..., 1] - 16.0, 500.0 * (f[..., 0] - f[..., 1]), 200.0 * (f[..., 1] - f[..., 2])], axis=-1)


def adjust_levels(layer: np.ndarray, levels) -> np.ndarray:
    """darktable's rt_adjust_levels: the lightness of a layer put through the preview's black / middle / white levels, so a detail layer (which is mostly zero) can be seen."""
    left, middle, right = (float(v) for v in levels)
    if left == PREVIEW_LVL_MIN and middle == 0.0 and right == PREVIEW_LVL_MAX:
        return layer
    delta = (right - left) / 2.0
    mid = left + delta
    in_inv_gamma = 10.0 ** ((middle - mid) / delta)
    lab = _lab(layer)
    l_in = lab[..., 0] / 100.0
    percentage = np.clip((l_in - left) / (right - left), 0.0, None)
    lab[..., 0] = np.where(l_in <= left, 0.0, 100.0 * np.power(percentage, in_inv_gamma))
    return bilateral.lab_to_rgb(lab).astype(np.float32)


def auto_levels(layer: np.ndarray, current=None) -> list:
    """darktable's rt_process_stats and rt_clamp_minmax: levels that fit the layer shown (the lightness's lowest, mean and highest)."""
    l = _lab(layer)[..., 0] / 100.0
    levels = [float(l.min()), float(l.mean()), float(l.max())]
    old = list(current) if current is not None else list(levels)
    if (old[0] != levels[0] or old[2] != levels[2]) and old[1] == levels[1] and old[2] != old[0]:
        left, right = max(levels[0], PREVIEW_LVL_MIN), min(levels[2], PREVIEW_LVL_MAX)
        levels[1] = left + (right - left) * (old[1] - old[0]) / (old[2] - old[0])
        levels[0], levels[2] = left, right
    if levels == [0.0, 0.0, 0.0]:
        levels = [-1.5, 0.0, 1.5]
    if levels[2] < levels[0] + 0.1:
        levels[2] = levels[0] + 0.1
    if levels[1] < levels[0] + 0.05:
        levels[1] = levels[0] + 0.05
    if levels[1] > levels[2] - 0.05:
        levels[1] = levels[2] - 0.05
    left, right = max(levels[0], PREVIEW_LVL_MIN), min(levels[2], PREVIEW_LVL_MAX)
    pct = (levels[1] - levels[0]) / (levels[2] - levels[0])
    return [left, left + (right - left) * pct, right]


# ------------------------------------------------------------------ the module
def process(pixels: np.ndarray, s: Settings, ctx: Context) -> np.ndarray:
    """The picture (uint8, height x width x 3) with Retouch applied; the same array when there is nothing to do."""
    if ctx.view == "suppress" or (not s.forms and ctx.view != "scale"):    # (a wavelet scale can be looked at before there is a shape on it)
        return pixels
    h, w = pixels.shape[:2]
    ps = ctx.preview_scale if ctx.preview_scale > 0 else 1.0
    view_scale = s.curr_scale if ctx.view == "scale" else 0
    scales = min(s.num_scales, dwt.scales_for(w, h, ps))
    masks: dict[int, np.ndarray | None] = {}

    def mask(formid: int):
        if formid not in masks:
            m = ctx.mask_of(formid)
            masks[formid] = None if m is None else np.asarray(m, np.float32)
        return masks[formid]

    done = {"any": False}

    def forms(layer: np.ndarray, scale: int) -> None:
        """darktable's rt_process_forms: the shapes that belong to this layer."""
        if s.merge_from_scale == 0 and view_scale > 0 and scale != view_scale and scale != 0:
            return
        if scale > scales + 1:
            return
        if scales < s.num_scales and view_scale == 0 and scale == scales + 1:
            scale = s.num_scales + 1        # the residual of a picture that takes fewer scales than were asked for
        for setting in s.forms:
            if setting.scale != scale:
                continue
            m = mask(setting.formid)
            if m is None or m.shape[:2] != (h, w):
                continue
            delta = ctx.delta_of(setting.formid) if setting.algorithm in (CLONE, HEAL) else None
            if process_form(layer, setting, m, ctx.opacity_of(setting.formid), delta, ps, s.max_heal_iter):
                done["any"] = True

    linear = to_linear(pixels).astype(np.float32)
    result, _ = dwt.decompose(linear, s.num_scales, forms, view_scale, s.merge_from_scale, ps)
    if view_scale > 0 and view_scale < scales + 1:
        result = adjust_levels(result, auto_levels(result) if s.preview_auto else s.preview_levels)
    if ctx.view == "mask":
        return _show_shapes(to_srgb8(result), s, ctx, mask)
    if view_scale == 0 and not done["any"]:
        return pixels
    return to_srgb8(result)


def _show_shapes(image: np.ndarray, s: Settings, ctx: Context, mask) -> np.ndarray:
    """darktable's "display mask": a yellow wash where the shapes of the scale being worked on act."""
    wash = np.zeros(image.shape[:2], np.float32)
    for setting in s.forms:
        if setting.scale != s.curr_scale:
            continue
        m = mask(setting.formid)
        if m is not None and m.shape == wash.shape:
            wash = np.maximum(wash, m * ctx.opacity_of(setting.formid))
    out = image.astype(np.float32)
    out = out * (1.0 - 0.7 * wash[..., None]) + np.array([255.0, 214.0, 0.0], np.float32) * (0.7 * wash[..., None])
    return np.clip(out, 0, 255).astype(np.uint8)
