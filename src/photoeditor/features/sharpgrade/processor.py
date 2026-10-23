"""Reading a frame in for grading: small, because the grade is made at 700 pixels anyway. Thin I/O around logic.py."""

import cv2
import numpy as np
import rawpy
from PIL import Image

from ..open_image.logic import is_raw
from .logic import OVERLAY_MAX_DIM


def load_for_grading(path: str, max_dim: int = OVERLAY_MAX_DIM) -> np.ndarray:
    """RGB uint8 of `path`, at most `max_dim` on its long side (a RAW is decoded at half size, with the camera's own white balance and no brightening: a negative is graded as it is)."""
    if is_raw(path):
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True, half_size=True, output_bps=8)
    else:
        with Image.open(path) as img:
            rgb = np.asarray(img.convert("RGB"))
    h, w = rgb.shape[:2]
    if max(h, w) > max_dim:
        k = max_dim / max(h, w)
        rgb = cv2.resize(rgb, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(rgb)
