"""Thin I/O wrapper around logic.py - decodes reference/roll frames."""

import numpy as np
import rawpy
from PIL import Image

from ..open_image.logic import is_raw
from ..open_image.processor import load_image_rgb
from .logic import POOL_MIN_FRAMES, compute_gain, pool_gain_from_frames

_FRAME_MAX_DIM = 640


def load_small_frame(path: str) -> np.ndarray:
    """uint8 RGB of path at reduced size (a RAW is decoded at half size)."""
    if is_raw(path):
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True, half_size=True, output_bps=8)
        img = Image.fromarray(rgb)
    else:
        img = Image.open(path).convert("RGB")
    img.thumbnail((_FRAME_MAX_DIM, _FRAME_MAX_DIM), Image.Resampling.BILINEAR)
    return np.array(img)


def gain_from_reference(path: str) -> np.ndarray:
    """A gain map from one dedicated reference shot (a scan of the bare light)."""
    return compute_gain(load_image_rgb(path))


def gain_from_roll(paths: list[str], progress=None, cancelled=None):
    """A gain map pooled from every frame in paths."""
    frames = []
    total = len(paths)
    for i, path in enumerate(paths):
        if cancelled is not None and cancelled():
            return None
        try:
            frames.append(load_small_frame(path))
        except Exception:
            pass
        if progress is not None:
            progress(i + 1, total, path)
    if len(frames) < POOL_MIN_FRAMES:
        raise ValueError(f"Auto (Roll) needs at least {POOL_MIN_FRAMES} readable frames; this folder has {len(frames)}.")
    return pool_gain_from_frames(frames)
