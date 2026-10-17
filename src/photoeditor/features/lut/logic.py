"""Per-channel 0-255 lookup-table helpers - numpy + Pillow only, no Qt/UI imports."""

import numpy as np
from PIL import Image


def identity_ramp() -> np.ndarray:
    """A (1, 256, 3) uint8 image where every channel holds 0..255 - feeding it
    through any pointwise-per-channel stage yields that stage's own lookup
    table, with exactly the same rounding as running it on a real image."""
    return np.repeat(np.arange(256, dtype=np.uint8)[None, :, None], 3, axis=2)


def ramp_to_lut(ramp: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(ramp[0].T)


WIDE_SIZE = 65536


def wide_ramp() -> np.ndarray:
    """A (1, 65536, 3) float32 image holding the 0..255 value of every 16-bit level, for every channel - the wide counterpart of identity_ramp."""
    values = np.arange(WIDE_SIZE, dtype=np.float32) * np.float32(255.0 / 65535.0)
    return np.repeat(values[None, :, None], 3, axis=2)


def wide_ramp_to_lut(ramp: np.ndarray) -> np.ndarray:
    """The finished float ramp as a (3, 65536) uint8 table: the one rounding the whole wide chain gets."""
    return np.ascontiguousarray(np.clip(np.rint(ramp[0].T), 0, 255).astype(np.uint8))


def wide_ramp_to_lut16(ramp: np.ndarray) -> np.ndarray:
    """The finished float ramp as a (3, 65536) uint16 table: the 0-255 values it holds, kept at 16 bits (255 is 65535) instead of rounded to 256 steps."""
    return np.ascontiguousarray(np.clip(np.rint(ramp[0].T * np.float32(65535.0 / 255.0)), 0, 65535).astype(np.uint16))


def apply_wide_lut(pixels16: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """A uint16 picture through a (3, 65536) table -> a picture as deep as the table: uint8 for a uint8 table, uint16 for a uint16 one."""
    try:
        import cv2

        return cv2.LUT(np.ascontiguousarray(pixels16), np.ascontiguousarray(lut.T[None]))
    except Exception:
        out = np.empty(pixels16.shape, dtype=lut.dtype)
        for c in range(3):
            np.take(lut[c], pixels16[..., c], out=out[..., c])
        return out


def to_uint8(pixels: np.ndarray) -> np.ndarray:
    """An 8-bit copy of a picture (a uint8 one is returned as it is): 16-bit levels are rounded to the nearest of 256."""
    if pixels.dtype == np.uint8:
        return pixels
    return ((pixels.astype(np.uint32) + 128) // 257).astype(np.uint8)


def is_identity(lut: np.ndarray) -> bool:
    """Whether a (3, 256) uint8 or (3, 65536) uint16 table changes nothing."""
    return bool(np.array_equal(lut, np.broadcast_to(np.arange(lut.shape[-1], dtype=lut.dtype), (3, lut.shape[-1]))))


def apply_channel_lut(pixels: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """Applies a table, one curve per channel: (3, 256) uint8 to an 8-bit picture, or (3, 65536) uint16 to a 16-bit one."""
    if pixels.size == 0:
        return pixels
    if pixels.dtype == np.uint16:
        return apply_wide_lut(pixels, lut)
    out = Image.fromarray(np.ascontiguousarray(pixels)).point(lut.reshape(-1).tolist())
    return np.asarray(out)
