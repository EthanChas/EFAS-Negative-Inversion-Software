"""Shadows & Highlights: no more washed-out look - black and white stay put, tones never swap, and colour is kept."""
import itertools

import numpy as np

from photoeditor.features.shadows_highlights.logic import adjust_shadows_highlights, gain_table, tone_curve


def grey(v, shape=(2, 2)):
    return np.full((*shape, 3), v, np.uint8)


def ramp():
    return np.repeat(np.arange(256, dtype=np.uint8)[None, :, None], 3, axis=2)


def test_zero_is_untouched():
    img = ramp()
    assert adjust_shadows_highlights(img, 0.0, 0.0) is img


def test_black_and_white_never_move():
    for s, h in itertools.product((-1.0, -0.5, 0.5, 1.0), repeat=2):
        out = adjust_shadows_highlights(ramp(), s, h)
        assert out[0, 0, 0] == 0, ("black lifted", s, h)
        assert out[0, 255, 0] == 255, ("white moved", s, h)


def test_tones_never_swap_places():
    values = (-1.0, -0.75, -0.25, 0.0, 0.25, 0.75, 1.0)
    for s, h in itertools.product(values, repeat=2):
        row = adjust_shadows_highlights(ramp(), s, h)[0, :, 0].astype(int)
        assert (np.diff(row) >= 0).all(), ("the ramp runs backwards", s, h)
        y = tone_curve(s, h)
        assert (np.diff(y) >= 0).all() and y[0] == 0 and y[-1] == 1


def test_directions():
    mid, dark, light = 128, 40, 215
    assert adjust_shadows_highlights(grey(dark), 0.6, 0)[0, 0, 0] > dark
    assert adjust_shadows_highlights(grey(dark), -0.6, 0)[0, 0, 0] < dark
    assert adjust_shadows_highlights(grey(light), 0, 0.6)[0, 0, 0] > light
    assert adjust_shadows_highlights(grey(light), 0, -0.6)[0, 0, 0] < light
    # each slider mostly leaves the other end alone
    assert abs(int(adjust_shadows_highlights(grey(light), 1.0, 0)[0, 0, 0]) - light) <= 3
    assert abs(int(adjust_shadows_highlights(grey(dark), 0, 1.0)[0, 0, 0]) - dark) <= 4


def test_midtones_are_left_close_to_alone():
    for s in (-1.0, 1.0):
        assert abs(int(adjust_shadows_highlights(grey(128), s, 0)[0, 0, 0]) - 128) <= 16
    for h in (-1.0, 1.0):
        assert abs(int(adjust_shadows_highlights(grey(128), 0, h)[0, 0, 0]) - 128) <= 30


def test_colour_is_kept_not_drained():
    px = np.array([[[60, 24, 12]]], np.uint8)
    before = (60 - 12) / 60
    out = adjust_shadows_highlights(px, 1.0, 0)[0, 0].astype(float)
    assert out[0] > 70, "it was lifted"
    assert abs((out.max() - out.min()) / out.max() - before) < 0.03, "saturation is what it was"
    ratio_before, ratio_after = 60 / 24, out[0] / out[1]
    assert abs(ratio_after - ratio_before) / ratio_before < 0.05, "hue is what it was"


def test_a_bright_colour_is_not_pushed_past_white():
    px = np.array([[[250, 200, 100]]], np.uint8)
    out = adjust_shadows_highlights(px, 0, 1.0)[0, 0].astype(int)
    assert out.max() <= 255 and out[0] >= 250
    assert abs(out[1] / out[0] - 200 / 250) < 0.05, "no channel clipped on its own, so the hue holds"


def old_method(pixels, shadows, highlights):
    """The earlier algorithm, for comparison: the same offset on every channel."""
    x = np.arange(256) / 255.0
    sw, hw = np.clip(1 - x * 2, 0, 1), np.clip(x * 2 - 1, 0, 1)
    table = np.round((shadows * sw + highlights * hw) * 120).astype(int)
    luma = (pixels.reshape(-1, 3) @ np.array([0.299, 0.587, 0.114])).reshape(pixels.shape[:2]).astype(np.uint8)
    return np.clip(pixels.astype(int) + table[luma][:, :, None], 0, 255).astype(np.uint8)


def test_it_is_not_washed_out_like_the_old_one():
    rng = np.random.default_rng(1)
    scene = np.clip(rng.normal(90, 55, (120, 160, 3)), 0, 255).astype(np.uint8)
    scene[:10] = 0
    scene[10:20] = (200, 60, 30)
    new, old = adjust_shadows_highlights(scene, 0.6, 0), old_method(scene, 0.6, 0)
    assert new.min() == 0 and old[:10].min() > 40, "the old one lifted pure black to grey"
    # contrast (spread of brightness) and colour (spread between channels) survive better
    assert new.astype(float).std() > old.astype(float).std() * 1.05
    chroma = lambda a: (a.max(axis=2).astype(float) - a.min(axis=2)).mean()
    assert chroma(new) > chroma(old) * 1.05, "more colour left"
    sat = lambda a: float(np.mean((a.max(axis=2).astype(float) - a.min(axis=2)) / np.maximum(a.max(axis=2), 1)))
    assert abs(sat(adjust_shadows_highlights(scene, 0, -0.6)) - sat(scene)) < 0.02, "darkening highlights keeps colours as saturated as they were"
    assert abs(sat(adjust_shadows_highlights(scene, 0.6, 0)) - sat(scene)) < 0.03
    assert sat(old) < sat(scene) - 0.03, "the old one drained the colour"


def test_big_pictures_are_the_same_as_small_ones():
    rng = np.random.default_rng(2)
    big = rng.integers(0, 256, (900, 700, 3), dtype=np.uint8)
    whole = adjust_shadows_highlights(big, 0.4, -0.3)
    assert whole.shape == big.shape and whole.dtype == np.uint8
    top = adjust_shadows_highlights(big[:100], 0.4, -0.3)
    assert np.array_equal(top, whole[:100])


def test_gain_table_shape():
    g = gain_table(0.5, 0.5)
    assert g.shape == (256,) and g[0] == 1.0 and (g > 0).all()
