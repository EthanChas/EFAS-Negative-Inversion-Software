"""Tone Equalizer (darktable's, features/toneequalizer/logic.py): the curve through the nine nodes, the luminance estimators, the edge-aware mask, the relighting, the wands and the presets."""
import numpy as np
import pytest

from photoeditor.features.toneequalizer import logic as T


def _ramp(h=64, w=256):
    """A grey ramp from black to white, the same on every row."""
    row = np.linspace(0, 255, w).astype(np.uint8)
    return np.repeat(np.repeat(row[None, :, None], 3, axis=2), h, axis=0)


def test_it_does_nothing_until_a_node_is_moved():
    img = _ramp()
    assert T.is_neutral(T.DEFAULTS) and T.is_neutral({}) and T.apply_tone_equalizer(img, T.DEFAULTS) is img
    assert not T.is_neutral({"teq_band3": 0.5})
    assert T.apply_tone_equalizer(img, T.PRESETS["simple tone curve"]) is img, "darktable's 'simple tone curve' has all nodes at 0"


def test_the_curve_passes_close_to_the_nodes_and_is_the_unit_gain_when_flat():
    flat = T.correction_curve({**T.DEFAULTS})[1]
    assert np.abs(flat).max() < 0.05, "no correction between the nodes when every node is 0"
    values = {**T.DEFAULTS, **{f"teq_band{i}": v for i, v in enumerate([0.0, 0.3, 0.6, 0.9, 1.0, 0.9, 0.6, 0.3, 0.0])}}
    ev, corr = T.correction_curve(values, 9 * 32 - 31)
    at_nodes = corr[::32]
    assert np.abs(at_nodes - np.array([0.0, 0.3, 0.6, 0.9, 1.0, 0.9, 0.6, 0.3, 0.0])).max() < 0.25
    assert ev[0] == T.MIN_EV and ev[-1] == T.MAX_EV
    # the gain is held between a quarter and four times
    huge = {**T.DEFAULTS, **{f"teq_band{i}": 2.0 for i in range(9)}}
    assert T.pixel_correction(-4.0, T.channel_factors(huge), T.sigma_of(0.0)) <= 4.0
    assert T.sigma_of(0.0) == pytest.approx(2 ** 0.5)


def test_the_luminance_estimators_agree_on_grey_and_differ_on_colour():
    grey = np.full((4, 4, 3), 0.25, dtype=np.float32)
    for method, expect in ((T.MEAN, 0.25), (T.LIGHTNESS, 0.25), (T.VALUE, 0.25), (T.NORM_1, 0.75), (T.NORM_2, 0.25 * 3 ** 0.5), (T.NORM_POWER, 0.25), (T.GEOMEAN, 0.25)):
        assert T.luminance_mask(grey, method, 1.0, 0.0, 1.0)[0, 0] == pytest.approx(expect, rel=1e-4), method
    red = np.zeros((2, 2, 3), dtype=np.float32)
    red[..., 0] = 0.5
    assert T.luminance_mask(red, T.GEOMEAN, 1.0, 0.0, 1.0)[0, 0] == pytest.approx(T.MIN_FLOAT), "a saturated colour has no geometric-mean luminance: it counts as a shadow"
    assert T.luminance_mask(red, T.VALUE, 2.0, 0.0, 1.0)[0, 0] == pytest.approx(1.0), "the exposure compensation scales the mask"


def test_without_details_the_mask_is_the_pixels_own_and_a_guided_filter_smooths_it():
    img = _ramp()
    img[20:44, 100:156] = 30
    linear = T._to_linear(img)
    plain = T.compute_mask(linear, {**T.DEFAULTS, "teq_details": float(T.NONE)})
    assert np.allclose(plain, T.luminance_mask(linear, T.NORM_2, 1.0, 0.0, 1.0))
    for details in (T.GUIDED, T.EIGF, T.AVG_GUIDED, T.AVG_EIGF):
        mask = T.compute_mask(linear, {**T.DEFAULTS, "teq_details": float(details), "teq_feathering": 1.0, "teq_blending": 8.0})
        assert mask.shape == plain.shape and mask.min() >= T.MIN_FLOAT * 0.999 and np.isfinite(mask).all(), details
    smooth = T.compute_mask(linear, {**T.DEFAULTS, "teq_details": float(T.EIGF), "teq_feathering": 1.0, "teq_blending": 8.0, "teq_iterations": 3.0})
    assert np.abs(np.diff(np.log2(smooth), axis=1)).mean() < np.abs(np.diff(np.log2(plain), axis=1)).mean() * 1.0001


def test_lifting_the_shadows_lightens_dark_tones_far_more_than_light_ones():
    img = _ramp()
    values = {**T.DEFAULTS, "teq_details": float(T.NONE), "teq_method": float(T.NORM_POWER), "teq_band2": 1.0, "teq_band3": 1.0, "teq_band4": 1.0}
    out = T.apply_tone_equalizer(img, values)
    dark, light = slice(30, 60), slice(220, 250)
    gain_dark = out[:, dark].astype(int).mean() - img[:, dark].astype(int).mean()
    gain_light = out[:, light].astype(int).mean() - img[:, light].astype(int).mean()
    assert gain_dark > 15 and gain_dark > gain_light * 3, (gain_dark, gain_light)
    assert out.dtype == np.uint8 and out.shape == img.shape
    darker = T.apply_tone_equalizer(img, {**values, "teq_band2": -1.0, "teq_band3": -1.0, "teq_band4": -1.0})
    assert darker[:, dark].astype(int).mean() < img[:, dark].astype(int).mean() - 5


def test_the_mask_histogram_and_the_two_wands():
    rng = np.random.default_rng(5)
    img = np.clip(rng.normal(90, 40, (96, 96, 3)), 0, 255).astype(np.uint8)
    hist, first, last = T.mask_stats(img, T.DEFAULTS)
    assert hist.shape == (256,) and hist.sum() == 96 * 96 and first < last <= 6.0
    exposure = T.auto_exposure_boost((first, last), T.DEFAULTS)
    values = {**T.DEFAULTS, "teq_exposure_boost": exposure}
    again = T.auto_exposure_boost(T.mask_stats(img, values)[1:], values)
    assert abs(again - exposure) < 0.35, "setting the wand's value and asking again gives about the same"
    contrast = T.auto_contrast_boost((first, last), {**T.DEFAULTS, "teq_details": float(T.NONE)})
    assert np.isfinite(contrast)
    # darktable centres the mask on -4 EV: the middle of the two deciles lands at about -4 EV once the exposure is compensated
    moved = T.mask_stats(img, values)
    assert abs((moved[1] + moved[2]) / 2 + 4.0) < 1.0


def test_the_mask_can_be_shown_as_a_grey_picture():
    img = _ramp()
    shown = T.mask_picture(img, {**T.DEFAULTS, "teq_details": float(T.NONE)})
    assert shown.shape == img.shape and np.array_equal(shown[..., 0], shown[..., 1]) and np.array_equal(shown[..., 1], shown[..., 2])
    row = shown[0, :, 0].astype(int)
    assert row[-1] > row[len(row) // 2] > row[0], "light to the right, as in the picture"


def test_darktables_presets_are_all_here():
    expected = {"simple tone curve", "mask blending | all purposes", "mask blending | people with backlight", "relight: fill-in", "contrast tone curve | soft",
                "contrast tone curve | medium", "contrast tone curve | strong"}
    expected |= {f"compress shadows/highlights | {m} | {s}" for m in ("EIGF", "GF") for s in ("strong", "medium", "soft")}
    assert set(T.PRESETS) == expected
    strong = T.PRESETS["compress shadows/highlights | EIGF | strong"]
    assert strong["teq_band0"] == pytest.approx(0.65) and strong["teq_band1"] == pytest.approx(5 / 3 * 0.65) and strong["teq_band5"] == pytest.approx(-0.65) and strong["teq_band4"] == 0.0
    assert strong["teq_details"] == T.EIGF and strong["teq_iterations"] == 5 and strong["teq_exposure_boost"] == pytest.approx(-1.57)
    assert T.PRESETS["compress shadows/highlights | GF | strong"]["teq_details"] == T.GUIDED
    assert T.PRESETS["relight: fill-in"]["teq_band4"] == pytest.approx(1.33)
    for name, preset in T.PRESETS.items():
        assert set(preset) == set(T.KEYS), name
    img = _ramp()
    assert not np.array_equal(T.apply_tone_equalizer(img, T.PRESETS["compress shadows/highlights | EIGF | medium"]), img)
