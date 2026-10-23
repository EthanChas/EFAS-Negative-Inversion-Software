"""Grain Sharpening: sharpen the film's grain itself - numpy and OpenCV only, no Qt.

A camera scan of a negative often shows the grain soft: the lens, the sensor's own filter and the demosaicing all blur a texture that is only a pixel or two wide (the Grain Report says
how wide it is in your scan). Sharpening, as a tool, works on the *picture's* detail and is set to leave the grain alone (its Wavelet method says so). This module is the other way
round: it takes the grain that is already in the scan and makes it crisper, by raising the contrast of the texture at the size of the grain and nothing else.

    Amount     how much crisper the grain is made (0 = off)
    Size       the grain's width in scan pixels (the Grain Report's number; 1 to 2 for most camera scans)
    Midtones   0 = every tone alike, 1 = only the midtones, leaving the deepest shadows and the highlights as they were

It does not make grain where there is none, and it cannot show detail the capture did not record: a texture that is a flat grey in the scan stays a flat grey. It works on lightness only
(the colour of every pixel is kept), and the boost to any one pixel is limited so a hard edge is not given a halo. Size is in pixels of the *scan*: on the editing preview, which is the scan
made smaller, the grain is below a pixel and nothing shows, so the effect is seen from 100% zoom up and in the export, which are made from the scan itself."""
import math

import numpy as np

from ..lut.strips import run_strips
from ..sharpening.logic import _from_lab, _to_lab

KEYS = ("gs_amount", "gs_size", "gs_midtones")
DEFAULTS = {"gs_amount": 0.0, "gs_size": 1.2, "gs_midtones": 0.5}
SIZE_RANGE = (0.6, 4.0)
LIVE = "grainsharp"            # its name among the modules a preview may leave out (see render.py)
GAIN = 1.5                     # Amount 1 raises the contrast of the grain band to this much more than it was (so 2.5 times)
LIMIT = 3.0                    # lightness units: the most the band can add to one pixel before it is eased off, so hard edges are not given halos
LOW_RATIO, HIGH_RATIO = 0.5, 1.6   # the grain band is what is left between a blur of Size x 0.5 and one of Size x 1.6
MIN_SIGMA = 0.35               # a blur narrower than this is the picture itself: nothing to separate, so nothing is done
MIDTONE_CENTRE, MIDTONE_WIDTH = 50.0, 32.0   # lightness of the tones the Midtones slider favours, and how wide that is


def is_neutral(values: dict | None) -> bool:
    return float((values or {}).get("gs_amount", 0.0)) <= 1e-9


def band_sigmas(size: float, scale: float = 1.0) -> tuple[float, float]:
    """(the narrow and the wide blur, in pixels of the picture being worked on) for a grain of `size` scan pixels, where `scale` is picture pixels per scan pixel."""
    s = float(np.clip(size, *SIZE_RANGE)) * float(scale)
    return LOW_RATIO * s, HIGH_RATIO * s


def _blur(chan: np.ndarray, sigma: float) -> np.ndarray:
    import cv2

    r = max(1, int(math.ceil(3.0 * sigma)))
    return cv2.GaussianBlur(chan, (2 * r + 1, 2 * r + 1), sigma, borderType=cv2.BORDER_REFLECT_101)


def _body(strip: np.ndarray, amount: float, s_lo: float, s_hi: float, midtones: float) -> np.ndarray:
    l_chan, a, b = _to_lab(strip)
    band = _blur(l_chan, s_lo) - _blur(l_chan, s_hi)
    band = np.float32(LIMIT) * np.tanh(band / np.float32(LIMIT))
    tones = np.exp(-(((l_chan - np.float32(MIDTONE_CENTRE)) / np.float32(MIDTONE_WIDTH)) ** 2))
    weight = (np.float32(1.0) - np.float32(midtones)) + np.float32(midtones) * tones
    l_new = np.clip(l_chan + np.float32(amount * GAIN) * weight * band, 0.0, 100.0)
    return _from_lab(l_new, a, b)


def apply_grain_sharpening(pixels: np.ndarray, values: dict | None, scale: float = 1.0) -> np.ndarray:
    """The picture (uint8 RGB) with its grain sharpened by `values`; `scale` is the picture's pixels per scan pixel (1 for the scan itself, less for a smaller preview of it)."""
    if is_neutral(values):
        return pixels
    amount = float(np.clip(values.get("gs_amount", 0.0), 0.0, 1.0))
    s_lo, s_hi = band_sigmas(values.get("gs_size", DEFAULTS["gs_size"]), scale)
    if s_lo < MIN_SIGMA:
        return pixels   # the grain is smaller than a pixel of this picture: there is nothing of it to sharpen
    midtones = float(np.clip(values.get("gs_midtones", DEFAULTS["gs_midtones"]), 0.0, 1.0))
    overlap = int(math.ceil(3.0 * s_hi)) + 2
    return run_strips(lambda strip: _body(strip, amount, s_lo, s_hi, midtones), pixels, overlap=overlap)
