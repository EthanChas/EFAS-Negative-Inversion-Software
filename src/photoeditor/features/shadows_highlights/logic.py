"""Pure shadows/highlights tonal adjustment - numpy only, no Qt/UI imports.

The old version added the same number to red, green and blue for every pixel of a given brightness. That lifts black (nothing is black any more),
flattens contrast and drains colour, so any use of the sliders looked washed out. This one works by gain instead:

- a brightness curve is built that bends only the shadow or the highlight end - black stays black and white stays white, and the curve never
  runs backwards, so no tones swap places;
- each pixel is then multiplied by (new brightness / old brightness), the same factor on red, green and blue, so its hue and saturation are kept
  and a lifted shadow keeps its colour instead of turning grey;
- a pixel is never pushed past white (the gain is capped so no channel clips), so a bright, saturated colour does not shift hue."""

import numpy as np

from ..lut.strips import run_strips

_LUMA_VEC = np.array((0.299, 0.587, 0.114), dtype=np.float32)
_SHADOW_REACH = 1.2     # stops of gain at full strength at the darkest end
_HIGHLIGHT_REACH = 0.65  # stops of gain at full strength where the highlight curve peaks (three quarters of the way to white)
_TO_255 = np.float32(255.0 / 65535.0)
_TO_WIDE = np.float32(65535.0 / 255.0)


def tone_curve(shadows: float, highlights: float) -> np.ndarray:
    """The new brightness (0-1) for each of the 256 old ones: black and white are fixed, and the curve only ever rises."""
    x = np.arange(256, dtype=np.float64) / 255.0
    y = x.copy()
    if shadows:
        # most of the effect near black, fading to almost nothing by the midtones
        y = y * np.exp2(_SHADOW_REACH * float(shadows) * (1.0 - y) ** 3)
    if highlights:
        w = 9.4815 * y ** 3 * (1.0 - y)  # 0 at black and at white, 1 at three quarters
        if highlights < 0:
            y = y * np.exp2(_HIGHLIGHT_REACH * float(highlights) * w)  # darker highlights
        else:
            y = 1.0 - (1.0 - y) * np.exp2(-_HIGHLIGHT_REACH * float(highlights) * w)  # brighter highlights, measured down from white
    y = np.clip(y, 0.0, 1.0)
    return np.maximum.accumulate(y)


def gain_table(shadows: float, highlights: float) -> np.ndarray:
    """What to multiply a pixel of each brightness (0-255) by."""
    x = np.arange(256, dtype=np.float64) / 255.0
    y = tone_curve(shadows, highlights)
    gain = np.ones(256, dtype=np.float64)
    gain[1:] = y[1:] / x[1:]
    return gain.astype(np.float32)


def adjust_shadows_highlights(pixels: np.ndarray, shadows: float, highlights: float) -> np.ndarray:
    """shadows, highlights in [-1, 1]: positive brightens that tonal range, negative darkens it - a consistent +/- direction for both, rather
    than Lightroom's inverted-feeling "negative highlights to recover them." The pixels are uint8 RGB (or uint16, kept at 16 bits); the result is a new array."""
    if shadows == 0.0 and highlights == 0.0:
        return pixels
    table = gain_table(float(shadows), float(highlights))
    return run_strips(lambda strip: _apply_gain(strip, table), pixels)


def _apply_gain_wide(flat: np.ndarray, table: np.ndarray) -> np.ndarray:
    """The same gain on a 16-bit picture: the brightness is not rounded to one of 256 steps but looked up between two neighbouring entries of the table, and nothing is rounded
    until the end."""
    f = flat.astype(np.float32) * _TO_255   # the 0-255 scale
    luma = np.clip(f @ _LUMA_VEC, 0.0, 255.0)
    i0 = np.minimum(luma.astype(np.int32), 254)
    frac = luma - i0
    gain = table[i0] * (np.float32(1.0) - frac) + table[i0 + 1] * frac
    gain = np.minimum(gain, 255.0 / np.maximum(f.max(axis=1), 1.0))
    return np.clip(f * gain[:, None] * _TO_WIDE + 0.5, 0, 65535).astype(np.uint16)


def _apply_gain(pixels: np.ndarray, table: np.ndarray) -> np.ndarray:
    h, w, _ = pixels.shape
    flat = pixels.reshape(-1, 3)
    if pixels.dtype == np.uint16:
        return _apply_gain_wide(flat, table).reshape(h, w, 3)
    luma = np.rint(flat.astype(np.float32) @ _LUMA_VEC).astype(np.uint8)
    gain = table[luma]
    brightest = flat.max(axis=1).astype(np.float32)
    gain = np.minimum(gain, 255.0 / np.maximum(brightest, 1.0))
    out = flat.astype(np.float32) * gain[:, None]
    return np.clip(out + 0.5, 0, 255).astype(np.uint8).reshape(h, w, 3)
