"""Alternative export outputs for finishing a conversion elsewhere: flat, linear light and density (log). All are 16-bit TIFF. Numpy and OpenCV only, no Qt/UI.

  flat     the conversion alone: inverted and framed (crop, rotation, straightening), with none of the exposure, tone, colour, sharpening or finishing
           edits, in the same display encoding as a standard export. For grading in other software.
  linear   the flat result converted to linear light (the sRGB transfer function undone), so values are proportional to light. An estimate: the standard
           conversion's output is assumed to be sRGB-encoded.
  density  the negative's density above its film base, scaled so the code 65535 is DENSITY_RANGE density and 0 is the film base. Not a picture: a measurement.
"""

import numpy as np

KINDS = ("standard", "flat", "linear", "density")
KIND_LABELS = {
    "standard": "Standard (as edited)",
    "flat": "Flat: conversion only (16-bit TIFF)",
    "linear": "Linear light (16-bit TIFF)",
    "density": "Density, log (16-bit TIFF)",
}
KIND_NOTES = {
    "standard": "",
    "flat": "The inverted picture with crop and rotation but none of your tone, colour, sharpening or finishing edits, at 16 bits, for grading elsewhere. "
            "Your Color Trim (the red/green/blue inversion trim) is kept: it is part of getting a neutral conversion.",
    "linear": "The flat conversion in linear light (values proportional to light), at 16 bits. EFAS assumes its output is sRGB-encoded, so this is an estimate. "
              "With the curve-informed method it is the reconstructed relative exposure.",
    "density": "The negative's density above its film base, not a picture: code 0 is the film base and 65535 is 4.0 density, so one code step is 0.00006. "
               "Needs a RAW file (or a 16-bit linear scan) and, for the best result, a sampled film base.",
}
SUFFIX = {"standard": "", "flat": "_flat", "linear": "_linear", "density": "_density"}
DENSITY_RANGE = 4.0
CV2_COMPRESSION = {"none": 1, "lzw": 5, "zip": 8, "packbits": 32773}
_EOTF_LUT: np.ndarray | None = None


def srgb_eotf_lut() -> np.ndarray:
    """A 65536-entry table: a 16-bit sRGB-encoded code to the 16-bit linear-light code."""
    global _EOTF_LUT
    if _EOTF_LUT is None:
        a = np.arange(65536, dtype=np.float64) / 65535.0
        lin = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
        _EOTF_LUT = np.round(lin * 65535.0).astype(np.uint16)
    return _EOTF_LUT


def to_linear16(encoded: np.ndarray) -> np.ndarray:
    """A 16-bit sRGB-encoded picture as a 16-bit linear-light picture."""
    return np.take(srgb_eotf_lut(), np.asarray(encoded, dtype=np.uint16))


def density_code(delta_density: np.ndarray, density_range: float = DENSITY_RANGE) -> np.ndarray:
    """Density above base as 16-bit codes: 0 at the film base (and below), 65535 at `density_range`."""
    return np.round(np.clip(np.asarray(delta_density, dtype=np.float64) / density_range, 0.0, 1.0) * 65535.0).astype(np.uint16)


def density_from_code(code: np.ndarray, density_range: float = DENSITY_RANGE) -> np.ndarray:
    return np.asarray(code, dtype=np.float64) / 65535.0 * density_range


def resize16(pixels: np.ndarray, size: tuple[int, int], resample: str = "lanczos") -> np.ndarray:
    """Resize a 16-bit picture to (w, h) without leaving 16 bits."""
    import cv2

    h, w = pixels.shape[:2]
    if (w, h) == tuple(size):
        return pixels
    shrinking = size[0] * size[1] < w * h
    flag = cv2.INTER_AREA if shrinking and resample != "bilinear" else {"lanczos": cv2.INTER_LANCZOS4, "bicubic": cv2.INTER_CUBIC, "bilinear": cv2.INTER_LINEAR}.get(resample, cv2.INTER_LANCZOS4)
    return cv2.resize(np.ascontiguousarray(pixels), tuple(size), interpolation=flag)


def write_tiff16(pixels: np.ndarray, dest: str, compression: str = "lzw", dpi: int = 300, icc: bytes | None = None) -> tuple[int, int]:
    """Write a 16-bit RGB picture as a TIFF (atomically); returns (w, h). With an ICC profile to carry it is written with tifffile, otherwise with OpenCV."""
    import os

    import cv2

    if pixels.dtype != np.uint16 or pixels.ndim != 3 or pixels.shape[2] != 3:
        raise ValueError("a 16-bit RGB picture is needed")
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmp = dest + ".part.tif"
    if icc:
        return _write_tiff16_tags(pixels, dest, tmp, compression, dpi, icc)
    try:
        ok = cv2.imwrite(tmp, np.ascontiguousarray(pixels[..., ::-1]), [
            cv2.IMWRITE_TIFF_COMPRESSION, CV2_COMPRESSION.get(compression, 5), cv2.IMWRITE_TIFF_XDPI, int(dpi), cv2.IMWRITE_TIFF_YDPI, int(dpi),
        ])
        if not ok:
            raise OSError("the TIFF could not be written")
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return pixels.shape[1], pixels.shape[0]


def _write_tiff16_tags(pixels: np.ndarray, dest: str, tmp: str, compression: str, dpi: int, icc: bytes | None) -> tuple[int, int]:
    """The tifffile route: 16-bit RGB with the sRGB profile tag (34675) and a resolution. Compression falls back to zlib when LZW needs a library that is not installed."""
    import os

    import tifffile

    extra = []
    if icc:
        extra.append((34675, "B", len(icc), icc, True))
    names = {"none": None, "lzw": "lzw", "zip": "adobe_deflate", "packbits": "packbits"}
    wanted = names.get(compression, "lzw")
    try:
        for choice in dict.fromkeys([wanted, "adobe_deflate", None]):
            try:
                tifffile.imwrite(tmp, np.ascontiguousarray(pixels), photometric="rgb", compression=choice, resolution=(int(dpi), int(dpi)), resolutionunit="INCH", extratags=extra)
                break
            except (ValueError, ImportError, KeyError):
                continue
        else:
            raise OSError("the TIFF could not be written")
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return pixels.shape[1], pixels.shape[0]
