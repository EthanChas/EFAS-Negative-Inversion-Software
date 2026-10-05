"""Thin I/O wrapper around logic.py - the boundary where file/RAW decoding happens."""

import numpy as np
import rawpy
from PIL import Image

from .logic import is_raw


def load_image_rgb(path: str) -> np.ndarray:
    """Decode `path` (standard image or RAW) to an HxWx3 uint8 RGB array."""
    if is_raw(path):
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=False, output_bps=8)
        return rgb
    img = Image.open(path).convert("RGB")
    return np.array(img)


def make_preview_rgb(pixels: np.ndarray, max_dim: int = 1600) -> np.ndarray:
    """A downsampled copy to run interactive editing math against instead
    of the (often much larger) original - a full-resolution RAW is tens of
    millions of pixels, and even simple per-pixel math plus a couple of
    histograms over that is slow enough to visibly stall the UI on every
    slider tick. Every photo editor uses this same proxy/preview approach
    for live adjustment, reserving full resolution for export."""
    h, w = pixels.shape[:2]
    if max(h, w) <= max_dim:
        return pixels
    scale = max_dim / max(h, w)
    new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
    return np.array(Image.fromarray(pixels).resize(new_size, Image.Resampling.LANCZOS))
