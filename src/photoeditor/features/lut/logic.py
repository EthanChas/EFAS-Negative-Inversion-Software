"""Per-channel 0-255 lookup-table helpers - numpy + Pillow only, no Qt/UI imports.

Exposure, white balance offsets, the negative inversion and the tone curve
are all pointwise per-channel maps, so instead of running each one over every
pixel (several full-image float passes per slider tick), they're run once over
a 256-entry "ramp" image and composed into a single (3, 256) table, which
then costs one fast pass over the real image."""

import numpy as np
from PIL import Image


def identity_ramp() -> np.ndarray:
    """A (1, 256, 3) uint8 image where every channel holds 0..255 - feeding it
    through any pointwise-per-channel stage yields that stage's own lookup
    table, with exactly the same rounding as running it on a real image."""
    return np.repeat(np.arange(256, dtype=np.uint8)[None, :, None], 3, axis=2)


def ramp_to_lut(ramp: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(ramp[0].T)  # (3, 256)


def is_identity(lut: np.ndarray) -> bool:
    return bool(np.array_equal(lut, np.broadcast_to(np.arange(256, dtype=np.uint8), (3, 256))))


def apply_channel_lut(pixels: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """Applies a (3, 256) uint8 table, one curve per channel. Pillow's point()
    does the whole thing in C - several times faster than numpy fancy
    indexing per channel, and bit-identical."""
    if pixels.size == 0:
        return pixels
    out = Image.fromarray(np.ascontiguousarray(pixels)).point(lut.reshape(-1).tolist())
    return np.asarray(out)
