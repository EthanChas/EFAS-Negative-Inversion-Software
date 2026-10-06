"""Thin I/O wrapper around logic.py - the boundary where file/RAW decoding happens."""

import os

import numpy as np
import rawpy
from PIL import Image

from ..lut.logic import to_uint8  # noqa: F401  (re-exported: the 8-bit copy of a decoded picture)
from ..settings import logic as settings
from .logic import is_raw

_SIXTEEN_BIT_FILES = (".tif", ".tiff", ".png")


def _load_16bit_file(path: str):
    """A 16-bit TIFF or PNG (a scanner's output, usually) as an HxWx3 uint16 array, or None when the file is not one."""
    if os.path.splitext(path)[1].lower() not in _SIXTEEN_BIT_FILES:
        return None
    try:
        import cv2

        data = cv2.imread(path, cv2.IMREAD_UNCHANGED | cv2.IMREAD_ANYDEPTH | cv2.IMREAD_ANYCOLOR)
    except Exception:
        return None
    if data is None or data.dtype != np.uint16:
        return None
    if data.ndim == 2:
        data = np.repeat(data[:, :, None], 3, axis=2)
    elif data.shape[2] == 4:
        data = data[:, :, :3]
    return np.ascontiguousarray(data[:, :, ::-1])  # OpenCV reads BGR


def load_image_rgb(path: str) -> np.ndarray:
    """Decode `path` (standard image or RAW) to an HxWx3 RGB array: uint16 for a RAW file or a 16-bit TIFF/PNG (keeping every level the
    sensor or scanner recorded - the edit pipeline stretches a negative's narrow range, and 8 bits would show gaps), uint8 for the rest."""
    if is_raw(path):
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(
                use_camera_wb=True, no_auto_bright=not settings.get("raw_auto_bright"), output_bps=16,
                demosaic_algorithm=getattr(rawpy.DemosaicAlgorithm, settings.DEMOSAIC_CHOICES[settings.get("raw_demosaic")][1]),
            )
        return rgb
    deep = _load_16bit_file(path)
    if deep is not None:
        return deep
    img = Image.open(path).convert("RGB")
    return np.array(img)


def make_preview_rgb(pixels: np.ndarray, max_dim: int = 1600) -> np.ndarray:
    """A downsampled copy to run interactive editing math against instead
    of the (often much larger) original - a full-resolution RAW is tens of
    millions of pixels, and even simple per-pixel math plus a couple of
    histograms over that is slow enough to visibly stall the UI on every
    slider tick. Every photo editor uses this same proxy/preview approach
    for live adjustment, reserving full resolution for export. Keeps the
    picture's bit depth."""
    h, w = pixels.shape[:2]
    if max(h, w) <= max_dim:
        return pixels
    scale = max_dim / max(h, w)
    new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
    if pixels.dtype == np.uint8:
        return np.array(Image.fromarray(pixels).resize(new_size, Image.Resampling.LANCZOS))
    import cv2

    return cv2.resize(np.ascontiguousarray(pixels), new_size, interpolation=cv2.INTER_AREA)
