"""Blending modules through masks while a picture is rendered (the render side of each module's Mask box; see features/masks).

A MaskBlender is made once per render. It knows which modules are blended (`params.blends`), the photo's drawn masks (`params.masks_json`), and how the picture was moved about on its way
to the stage a module works at: a mask is drawn on the untouched scan's frame, then put through the same straightening, distortion, keystone, rotation and flips as the picture, and (for the
stages after the crop) cropped with it, so it lies on the same part of the picture as the module's result. `blend(key, before, after)` is darktable's normal blend of what a module made
through its mask."""
import numpy as np

from ..features.geometry.logic import apply_crop
from ..features.masks import blend as B
from ..features.masks import raster
from ..features.masks import state as S
from ..features.instances import logic as I

# the modules whose result is made one step at a time (and so can be blended) while the tone and colour of the picture are made, in the order they act
RAMP_KEYS = ("color", "exposure", "contrast", "printresponse")
PIXEL_KEYS = ("color", "exposure", "contrast", "printresponse", "denoise", "localcontrast", "shadows_highlights", "tonecurve", "lablook", "colormixer", "colortoning")
AFTER_KEYS = ("sharpening", "grainsharp")            # on the whole scan, after the colour, before the crop
CROPPED_KEYS = ("edgecolor", "halation")             # on the cropped picture
BLENDABLE = PIXEL_KEYS + AFTER_KEYS + CROPPED_KEYS


class MaskBlender:
    def __init__(self, params, frame_hw: tuple, geometry=None, rect=None, scale: float = 1.0):
        """`frame_hw` is the (height, width) of the untouched scan's frame the masks are drawn on; `geometry(mask)` carries a mask the way the picture was carried (the identity when none was
        needed); `rect` is the crop; `scale` is this picture's pixels per pixel of the 1600 wide preview."""
        self.blends = {k: b for k, b in S.blends_from_tuple(params.blends).items() if I.split_key(k)[0] in BLENDABLE}
        self.instances = {k: v for k, v in I.thawed(getattr(params, "instances", ())).items() if k in BLENDABLE}   # the copies of modules that are on: {module key: [(id, {field: value}), ...]}
        self.masks = S.parse_masks(params.masks_json)
        self.frame_hw = frame_hw
        self.geometry = geometry or (lambda m: m)
        self.rect = rect
        self.scale = scale
        self._drawn: dict = {}

    def masked(self, key: str) -> bool:
        return key in self.blends

    def staged(self) -> bool:
        """True when a module of the tone and colour stage is blended: that stage is then made one module at a time."""
        return any(I.split_key(k)[0] in PIXEL_KEYS for k in self.blends) or any(k in PIXEL_KEYS for k in self.instances)

    def any(self) -> bool:
        return bool(self.blends) or bool(self.instances)

    def _mask(self, mask_id: int, cropped: bool) -> np.ndarray | None:
        key = (mask_id, cropped)
        if key not in self._drawn:
            h, w = self.frame_hw
            raw = raster.render_mask(self.masks, mask_id, w, h) if mask_id else None
            laid = self.geometry(raw) if raw is not None else None
            if laid is not None and cropped:
                laid = apply_crop(laid, self.rect)
            self._drawn[key] = laid
        return self._drawn[key]

    def blend(self, key: str, before: np.ndarray, after: np.ndarray, cropped: bool = False) -> np.ndarray:
        """`after` (what the module made of `before`) mixed back into `before` through the module's mask, as the same type; `after` untouched when the module is not blended."""
        b = self.blends.get(key)
        if b is None or after is before:
            return after
        drawn = self._mask(b.mask_id, cropped) if b.uses_mask() else None
        guide = before if (before.dtype == np.uint8 and before.ndim == 3 and b.feather > 0.1) else None
        mask = B.make_mask(b, before.shape, drawn, self.scale, guide)
        return B.blend_images(before, after, mask)

    def form_mask(self, form_id: int) -> np.ndarray | None:
        """A single shape's mask laid on the picture before its crop (Retouch's): the shape's own falloff, as the picture was moved about."""
        form = self.masks.get(form_id)
        if form is None or form.type == "group":
            return None
        mask = self._mask(form_id, False)
        return None if mask is None else mask.astype(np.float32, copy=False)

    def drawn_mask(self, mask_id: int, cropped: bool = True) -> np.ndarray | None:
        """A mask laid on the picture (cropped as it is), for showing it."""
        return self._mask(mask_id, cropped)
