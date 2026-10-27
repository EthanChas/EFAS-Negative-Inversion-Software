"""Diffuse or Sharpen (darktable's, features/diffuse/logic.py): the scales it works on, that it does nothing when it should, that negative speeds sharpen and positive ones blur, the
luminance mask that inpaints highlights, that the picture can be cut into strips, and darktable's presets."""
import math

import numpy as np
import pytest

from photoeditor.features.diffuse import logic as D


def _edge(blur=2.5, h=96, w=128):
    """A soft vertical edge (dark left, light right) with a little texture, the way a scan of a hard edge looks."""
    import cv2

    x = np.zeros((h, w), dtype=np.float32)
    x[:, w // 2:] = 200.0
    x = cv2.GaussianBlur(x, (0, 0), blur)
    return np.repeat(np.clip(x + 20, 0, 255)[..., None], 3, axis=2).astype(np.uint8)


def test_darktables_scale_arithmetic():
    assert D.equivalent_sigma_at_step(D.B_SPLINE_SIGMA, 0) == D.B_SPLINE_SIGMA
    assert D.equivalent_sigma_at_step(D.B_SPLINE_SIGMA, 1) == pytest.approx(math.sqrt(D.B_SPLINE_SIGMA ** 2 + (2 * D.B_SPLINE_SIGMA) ** 2))
    # the number of scales needed to reach a radius: more for a bigger radius, and at least one
    steps = [D.num_steps_to_reach_equivalent_sigma(D.B_SPLINE_SIGMA, r) for r in (0.5, 1.0, 3.0, 6.0, 16.0, 64.0, 1024.0)]
    assert steps == sorted(steps) and steps[0] == 1 and steps[3] == 4, steps
    # the radius is in pixels of the full picture, so a smaller preview needs fewer scales
    values = {**D.DEFAULTS, "dif_radius": 200.0}
    assert D.scales_for(values, 1.0) > D.scales_for(values, 8.0) >= 1
    assert D.scales_for({**D.DEFAULTS, "dif_radius": 100000.0}, 1.0) == D.MAX_NUM_SCALES


def test_it_does_nothing_until_a_speed_the_sharpness_or_the_threshold_is_set():
    img = _edge()
    assert D.is_neutral(D.DEFAULTS) and D.is_neutral({}) and D.is_neutral(None)
    assert D.apply_diffuse(img, D.DEFAULTS) is img, "the defaults leave the very same picture"
    assert D.apply_diffuse(img, {**D.DEFAULTS, "dif_iterations": 40.0, "dif_radius": 512.0, "dif_aniso_first": 5.0}) is img, "iterations, radius and anisotropy alone do nothing"
    for key in ("dif_first", "dif_second", "dif_third", "dif_fourth", "dif_sharpness", "dif_threshold"):
        assert not D.is_neutral({key: 0.2})


def test_the_wavelet_decomposition_rebuilds_the_picture_exactly_when_nothing_is_diffused():
    rng = np.random.default_rng(1)
    pix = rng.random((40, 52, 3)).astype(np.float32)
    values = {**D.DEFAULTS, "dif_radius": 40.0}
    scales = D.scales_for(values, 1.0)
    out = D._one_pass(pix, values, None, 1.0, scales)
    assert np.abs(out - pix).max() < 1e-5, "high-frequency layers plus the residual are the picture"


def test_negative_speeds_sharpen_an_edge_and_positive_speeds_blur_it():
    img = _edge()

    def steepest(a):
        return float(np.abs(np.diff(a[48].astype(np.float32), axis=0)[:, 0]).max())

    sharp = D.apply_diffuse(img, D.PRESETS["sharpen demosaicing | AA filter"])
    soft = D.apply_diffuse(img, D.PRESETS["surface blur"])
    assert steepest(sharp) > steepest(img) * 1.05, (steepest(sharp), steepest(img))
    assert sharp.shape == img.shape and sharp.dtype == np.uint8
    # a surface blur flattens noise on a flat area and keeps the edge
    rng = np.random.default_rng(2)
    flat = np.clip(120 + rng.normal(0, 8, (80, 80, 3)), 0, 255).astype(np.uint8)
    denoised = D.apply_diffuse(flat, D.PRESETS["surface blur"])
    assert denoised.std() < flat.std() * 0.7
    assert soft[48].astype(int).std() > 0


def test_the_luminance_threshold_only_works_on_the_bright_parts():
    rng = np.random.default_rng(3)
    img = np.clip(70 + rng.normal(0, 3, (64, 64, 3)), 0, 255).astype(np.uint8)
    img[20:30, 20:30] = 250
    values = {**D.PRESETS["inpaint highlights"], "dif_threshold": 0.5}      # 0.5 in linear light is a bright part of an 8-bit picture
    out = D.apply_diffuse(img, values)
    far = np.ones(img.shape[:2], dtype=bool)
    far[10:40, 10:40] = False
    assert np.array_equal(out[far], img[far]), "away from the bright part nothing is touched"
    assert not np.array_equal(out[20:30, 20:30], img[20:30, 20:30]), "the bright part was filled in"


def test_a_large_picture_is_cut_into_strips_that_agree_with_the_whole(monkeypatch):
    rng = np.random.default_rng(4)
    pix = np.clip(rng.normal(128, 20, (300, 96, 3)), 0, 255).astype(np.uint8)
    values = {**D.PRESETS["sharpness | normal"]}
    whole = D.apply_diffuse(pix, values)
    monkeypatch.setattr(D, "_BUDGET", 3 * 96 * 11 * 60)      # so few rows fit that the picture goes in strips
    cut = D.apply_diffuse(pix, values)
    inner = np.abs(whole[60:-60].astype(int) - cut[60:-60].astype(int))
    assert inner.mean() < 0.5 and inner.max() <= 12, (inner.mean(), inner.max())


def test_the_presets_are_all_here_and_make_the_picture_change():
    expected = ["lens deblur | soft", "lens deblur | medium", "lens deblur | hard", "dehaze | default", "dehaze | extra contrast",
                "surface blur", "sharpen demosaicing | no AA filter", "sharpen demosaicing | AA filter", "local contrast | normal", "local contrast | fine", "inpaint highlights",
                "sharpness | fast", "sharpness | normal", "sharpness | strong", "local contrast | fast"]
    assert sorted(D.PRESETS) == sorted(expected)
    for name, preset in D.PRESETS.items():
        assert set(preset) == set(D.KEYS), name
        for key, value in preset.items():
            low, high = D.RANGES[key]
            assert low <= value <= high, (name, key, value)
    assert D.PRESETS["sharpness | strong"]["dif_iterations"] == 6 and D.PRESETS["inpaint highlights"]["dif_threshold"] == 1.41
    img = _edge()
    for name in ("sharpness | fast", "dehaze | default", "surface blur"):
        assert not np.array_equal(D.apply_diffuse(img, D.PRESETS[name], zoom=4.0), img), name
