"""Finding the film's clear border for the film base (features/densitometry/rebate.py), on synthetic frames with known layouts."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photoeditor.features.densitometry import rebate  # noqa: E402

BASE = np.array([0.50, 0.35, 0.15])
BARE = np.array([0.95, 0.80, 0.70])
H, W = 300, 450


def picture(h, w, seed=0):
    rng = np.random.default_rng(seed)
    ramp = np.linspace(0.15, 1.8, w)[None, :] + rng.normal(0, 0.05, (h, w)) + np.linspace(0, 0.3, h)[:, None]
    return BASE * 10.0 ** -ramp[..., None]


def film(bare_left=22, rebate_left=38, rebate_other=24, noise=0.002, seed=1):
    """A negative: bare backlight, then the film border, then the picture; the other three sides have a border to the edge."""
    rng = np.random.default_rng(seed)
    v = np.empty((H, W, 3))
    v[:] = BASE
    inner_x1, inner_x2 = bare_left + rebate_left, W - rebate_other
    v[rebate_other:H - rebate_other, inner_x1:inner_x2] = picture(H - 2 * rebate_other, inner_x2 - inner_x1)
    if bare_left:
        v[:, :bare_left] = BARE
    return np.clip(v * (1 + rng.normal(0, noise, v.shape)), 1e-5, 1.0)


def test_a_border_inside_bare_backlight_is_found_and_the_backlight_is_not():
    r = rebate.find_rebate(film())
    assert r is not None and r.side == "left" and r.confidence == "high"
    x1, y1, x2, y2 = r.rect
    assert 22 <= x1 < x2 <= 60 and y2 > y1
    assert np.allclose(r.v, BASE, rtol=0.03)
    assert not np.allclose(r.v, BARE, rtol=0.1) and "bare backlight" in r.reasons[0]


def test_without_bare_light_the_border_is_a_medium_confidence_suggestion():
    r = rebate.find_rebate(film(bare_left=0, rebate_left=30))
    assert r is not None and r.confidence in ("medium", "low") and np.allclose(r.v, BASE, rtol=0.03)
    assert "could be the film border or the backlight" in " ".join(r.reasons)


def test_a_picture_that_fills_the_frame_has_no_border():
    assert rebate.find_rebate(picture(H, W).clip(1e-5, 1.0)) is None


def test_an_uneven_or_noisy_strip_is_not_offered():
    assert rebate.find_rebate(film(noise=0.09)) is None


def test_blown_out_backlight_alone_is_never_the_film_base():
    v = picture(H, W).clip(1e-5, 1.0)
    v[:, :40] = 1.0
    assert rebate.find_rebate(v) is None


def test_the_border_can_be_on_any_side():
    v = film()
    for k, expected in ((1, "bottom"), (2, "right"), (3, "top")):
        r = rebate.find_rebate(np.rot90(v, k).copy())
        assert r is not None and r.confidence == "high" and r.side == expected, (k, r)
        assert np.allclose(r.v, BASE, rtol=0.03)


def test_dust_in_the_border_does_not_change_the_answer():
    v = film()
    rng = np.random.default_rng(4)
    ys, xs = rng.integers(20, H - 20, 40), rng.integers(24, 58, 40)
    v[ys, xs] = 0.9
    r = rebate.find_rebate(v)
    assert r is not None and np.allclose(r.v, BASE, rtol=0.05)


def test_rectangle_is_in_the_coordinates_of_the_full_size_scan():
    big = np.kron(film(), np.ones((4, 4, 1)))
    r = rebate.find_rebate(big)
    assert r is not None and r.side == "left"
    x1, y1, x2, y2 = r.rect
    assert 4 * 22 <= x1 < x2 <= 4 * 60 and 0 <= y1 < y2 <= big.shape[0] and np.allclose(r.v, BASE, rtol=0.03)


def test_plateau_finder_on_a_profile():
    p = np.concatenate([np.full(20, 0.1), np.full(15, 0.25), np.linspace(0.3, 1.5, 25)])
    got = rebate.runs(p, tolerance=0.02, min_len=5)
    assert got[0][:2] == (0, 20) and got[1][:2] == (20, 35) and abs(got[1][2] - 0.25) < 1e-9
    assert rebate.runs(np.linspace(0, 2, 50), tolerance=0.02, min_len=5) == []


def test_bad_input_returns_nothing():
    assert rebate.find_rebate(np.zeros((8, 8, 3))) is None
    assert rebate.find_rebate(np.zeros((100, 100))) is None
