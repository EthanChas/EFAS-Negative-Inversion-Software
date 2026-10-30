"""The data behind the histogram's Curve view: the conversion's paper curve (the negative's density in, the print's level out) with the negative's own density histogram under it - numpy only,
no Qt. After NegPy's Analysis chart (an H&D / paper curve over the density histogram).

`build` takes what the renderer fed the conversion's table (the scan's codes or, for the density conversions, its density image) and the table itself, and answers on one axis, the
negative's density D (0 is clear film, a dense negative is further right): the curve of each colour (the print level 0..255 at that density) and how many pixels lie at each density."""
import numpy as np

D_MAX = 3.0                  # the right edge of the chart, in density (the film base, with the dyes' crosstalk taken out, is near 0 and a dense highlight is about 2.5)
POINTS = 256                 # points of each curve
BINS = 128                   # bins of the density histogram
_MAX_SAMPLES = 250_000
_CODE_FLOOR = 1e-4           # a scan code of 0 is as dense as the chart goes


def _sample(codes: np.ndarray) -> np.ndarray:
    flat = codes.reshape(-1, codes.shape[-1])
    if flat.shape[0] > _MAX_SAMPLES:
        flat = flat[:: -(-flat.shape[0] // _MAX_SAMPLES)]
    return flat


def build(codes: np.ndarray, lut: np.ndarray, in_density: bool, scale: float) -> dict | None:
    """`codes`: HxWx3 the table was read with (uint8 or uint16); `lut`: the (3, N) table of print levels 0..255; `in_density`: whether the codes are density * `scale` (else they are the
    scan's own codes, the more light the higher). -> {"density": D at each curve point, "curve": (3, POINTS) print levels, "hist": (4, BINS) counts [R, G, B, mean], "range": (low, high)}
    or None when there is nothing to draw."""
    if codes is None or lut is None or codes.ndim != 3 or codes.shape[2] != 3 or lut.ndim != 2 or lut.shape[0] != 3:
        return None
    n = lut.shape[1]
    top = 255.0 if codes.dtype == np.uint8 else 65535.0
    d = np.linspace(0.0, D_MAX, POINTS)
    if in_density:
        index = np.clip(np.rint(d * scale), 0, n - 1).astype(np.int64)
    else:
        index = np.clip(np.rint(np.power(10.0, -d) * (n - 1)), 0, n - 1).astype(np.int64)
    curve = np.stack([np.asarray(lut[c][index], dtype=np.float32) for c in range(3)])
    sample = _sample(codes).astype(np.float32)
    if in_density:
        dens = sample / np.float32(scale)      # (a density image is always 16-bit)
    else:
        dens = -np.log10(np.maximum(sample / np.float32(top), _CODE_FLOOR))
    edges = np.linspace(0.0, D_MAX, BINS + 1)
    hist = np.stack([np.histogram(np.clip(dens[:, c], 0.0, D_MAX), bins=edges)[0] for c in range(3)] + [np.histogram(np.clip(dens.mean(axis=1), 0.0, D_MAX), bins=edges)[0]]).astype(np.float64)
    if hist.max() <= 0:
        return None
    lum = dens.mean(axis=1)
    return {"density": d, "curve": curve, "hist": hist, "range": (float(np.percentile(lum, 0.5)), float(np.percentile(lum, 99.5)))}
