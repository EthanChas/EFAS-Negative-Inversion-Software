"""Splits an image into horizontal strips processed on a shared thread pool -
numpy ufuncs and Pillow filters release the GIL, so strips genuinely run in
parallel on multiple cores. No Qt/UI imports."""

import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np

_WORKERS = max(1, min(8, (os.cpu_count() or 2)))
_POOL = ThreadPoolExecutor(max_workers=_WORKERS, thread_name_prefix="strips")
_MIN_ROWS_PER_STRIP = 128  # below this, thread hand-off costs more than it saves


def run_strips(fn, pixels: np.ndarray, overlap: int = 0) -> np.ndarray:
    """fn(strip) -> same-shaped uint8 array. overlap is how many extra rows
    each strip reads past its own edges (for neighborhood filters like blur),
    discarded from the result - so strip seams match a single full-image
    call as long as overlap covers the filter's reach."""
    h = pixels.shape[0]
    n = min(_WORKERS, h // _MIN_ROWS_PER_STRIP)
    if n <= 1:
        return fn(pixels)

    bounds = np.linspace(0, h, n + 1).astype(int)
    out = np.empty(pixels.shape, dtype=np.uint8)

    def work(i: int) -> None:
        y0, y1 = int(bounds[i]), int(bounds[i + 1])
        r0, r1 = max(0, y0 - overlap), min(h, y1 + overlap)
        res = fn(pixels[r0:r1])
        out[y0:y1] = res[y0 - r0 : (y0 - r0) + (y1 - y0)]

    list(_POOL.map(work, range(n)))
    return out
