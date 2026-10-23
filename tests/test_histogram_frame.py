"""The histogram and the readings leave out the clear film border round the picture: with no crop they are what a crop to the picture gives; with the border on the scan not found they are of everything."""
import dataclasses

import numpy as np

from photoeditor.desktop.render import EditParams, Renderer
from photoeditor.desktop.session import AppState

H, W, B = 600, 800, 70


def _scan():
    rng = np.random.default_rng(0)
    img = np.full((H, W, 3), 238, np.uint8)                                  # clear film: the brightest part of a negative
    img[B:H - B, B:W - B] = np.clip(95 + rng.normal(0, 6, (H - 2 * B, W - 2 * B, 3)), 0, 255).astype(np.uint8)
    return img


def _stats(scan, **kw):
    p = dataclasses.replace(EditParams.from_state(AppState()), negative_inverted=True, scan_width=W, **kw)
    return Renderer().render(scan, p, "hist", W, None, want_stats=True)[2]


def test_the_film_border_is_no_part_of_the_histogram():
    scan = _scan()
    whole = _stats(scan)
    cropped = _stats(scan, crop_rect=(B, B, W - B, H - B))
    assert whole is not None and cropped is not None
    pairs = [("luminance", whole["luminance_histogram"], cropped["luminance_histogram"])] + [(c, whole["histogram"][c], cropped["histogram"][c]) for c in ("r", "g", "b")]
    for name, x, y in pairs:
        a, b = np.asarray(x, float), np.asarray(y, float)
        a, b = a / a.sum(), b / b.sum()
        assert np.abs(a - b).max() < 0.02, (name, np.abs(a - b).max())
    assert abs(whole["luminance"]["avg"] - cropped["luminance"]["avg"]) < 2.0, (whole["luminance"], cropped["luminance"])


def test_without_a_found_border_everything_is_counted():
    scan = np.full((H, W, 3), 120, np.uint8)
    scan[:, : W // 2] = 60                                                   # no clear border here: two broad tones
    s = _stats(scan)
    hist = np.asarray(s["luminance_histogram"], float)
    assert (hist > 0).sum() >= 2 and hist.sum() > 0
