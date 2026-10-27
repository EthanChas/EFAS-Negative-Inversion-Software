"""Reading a frame in for grading: small, because the grade is made at 700 pixels anyway. Thin I/O around logic.py."""

import cv2
import numpy as np
import rawpy
from PIL import Image

from ..open_image.logic import is_raw


def load_for_grading(path: str, max_dim: int | None = None) -> np.ndarray:
    """RGB uint8 of `path` at full resolution (a RAW is decoded at full size, with the camera's own white balance and no brightening: a negative is graded as it is), or at most `max_dim` on its
    long side when one is given. The grade and the overlay are made from the full picture and take their own sizes from it."""
    if is_raw(path):
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True, half_size=max_dim is not None, output_bps=8)
    else:
        with Image.open(path) as img:
            rgb = np.asarray(img.convert("RGB"))
    h, w = rgb.shape[:2]
    if max_dim is not None and max(h, w) > max_dim:
        k = max_dim / max(h, w)
        rgb = cv2.resize(rgb, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(rgb)
