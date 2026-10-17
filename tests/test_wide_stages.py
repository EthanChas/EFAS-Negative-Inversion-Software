"""A 16-bit picture goes through the per-pixel stages at 16 bits (and is rounded to 8 bits once, at the end), so a negative's narrow range, stretched, shows no gaps.

Each stage that mixes pixels takes a uint16 picture too. Its 8-bit behaviour is unchanged; the 16-bit branch does the same arithmetic without the rounding in between."""
import dataclasses

import numpy as np
import pytest

from photoeditor.features.color.logic import adjust_saturation
from photoeditor.features.colormix.logic import apply_color
from photoeditor.features.denoise.logic import apply_chroma_denoise
from photoeditor.features.localcontrast.logic import apply_local_contrast
from photoeditor.features.lut.logic import apply_channel_lut, apply_wide_lut, identity_ramp, is_identity, to_uint8, wide_ramp, wide_ramp_to_lut16
from photoeditor.features.open_image import camera
from photoeditor.features.shadows_highlights.logic import adjust_shadows_highlights

MATRIX = ((1.12, -0.08, -0.04), (-0.05, 1.10, -0.05), (-0.02, -0.14, 1.16))
COLOUR = {"vibrance": 0.5, "mix_sat_blue": 0.4, "mix_hue_green": 0.3, "tone_amt_shadows": 0.4, "tone_hue_shadows": 200.0, "tone_amt_highs": 0.3, "tone_hue_highs": 40.0}

# (stage, how far its 16-bit result, rounded to 8 bits, may be from its 8-bit result on the same picture - the most, and on average, in 8-bit levels). Local contrast is the
# loosest: its 8-bit path rounds the lightness and each tile's curve to whole steps, which the 16-bit one does not.
STAGES = {
    "shadows_highlights": (lambda p: adjust_shadows_highlights(p, 0.5, -0.3), 1, 0.6),
    "saturation": (lambda p: adjust_saturation(p, 0.4), 1, 0.6),
    "camera_matrix": (lambda p: camera.apply_matrix(p, MATRIX), 1, 0.6),
    "chroma_denoise": (lambda p: apply_chroma_denoise(p, 2.0, 1.0), 2, 0.6),
    "local_contrast": (lambda p: apply_local_contrast(p, 0.5), 6, 1.0),
    "colour": (lambda p: apply_color(p, COLOUR), 2, 0.6),
}


def scene(seed=0, size=(96, 128)):
    """A smooth scene with colour gradients, a few blocks and some grain, as a 16-bit picture."""
    rng = np.random.default_rng(seed)
    h, w = size
    y, x = np.mgrid[0:h, 0:w]
    base = 0.12 + 0.7 * (x / w)[..., None] * np.array([1.0, 0.85, 0.7]) + 0.12 * (y / h)[..., None]
    base[10:40, 12:50] = (0.65, 0.2, 0.18)
    base[55:85, 70:115] = (0.14, 0.45, 0.62)
    return np.clip(np.rint((base + rng.normal(0, 0.006, base.shape)) * 65535), 0, 65535).astype(np.uint16)


def narrow_ramp():
    """A ramp over only ten 8-bit levels (2570 sixteen-bit ones): what a negative's narrow range is before it is stretched."""
    w = 1024
    row = np.linspace(20000, 20000 + 2570, w)
    return np.broadcast_to(np.stack([row, row * 0.97, row * 0.94], axis=1)[None], (40, w, 3)).round().astype(np.uint16).copy()


@pytest.mark.parametrize("name", list(STAGES))
def test_a_16_bit_stage_agrees_with_its_8_bit_twin(name):
    stage, tolerance, average = STAGES[name]
    wide = scene()
    eight = to_uint8(wide)
    lifted = eight.astype(np.uint16) * 257          # the 8-bit picture as exactly the same colours at 16 bits
    result8, result16 = stage(eight), stage(lifted)
    assert result16.dtype == np.uint16 and result16.shape == eight.shape and result8.dtype == np.uint8
    off = np.abs(to_uint8(result16).astype(int) - result8.astype(int))
    assert off.max() <= tolerance and off.mean() < average, (name, int(off.max()), float(off.mean()))
    assert not np.array_equal(result16, lifted), "the stage did something"


@pytest.mark.parametrize("name", list(STAGES))
def test_the_fine_levels_of_a_narrow_range_survive_a_16_bit_stage(name):
    stage = STAGES[name][0]
    ramp = narrow_ramp()
    out16, out8 = stage(ramp), stage(to_uint8(ramp))
    levels16, levels8 = np.unique(out16[..., 1]).size, np.unique(out8[..., 1]).size
    assert levels8 <= 20, "an 8-bit picture of that range has only a handful of levels to give"
    assert levels16 >= 100 and levels16 >= 8 * levels8, (name, levels16, levels8)


def test_a_stage_with_nothing_to_do_returns_the_picture_itself():
    p = scene()
    assert adjust_shadows_highlights(p, 0.0, 0.0) is p and adjust_saturation(p, 0.0) is p and apply_chroma_denoise(p, 0.0) is p
    assert apply_local_contrast(p, 0.0) is p and camera.apply_matrix(p, None) is p and apply_color(p, {}) is p


def test_strips_keep_the_depth_and_give_the_same_picture_as_one_piece():
    from photoeditor.features.shadows_highlights.logic import _apply_gain, gain_table

    tall = scene(2, (400, 96))                     # tall enough to be split into strips
    table = gain_table(0.5, -0.3)
    whole = _apply_gain(tall, table)
    assert adjust_shadows_highlights(tall, 0.5, -0.3).dtype == np.uint16 and np.array_equal(adjust_shadows_highlights(tall, 0.5, -0.3), whole)
    assert adjust_saturation(tall, 0.3).dtype == np.uint16 and adjust_saturation(tall, 0.3).shape == tall.shape


def test_sixteen_bit_lookup_tables():
    ramp = wide_ramp()
    table = wide_ramp_to_lut16(ramp)
    assert table.shape == (3, 65536) and table.dtype == np.uint16 and is_identity(table), "the identity at 16 bits"
    assert wide_ramp_to_lut16(ramp * np.float32(0.5))[0, 65535] == 32768 and wide_ramp_to_lut16(ramp * 2)[0, 65535] == 65535, "255 is 65535, and it clips"
    p = scene()
    assert np.array_equal(apply_wide_lut(p, table), p) and apply_wide_lut(p, table).dtype == np.uint16
    assert np.array_equal(apply_channel_lut(p, table), p), "apply_channel_lut takes a 16-bit table for a 16-bit picture"
    darker = wide_ramp_to_lut16(ramp * np.float32(0.8))
    assert not is_identity(darker) and apply_channel_lut(p, darker).max() <= 52428 and is_identity(np.broadcast_to(np.arange(256, dtype=np.uint8), (3, 256)).copy())
    assert is_identity(np.ascontiguousarray(identity_ramp()[0].T))


def test_the_renderer_keeps_a_16_bit_scan_16_bit_through_the_mixing_stages():
    from photoeditor.desktop.export_worker import default_edit_state
    from photoeditor.desktop.render import EditParams, Renderer

    rng = np.random.default_rng(5)
    h, w = 120, 480
    x = np.linspace(0.0, 1.0, w)[None, :, None] * np.array([1.0, 0.9, 0.8]) + np.linspace(0.0, 0.05, h)[:, None, None]
    scan = np.clip(np.rint((0.55 - 0.18 * x + rng.normal(0, 0.0004, (h, w, 3))) * 65535), 0, 65535).astype(np.uint16)   # a negative: a narrow band of codes
    base = {**default_edit_state(True), "negative_inverted": True, "shadows": 0.4, "saturation": 0.2, "tone_curve_points": [(0, 0), (60, 30), (190, 225), (255, 255)]}
    params = EditParams.from_dict(base)

    def render(deep, wide_mixing=True, **changes):
        renderer = Renderer(); renderer.wide_mixing = wide_mixing
        return renderer.render(scan, dataclasses.replace(params, **changes), "t", w, deep=deep)[0]

    deep = render(True)
    assert deep.dtype == np.uint16 and deep.shape == (h, w, 3), "mixing stages on, nothing 8-bit after them: a 16-bit export keeps its 16 bits"
    assert render(False).dtype == np.uint8
    assert render(True, sharpen_amount=0.5).dtype == np.uint8 and render(True, vignette=0.3).dtype == np.uint8, "a stage that works in 8 bits only gives an 8-bit picture"
    assert np.unique(deep[..., 1]).size > 3 * np.unique(render(True, wide_mixing=False)[..., 1]).size or render(True, wide_mixing=False).dtype == np.uint8

    def gaps(image8):
        used = np.unique(image8[..., 1])
        return int(used.max() - used.min() + 1 - used.size)   # 8-bit levels inside the range that no pixel has: combing in the histogram

    new, old = render(False), render(False, wide_mixing=False)
    assert gaps(new) < gaps(old) and gaps(new) <= 2, (gaps(new), gaps(old))
    assert np.abs(new.astype(int) - old.astype(int)).mean() < 2.0, "the two paths make the same picture, one of them without the gaps"
