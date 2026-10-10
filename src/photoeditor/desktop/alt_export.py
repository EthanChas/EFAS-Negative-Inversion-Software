"""The numbers behind the flat, linear and density exports (features/export/kinds.py): the same inversion, framing and crop as the editor, without the edits.

flat16 follows Renderer.render step for step (monochrome, straighten, distortion, rotation, flips, crop, the inversion lookup) but keeps the inversion's
sub-8-bit precision instead of rounding to 8 bits, and leaves out exposure, tone, colour, sharpening, finishing and watermarks.
"""

import numpy as np

from ..features.densitometry.linear import LinearScan
from ..features.geometry.logic import apply_crop, fine_rotate, flip_horizontal, flip_vertical, radial_distort, rotate_quarter_turns
from ..features.negative.logic import apply_channel_offsets, compute_invert_lut, monochrome
from .render import _scale_rect

BLOCK_PIXELS = 1_000_000


def _frame(pixels: np.ndarray, params) -> np.ndarray:
    """The editor's geometry, in its order and with its interpolation."""
    pixels = fine_rotate(pixels, params.fine_rotation)
    pixels = radial_distort(pixels, params.distortion)
    if params.rotation_quarter_turns:
        pixels = rotate_quarter_turns(pixels, params.rotation_quarter_turns)
    if params.flip_h:
        pixels = flip_horizontal(pixels)
    if params.flip_v:
        pixels = flip_vertical(pixels)
    return pixels


def flat16(source: np.ndarray, params, preview_width: int, already_positive: bool = False) -> np.ndarray:
    """The inverted, framed, cropped picture as 16-bit display-encoded values, with none of the creative edits. `already_positive` is for a source that has
    been converted already (the curve-informed method): it is only framed and cropped."""
    pixels = source if source.dtype == np.uint16 else source.astype(np.uint16) * 257
    scale = pixels.shape[1] / preview_width
    if params.film_type == "bw":
        pixels = monochrome(pixels)
    pixels = _frame(pixels, params)
    h, w = pixels.shape[:2]
    rect = _scale_rect(params.crop_rect, scale, w, h)
    out = pixels
    if params.negative_inverted and not already_positive:
        meter_rect = rect if params.metering.rect is None else _scale_rect(params.metering.rect, scale, w, h)
        base = params.film_base
        if base is not None and params.film_type == "bw":
            gray = round(0.299 * base[0] + 0.587 * base[1] + 0.114 * base[2])
            base = (gray, gray, gray)
        lut = compute_invert_lut(pixels, meter_rect, base, params.metering)
        table = apply_channel_offsets(np.ascontiguousarray(lut.T[None]), (params.invert_r, params.invert_g, params.invert_b))[0]
        out = np.empty(pixels.shape, dtype=np.uint16)
        for c in range(3):
            out[..., c] = np.clip(np.round(np.take(table[:, c], pixels[..., c]) * 257.0), 0, 65535)
    return apply_crop(out, rect)


def density16(scan: LinearScan, v_base, params, preview_width: int, density_range: float = 4.0) -> np.ndarray:
    """Density above the film base as 16-bit codes (code 65535 = density_range), framed and cropped like the picture. Computed in row blocks."""
    from ..features.export.kinds import density_code

    v = scan.rgb
    h, w = v.shape[:2]
    floor = np.maximum(np.asarray(scan.info.floor(), dtype=np.float64), 1e-9)
    base = np.asarray(v_base, dtype=np.float64)
    out = np.empty((h, w, 3), dtype=np.uint16)
    rows = max(1, BLOCK_PIXELS // max(w, 1))
    for y in range(0, h, rows):
        block = v[y:y + rows].astype(np.float64)
        out[y:y + rows] = density_code(np.log10(base) - np.log10(np.maximum(block, floor)), density_range)
    if params.film_type == "bw":
        out = np.repeat(np.round(out.mean(axis=2)).astype(np.uint16)[..., None], 3, axis=2)
    scale = w / preview_width
    out = _frame(out, params)
    return apply_crop(out, _scale_rect(params.crop_rect, scale, out.shape[1], out.shape[0]))
