"""Color Balance RGB (darktable's, features/colorbalancergb/logic.py): that it does nothing at rest, that each group of controls does what darktable's does, that both saturation formulas keep
colours in gamut without breaking, and the colour-space constants."""
import numpy as np
import pytest

from photoeditor.features.colorbalancergb import logic as C


def _patch():
    """A small picture with greys, a skin tone, a sky, a leaf and a deep shadow."""
    colours = [(30, 30, 30), (120, 120, 120), (230, 230, 230), (200, 150, 120), (90, 130, 200), (60, 140, 70), (180, 40, 40), (15, 10, 12)]
    return np.repeat(np.array(colours, dtype=np.uint8)[None, :, :], 8, axis=0)


def test_it_does_nothing_until_a_grading_slider_moves():
    img = _patch()
    assert C.is_neutral(C.DEFAULTS) and C.is_neutral({}) and C.apply_color_balance(img, C.DEFAULTS) is img
    assert C.apply_color_balance(img, {**C.DEFAULTS, "cbr_shadows_weight": 2.0, "cbr_mask_grey_fulcrum": 0.3, "cbr_formula": 0.0}) is img, "only the masks and the formula: still nothing"
    assert not C.is_neutral({"cbr_vibrance": 0.1})


def test_the_colour_space_constants_are_consistent():
    # the Filmlight RGB matrices are inverses of each other, and so are the XYZ and cone ones
    assert np.allclose(C._LMS_TO_GRADING @ C._GRADING_TO_LMS, np.eye(3), atol=1e-6)
    assert np.allclose(C._XYZ_TO_LMS @ C._LMS_TO_XYZ, np.eye(3), atol=2e-4)
    assert np.allclose(C._SRGB_TO_XYZ @ C._XYZ_TO_SRGB, np.eye(3), atol=1e-5)
    # white in sRGB has the D65 white of Yrg
    lms = C._RGB_TO_LMS @ np.ones(3)
    Y, r, g = C._yrg_from_lms(lms)
    assert (r, g) == pytest.approx((C._D65_R, C._D65_G), abs=2e-4)
    back = C._lms_from_yrg(Y, r, g)
    assert np.allclose(back, lms, atol=1e-6)
    for formula in (C.FORMULA_JZAZBZ, C.FORMULA_DTUCS):
        lut = C._gamut_lut(formula)
        assert lut.shape == (C.LUT_ELEM,) and np.isfinite(lut).all() and lut.min() > 0, formula


def test_hue_shift_turns_colours_and_leaves_greys_alone():
    img = _patch()
    out = C.apply_color_balance(img, {**C.DEFAULTS, "cbr_hue_angle": 180.0})
    grey = [0, 1, 2]
    assert np.abs(out[:, grey].astype(int) - img[:, grey].astype(int)).max() <= 3, "greys have no hue to turn"
    red = out[0, 6].astype(int)
    assert red[0] < img[0, 6][0] and max(red[1], red[2]) > img[0, 6][1], "a red is turned towards the opposite side of the wheel"


def test_chroma_saturation_and_vibrance_move_colourfulness_the_way_the_sign_says():
    img = _patch()

    def spread(a):
        a = a.astype(int)
        return (a.max(axis=2) - a.min(axis=2))[:, 3:7].mean()

    for key in ("cbr_chroma_global", "cbr_saturation_global", "cbr_vibrance"):
        more = C.apply_color_balance(img, {**C.DEFAULTS, key: 0.4})
        less = C.apply_color_balance(img, {**C.DEFAULTS, key: -0.4})
        assert spread(more) > spread(img) > spread(less), key
    flat = C.apply_color_balance(img, {**C.DEFAULTS, "cbr_saturation_global": -1.0})
    assert spread(flat) < 14, "all the saturation taken out leaves nearly grey"
    # in the other saturation formula as well
    legacy = C.apply_color_balance(img, {**C.DEFAULTS, "cbr_saturation_global": 0.4, "cbr_formula": 0.0})
    assert spread(legacy) > spread(img)


def test_brilliance_and_contrast_and_the_four_ways():
    img = _patch()
    lum = lambda a: a.astype(int).sum(axis=2)
    assert lum(C.apply_color_balance(img, {**C.DEFAULTS, "cbr_brilliance_global": 0.3})).mean() > lum(img).mean()
    assert lum(C.apply_color_balance(img, {**C.DEFAULTS, "cbr_brilliance_global": -0.3})).mean() < lum(img).mean()
    punchy = C.apply_color_balance(img, {**C.DEFAULTS, "cbr_contrast": 0.4})
    assert lum(punchy)[0, 2] > lum(img)[0, 2] and lum(punchy)[0, 0] < lum(img)[0, 0], "contrast about the grey fulcrum: lights lighter, darks darker"
    # lift: a warm tint in the shadows reaches the deep shadow but hardly the highlight
    warm = C.apply_color_balance(img, {**C.DEFAULTS, "cbr_shadows_C": 0.25, "cbr_shadows_H": 40.0})
    shadow_shift = np.abs(warm[0, 7].astype(int) - img[0, 7].astype(int)).sum()
    light_shift = np.abs(warm[0, 2].astype(int) - img[0, 2].astype(int)).sum()
    assert shadow_shift > 6 and shadow_shift > light_shift * 2, (shadow_shift, light_shift)
    assert warm[0, 7][0] > warm[0, 7][2], "red above blue in the tinted shadow"
    # gain does the opposite
    gain = C.apply_color_balance(img, {**C.DEFAULTS, "cbr_highlights_C": 0.1, "cbr_highlights_H": 40.0})
    assert np.abs(gain[0, 2].astype(int) - img[0, 2].astype(int)).sum() > np.abs(gain[0, 7].astype(int) - img[0, 7].astype(int)).sum()
    # global offset moves everything, power the midtones
    assert not np.array_equal(C.apply_color_balance(img, {**C.DEFAULTS, "cbr_global_Y": 0.03}), img)
    assert not np.array_equal(C.apply_color_balance(img, {**C.DEFAULTS, "cbr_midtones_Y": 0.2}), img)


def test_extreme_settings_stay_finite_and_in_range_in_both_formulas():
    rng = np.random.default_rng(6)
    img = rng.integers(0, 256, (24, 24, 3), dtype=np.uint8)
    img[0, :] = 0
    img[1, :] = 255
    for formula in (0.0, 1.0):
        for values in ({"cbr_saturation_global": 1.0, "cbr_chroma_global": 1.0}, {"cbr_brilliance_global": 1.0, "cbr_vibrance": 1.0}, {"cbr_shadows_C": 1.0, "cbr_highlights_C": 1.0, "cbr_global_C": 0.05},
                       {"cbr_contrast": 1.0, "cbr_midtones_Y": -1.0, "cbr_white_fulcrum": -8.0}):
            out = C.apply_color_balance(img, {**C.DEFAULTS, **values, "cbr_formula": formula})
            assert out.dtype == np.uint8 and out.shape == img.shape, (formula, values)


def test_the_presets_and_the_hue_swatch():
    assert sorted(C.PRESETS) == ["basic colorfulness | legacy", "basic colorfulness | natural skin", "basic colorfulness | standard", "basic colorfulness | vibrant colors"]
    assert C.PRESETS["basic colorfulness | legacy"]["cbr_formula"] == 0.0 and C.PRESETS["basic colorfulness | standard"]["cbr_saturation_highlights"] == -0.25
    for key in C.KEYS:
        low, high = C.RANGES[key]
        assert low <= C.DEFAULTS[key] <= high, key
    swatches = [C.hue_swatch(h) for h in range(0, 360, 60)]
    assert all(len(s) == 3 and all(0 <= v <= 255 for v in s) for s in swatches) and len(set(swatches)) == 6
