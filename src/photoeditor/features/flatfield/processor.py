"""Thin I/O wrapper around logic.py - decodes reference/roll frames."""

import numpy as np
import rawpy
from PIL import Image

from ..open_image.logic import is_raw
from ..open_image.processor import load_image_rgb
from .logic import POOL_MIN_FRAMES, gain_from_map, pool_reference_from_frames, reference_map

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


def reference_from_file(path: str) -> np.ndarray:
    """The small linear reference map of one dedicated reference shot (a scan of the bare light)."""
    return reference_map(load_image_rgb(path))


def gain_from_reference(path: str, method: str = "efas") -> np.ndarray:
    """A gain map from one dedicated reference shot (a scan of the bare light)."""
    return gain_from_map(reference_from_file(path), method)


def reference_from_roll(paths: list[str], progress=None, cancelled=None):
    """The small linear reference map pooled from every frame in paths (None if cancelled)."""
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
    return pool_reference_from_frames(frames)


def gain_from_roll(paths: list[str], progress=None, cancelled=None, method: str = "efas"):
    """A gain map pooled from every frame in paths."""
    ref = reference_from_roll(paths, progress, cancelled)
    return None if ref is None else gain_from_map(ref, method)
