"""Colour in OKLCH: Vibrance, the Color Mixer and the scanner colour response (features/colormix/logic.py)."""
import numpy as np
import pytest

from photoeditor.features.colormix import logic as cm


def swatches():
    """A strip of named colours (8-bit sRGB), plus greys."""
    colours = {
        "red": (185, 95, 95), "orange": (205, 140, 85), "yellow": (205, 190, 95), "green": (100, 160, 105), "aqua": (90, 165, 170), "blue": (100, 125, 190),
        "purple": (140, 105, 175), "magenta": (180, 105, 155), "skin": (205, 160, 135), "muted": (125, 135, 150), "grey": (128, 128, 128), "dark": (30, 30, 34),
    }
    names = list(colours)
    img = np.array([[colours[n] for n in names]], dtype=np.uint8)
    return names, np.repeat(img, 6, axis=0)


def lab_of(pixels):
    lab = cm.srgb8_to_oklab(pixels)
    return lab[..., 0], np.hypot(lab[..., 1], lab[..., 2]), np.degrees(np.arctan2(lab[..., 2], lab[..., 1])) % 360.0


def at(arr, names, name):
    return float(arr[0, names.index(name)])


def test_the_colour_space_round_trips_and_greys_have_no_chroma():
    rng = np.random.default_rng(1)
    px = rng.integers(0, 256, (60, 80, 3), dtype=np.uint8)
    back = cm.oklab_to_srgb8(cm.srgb8_to_oklab(px))
    assert np.abs(back.astype(int) - px.astype(int)).max() <= 1, "sRGB -> OKLab -> sRGB gives the picture back"
    grey = np.full((4, 4, 3), 99, np.uint8)
    lab = cm.srgb8_to_oklab(grey)
    assert np.abs(lab[..., 1:]).max() < 1e-3 and 0.3 < lab[0, 0, 0] < 0.8
    white = cm.srgb8_to_oklab(np.full((1, 1, 3), 255, np.uint8))
    assert white[0, 0, 0] == pytest.approx(1.0, abs=1e-3)


def test_neutral_settings_return_the_picture_itself():
    _n, px = swatches()
    assert cm.apply_color(px, {}, "none") is px and cm.apply_color(px, cm.DEFAULTS, "none", 1.0) is px and cm.is_neutral(cm.DEFAULTS)
    assert cm.apply_color(px, {}, "frontier", 0.0) is px, "a response at amount 0 is no response"


def test_vibrance_lifts_muted_colour_more_than_vivid_and_spares_skin_and_grey():
    names, px = swatches()
    _l0, c0, _h0 = lab_of(px)
    out = cm.apply_color(px, {"vibrance": 1.0})
    _l1, c1, _h1 = lab_of(out)
    gain = lambda n: at(c1, names, n) / at(c0, names, n)
    assert gain("muted") > 1.25, "a muted colour gains a lot"
    assert gain("muted") > gain("red") + 0.1 and gain("muted") > gain("blue") + 0.1, "more than the vivid ones"
    assert gain("skin") < gain("muted"), "skin is held back"
    assert at(c1, names, "grey") < 0.01, "a grey stays grey"
    down = lab_of(cm.apply_color(px, {"vibrance": -1.0}))[1]
    assert at(down, names, "muted") < at(c0, names, "muted") * 0.8, "minus mutes"
    assert abs(at(_l1, names, "muted") - at(_l0, names, "muted")) < 0.03, "lightness is not dragged along with the colour"


def test_a_mixer_band_moves_only_its_own_colours():
    names, px = swatches()
    l0, c0, h0 = lab_of(px)
    sat = cm.apply_color(px, {"mix_sat_blue": 1.0})
    _l, c1, _h = lab_of(sat)
    assert at(c1, names, "blue") > at(c0, names, "blue") * 1.5, "blue gets much more colourful"
    for other in ("red", "orange", "yellow", "green", "grey"):
        assert abs(at(c1, names, other) - at(c0, names, other)) < 0.01, other
    hue = cm.apply_color(px, {"mix_hue_green": 1.0})
    _l, _c, h1 = lab_of(hue)
    shift = (at(h1, names, "green") - at(h0, names, "green") + 180) % 360 - 180
    assert 20 < shift < 40, "plus 1 turns a green about 30 degrees along the hue wheel"
    assert abs((at(h1, names, "magenta") - at(h0, names, "magenta") + 180) % 360 - 180) < 2
    lum = cm.apply_color(px, {"mix_lum_yellow": 1.0, "mix_lum_red": -1.0})
    l1, _c, _h = lab_of(lum)
    assert at(l1, names, "yellow") > at(l0, names, "yellow") + 0.05 and at(l1, names, "red") < at(l0, names, "red") - 0.05
    assert abs(at(l1, names, "blue") - at(l0, names, "blue")) < 0.01
    assert set(cm.MIXER_KEYS) == {f"mix_{k}_{b}" for b in cm.BANDS for k in ("hue", "sat", "lum")} and len(cm.KEYS) == 25


def test_bands_blend_into_their_neighbours_with_no_gaps():
    hues = np.linspace(0, 359, 360)
    weights = cm.band_weights(hues)
    total = sum(weights.values())
    assert np.allclose(total, 1.0, atol=1e-4), "every hue is covered once: the windows add up to one everywhere"
    assert weights["red"][29] > 0.5 and weights["red"][29] == max(w[29] for w in weights.values()), "a band dominates at its own centre"
    assert weights["red"][100] == 0.0 and weights["yellow"][100] > 0.5


def test_the_results_stay_in_gamut_without_a_hue_shift():
    px = np.array([[[0, 255, 0], [255, 0, 255], [0, 80, 255], [255, 220, 0]]], dtype=np.uint8)
    out = cm.apply_color(px, {"vibrance": 1.0, "mix_sat_green": 1.0, "mix_sat_blue": 1.0, "mix_sat_magenta": 1.0})
    assert out.dtype == np.uint8 and out.shape == px.shape
    _l0, _c0, h0 = lab_of(px)
    _l1, _c1, h1 = lab_of(out)
    assert np.all(np.abs((h1 - h0 + 180) % 360 - 180) < 12), "pulling a colour into gamut keeps its hue"


def test_a_scanner_response_casts_each_tonal_range_the_way_labs_describe():
    ramp = np.repeat(np.arange(256, dtype=np.uint8)[None, :, None], 3, axis=2)
    dark, mid, light = ramp[:, 30:31], ramp[:, 120:121], ramp[:, 230:231]

    def cast(response, px):
        lab = cm.srgb8_to_oklab(cm.apply_color(px, {}, response, 1.0))
        return float(lab[0, 0, 1]), float(lab[0, 0, 2])

    a, b = cast("frontier", dark)
    assert b < -0.004 and a < -0.003, "Frontier: cyan-blue shadows"
    a, b = cast("frontier", mid)
    assert b > 0.005, "Frontier: golden midtones"
    a, b = cast("noritsu", dark)
    assert a < -0.003, "Noritsu: a faint green in the shadows"
    a, b = cast("noritsu", mid)
    assert a > 0.002 and b > 0.002, "Noritsu: peach midtones"
    assert cast("pakon", dark) == pytest.approx((0.0, 0.0), abs=2e-3), "Pakon stays clean in the shadows"
    assert abs(cast("frontier", light)[1]) < 0.012


def test_a_response_changes_colourfulness_and_its_amount_scales_it():
    names, px = swatches()
    c0 = lab_of(px)[1]
    frontier = lab_of(cm.apply_color(px, {}, "frontier", 1.0))[1]
    noritsu = lab_of(cm.apply_color(px, {}, "noritsu", 1.0))[1]
    colourful = [names.index(n) for n in ("red", "orange", "yellow", "green", "aqua", "blue", "purple", "magenta")]
    assert frontier[0, colourful].mean() > c0[0, colourful].mean() * 1.05, "Frontier is more saturated"
    assert noritsu[0, colourful].mean() < c0[0, colourful].mean() * 0.96, "Noritsu is softer"
    half = lab_of(cm.apply_color(px, {}, "frontier", 0.5))[1]
    assert c0[0, colourful].mean() < half[0, colourful].mean() < frontier[0, colourful].mean(), "half the amount, half the change"
    assert set(cm.RESPONSE) == set(cm.RESPONSES) - {"none"}


def test_large_pictures_are_processed_in_pieces_with_the_same_result():
    rng = np.random.default_rng(5)
    px = rng.integers(0, 256, (900, 1300, 3), dtype=np.uint8)
    whole = cm.apply_color(px, {"vibrance": 0.5, "mix_hue_red": 0.4}, "frontier", 1.0)
    top = cm.apply_color(px[:300], {"vibrance": 0.5, "mix_hue_red": 0.4}, "frontier", 1.0)
    assert np.array_equal(whole[:300], top), "no seams between the pieces"
