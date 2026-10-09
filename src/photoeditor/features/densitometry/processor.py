"""Decoding a RAW file to linear, normalised sensor values for measurement (docs/scientific-inversion-design.md, section 4.1).

This is separate from the picture decode in open_image/processor.py: no white balance, colour matrix, tone curve or auto-brightness
touches the numbers here.
"""

import numpy as np
import rawpy

from ..open_image.logic import is_raw
from ..settings import logic as settings
from .linear import LinearScan, ScanInfo, from_display_referred

_OB_GUARD = 4


def linear_settings(demosaic: str, user_flip: int | None = None) -> dict:
    """The rawpy settings that keep LibRaw's output linear in the sensor's light. Every one of them undoes a default that would not be."""
    return dict(
        gamma=(1, 1), no_auto_bright=True, bright=1.0, adjust_maximum_thr=0.0, use_camera_wb=False, use_auto_wb=False, user_wb=[1.0, 1.0, 1.0, 1.0],
        output_color=rawpy.ColorSpace.raw, output_bps=16, highlight_mode=rawpy.HighlightMode.Clip,
        demosaic_algorithm=getattr(rawpy.DemosaicAlgorithm, demosaic), user_flip=user_flip,
    )


def optical_black_noise(raw: "rawpy.RawPy", black: list[float], white: float):
    """Read noise per R, G, B channel (as a share of the sensor's range) from the optical-black margin, or None when the file has none."""
    try:
        sizes = raw.sizes
        left = int(sizes.left_margin)
        if left < 2 * _OB_GUARD + 8:
            return None
        full, colors = raw.raw_image, raw.raw_colors
        top = int(sizes.top_margin)
        region = full[top:top + int(sizes.height), _OB_GUARD:left - _OB_GUARD].astype(np.float64)
        pattern = colors[top:top + int(sizes.height), _OB_GUARD:left - _OB_GUARD]
        span = float(white - np.mean(black))
        out = []
        for group in ((0,), (1, 3), (2,)):
            vals = region[np.isin(pattern, group)]
            if vals.size < 200:
                return None
            out.append(float(np.std(vals)) / span)
        return tuple(out)
    except Exception:
        return None


def _saturation_levels(raw: "rawpy.RawPy", black: list[float], white: float):
    """The level at which each of R, G, B really clips: the camera's own figure when the file gives one (it can sit well under the nominal
    white level), else the nominal white level."""
    reported = raw.camera_white_level_per_channel
    if reported is not None and len(reported) >= 3 and all(0 < r <= white for r in reported[:3]):
        r, g, b = float(reported[0]), float(np.mean([reported[1], reported[3] if len(reported) > 3 else reported[1]])), float(reported[2])
        return (r, g, b), True
    return (white, white, white), False


def decode_linear_raw(path: str, user_flip: int | None = None) -> LinearScan:
    """The RAW file as linear values: (N - black) / (saturation - black) per channel, demosaiced, orientation as the picture. 1.0 is sensor white."""
    demosaic = settings.DEMOSAIC_CHOICES[settings.get("raw_demosaic")][1]
    with rawpy.imread(path) as raw:
        black = [float(b) for b in raw.black_level_per_channel]
        white = float(raw.white_level)
        sat, from_camera = _saturation_levels(raw, black, white)
        noise = None
        try:
            noise = optical_black_noise(raw, black, white)
        except Exception:
            noise = None
        rgb16 = raw.postprocess(**linear_settings(demosaic, user_flip))
        colour_desc = raw.color_desc.decode("ascii", "ignore") if isinstance(raw.color_desc, bytes) else str(raw.color_desc)
        colours = raw.raw_colors_visible
        vis = raw.raw_image_visible
        clipped = np.zeros(vis.shape, dtype=bool)
        for chan, group in ((0, (0,)), (1, (1, 3)), (2, (2,))):
            clipped |= np.isin(colours, group) & (vis >= sat[chan] - 1)
        saturated = float(clipped.mean())
    black_rgb = (black[0], (black[1] + black[3]) / 2.0 if len(black) > 3 else black[1], black[2])
    gain = np.array([(white - black_rgb[c]) / (sat[c] - black_rgb[c]) for c in range(3)], dtype=np.float32)
    rgb = rgb16.astype(np.float32) / 65535.0 * gain
    if noise is not None:
        noise = tuple(float(n * (white - np.mean(black)) / (sat[c] - black_rgb[c])) for c, n in enumerate(noise))
    bits = int(np.ceil(np.log2(max(white - float(np.mean(black)), 2.0))))
    steps = (
        f"RAW decoded by LibRaw ({colour_desc} sensor), {demosaic} demosaic",
        f"Black level {', '.join(f'{b:.0f}' for b in black)} subtracted per channel",
        f"Divided by the {'camera-reported ' if from_camera else ''}saturation level ({', '.join(f'{x:.0f}' for x in sat)}) so 1.0 is sensor white",
        "No white balance, colour matrix, tone curve or auto-brightness applied; highlights clipped, not reconstructed",
        "Sensor noise estimated from the optical-black margin" if noise else "No optical-black margin: noise floor comes from the bit depth",
    )
    span = float(np.mean([sat[c] - black_rgb[c] for c in range(3)]))
    info = ScanInfo(
        measured=True, encoding="raw-linear", bit_depth=bits, white=float(np.mean(sat)), black=tuple(black),
        quantisation=1.0 / max(span, 1.0), noise_sigma=noise, saturated_fraction=saturated, steps=steps,
    )
    return LinearScan(rgb, info)


def linear_scan(path: str, preview_rgb, transfer: str) -> LinearScan:
    """RAW files are decoded for measurement; any other picture is linearised from the already-loaded pixels with the assumed transfer function."""
    if is_raw(path):
        return decode_linear_raw(path)
    return from_display_referred(preview_rgb, transfer)
