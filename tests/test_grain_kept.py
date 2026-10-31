"""The film's grain survives the pipeline: a conversion at full resolution keeps it untouched, and the warps (straighten, keystone) no longer soften it the way linear interpolation did."""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photoeditor.features.geometry import logic as geo  # noqa: E402


def _grain(h=800, w=1200, sigma=2500.0, seed=0):
    return np.clip(30000 + np.random.default_rng(seed).normal(0, sigma, (h, w, 3)), 0, 65535).astype(np.uint16)


def _residual(a):
    x = a.astype(np.float32).mean(axis=2)
    return (x - cv2.GaussianBlur(x, (0, 0), 3))[20:-20, 20:-20]


def test_a_straighten_keeps_the_grain():
    a = _grain()
    base = _residual(a).std()
    for degrees in (0.4, 1.5, 6.0):
        out = geo.fine_rotate(a, degrees)
        r = _residual(out)
        assert r.std() / base > 0.85, (degrees, "the grain is softened by the rotation", r.std() / base)
        assert abs(float((r[:, 1:] * r[:, :-1]).mean() / (r * r).mean())) < 0.2, "and it is still grain, not a smear"


def test_a_keystone_keeps_the_grain():
    a = _grain()
    base = _residual(a).std()
    out = geo.keystone(a, 0.15, 0.0)
    assert _residual(out).std() / base > 0.85


def test_the_nearest_mode_used_for_masks_is_still_nearest():
    a = np.zeros((40, 60), np.uint8)
    a[10:20, 10:30] = 255
    out = geo.fine_rotate(a, 3.0, nearest=True)
    assert set(np.unique(out)) <= {0, 255}, "no grey values: a mask stays a mask"
