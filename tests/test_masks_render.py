"""A module blended through a mask, in the render: it acts only inside the mask, at the opacity, with the mask's polarity - and the mask lies on the same part of the picture whether it was cropped,
rotated, flipped or straightened afterwards. Without a mask nothing changes."""
import dataclasses

import numpy as np

from photoeditor.desktop.render import EditParams, Renderer
from photoeditor.desktop.session import AppState
from photoeditor.features.masks import blend as B
from photoeditor.features.masks import model as M
from photoeditor.features.masks import state as S

W, H = 400, 300


def _scan(seed=1):
    rng = np.random.default_rng(seed)
    base = np.linspace(40, 200, W, dtype=np.float32)[None, :, None] * np.ones((H, 1, 3), np.float32)
    return np.clip(base + rng.normal(0, 6, (H, W, 3)), 0, 255).astype(np.uint8)


def _params(masks=None, blends=None, **kw):
    p = dataclasses.replace(EditParams.from_state(AppState()), negative_inverted=False)
    p = dataclasses.replace(p, masks_json=S.masks_json(masks.to_dict()) if masks is not None else "", blends=S.blends_tuple({k: v.to_dict() for k, v in (blends or {}).items()}), **kw)
    return p


def _render(scan, params):
    return Renderer().render(scan, params, "mask-test", scan.shape[1])[0]


def _circle_masks(x=0.3, y=0.5, radius=0.15, border=0.02):
    ms = M.MaskSet()
    ms.add(M.CIRCLE, M.circle(x, y, radius, border))
    return ms, 1


def test_without_a_mask_nothing_changes():
    scan = _scan()
    plain = _render(scan, _params(exposure_ev=0.8))
    again = _render(scan, _params(M.MaskSet(), {}, exposure_ev=0.8))
    assert np.array_equal(plain, again)


def test_a_uniform_blend_at_full_opacity_is_the_same_picture_made_one_module_at_a_time():
    scan = _scan()
    values = dict(exposure_ev=0.7, contrast=0.3, temperature=0.2, saturation=0.3, shadows=0.2, highlights=-0.2)
    fused = _render(scan, _params(**values))
    staged = _render(scan, _params(blends={"exposure": B.Blend(mode=B.UNIFORM, opacity=100.0)}, **values))
    diff = np.abs(fused.astype(int) - staged.astype(int))
    assert diff.max() <= 4 and diff.mean() < 0.6, (diff.max(), diff.mean())


def test_a_module_acts_only_inside_its_drawn_mask():
    scan = _scan()
    ms, mid = _circle_masks()
    plain = _render(scan, _params())
    lifted = _render(scan, _params(exposure_ev=1.0))
    blended = _render(scan, _params(ms, {"exposure": B.Blend(mode=B.DRAWN, mask_id=mid)}, exposure_ev=1.0))
    cx, cy = int(0.3 * W), int(0.5 * H)
    assert blended[cy, cx].astype(int).sum() > plain[cy, cx].astype(int).sum() + 30, "brighter inside the circle"
    assert np.abs(blended[cy, cx].astype(int) - lifted[cy, cx].astype(int)).max() <= 3, "as bright as the whole picture lifted"
    assert np.abs(blended[:, 300:].astype(int) - plain[:, 300:].astype(int)).max() <= 3, "and untouched far from it"
    half = _render(scan, _params(ms, {"exposure": B.Blend(mode=B.DRAWN, mask_id=mid, opacity=50.0)}, exposure_ev=1.0))
    mid_value = (plain[cy, cx].astype(int) + lifted[cy, cx].astype(int)) / 2
    assert np.abs(half[cy, cx] - mid_value).max() <= 4, "opacity 50% is halfway"
    inverted = _render(scan, _params(ms, {"exposure": B.Blend(mode=B.DRAWN, mask_id=mid, invert=True)}, exposure_ev=1.0))
    assert np.abs(inverted[cy, cx].astype(int) - plain[cy, cx].astype(int)).max() <= 3 and np.abs(inverted[:, 300:].astype(int) - lifted[:, 300:].astype(int)).max() <= 3, "polarity swaps inside and out"
    uniform = _render(scan, _params(blends={"exposure": B.Blend(mode=B.UNIFORM, opacity=50.0)}, exposure_ev=1.0))
    assert np.abs(uniform[10, 10].astype(int) - ((plain[10, 10].astype(int) + lifted[10, 10].astype(int)) / 2)).max() <= 4, "uniformly: half everywhere"


def test_the_mask_stays_on_the_picture_when_it_is_cropped_turned_flipped_or_straightened():
    scan = _scan()
    ms, mid = _circle_masks(0.3, 0.5, 0.12, 0.02)
    blend = {"exposure": B.Blend(mode=B.DRAWN, mask_id=mid)}

    def lit_centre(**geometry):
        plain = _render(scan, _params(**geometry)).astype(int).sum(axis=2)
        masked = _render(scan, _params(ms, blend, exposure_ev=1.2, **geometry)).astype(int).sum(axis=2)
        diff = masked - plain
        ys, xs = np.nonzero(diff > 25)
        assert len(xs) > 200, "something is lit"
        return xs.mean() / plain.shape[1], ys.mean() / plain.shape[0]

    x, y = lit_centre()
    assert abs(x - 0.3) < 0.03 and abs(y - 0.5) < 0.03
    x, y = lit_centre(flip_h=True)
    assert abs(x - 0.7) < 0.03 and abs(y - 0.5) < 0.03, "flipped with the picture"
    x, y = lit_centre(flip_v=True)
    assert abs(x - 0.3) < 0.03 and abs(y - 0.5) < 0.03
    x, y = lit_centre(rotation_quarter_turns=1)    # a quarter turn clockwise: (0.3, 0.5) -> (0.5, 0.3)
    assert abs(x - 0.5) < 0.03 and abs(y - 0.3) < 0.03, (x, y)
    x, y = lit_centre(crop_rect=(40, 30, 280, 270))   # a crop of the frame (pixels): the circle is still where it was, in the crop's own terms
    assert abs(x - (0.3 * W - 40) / 240) < 0.04 and abs(y - (0.5 * H - 30) / 240) < 0.04, (x, y)
    x, y = lit_centre(fine_rotation=8.0)
    assert 0.0 < x < 0.5 and 0.2 < y < 0.8, "straightened with the picture"
    assert abs(x - 0.3) > 0.005 or abs(y - 0.5) > 0.005, (x, y)


def test_the_modules_after_the_colour_and_on_the_crop_can_be_blended_too():
    scan = _scan()
    ms, mid = _circle_masks(0.3, 0.5, 0.15, 0.02)
    cx, cy = int(0.3 * W), int(0.5 * H)
    drawn = lambda: B.Blend(mode=B.DRAWN, mask_id=mid)
    plain = _render(scan, _params(sharpen_amount=1.0, sharpen_radius=1.5, sharpen_method="usm")).astype(int)
    with_mask = _render(scan, _params(ms, {"sharpening": drawn()}, sharpen_amount=1.0, sharpen_radius=1.5, sharpen_method="usm")).astype(int)
    none = _render(scan, _params()).astype(int)
    away = np.s_[:, 300:]
    assert np.abs(with_mask[away] - none[away]).max() <= 1, "far from the mask, sharpening is not applied"
    near = np.s_[cy - 15:cy + 15, cx - 15:cx + 15]
    assert np.abs(with_mask[near] - plain[near]).mean() < 1.0 and np.abs(with_mask[near] - none[near]).mean() > 1.0, "inside it, it is"
    ec = dict(ec_warmth=0.8, ec_size=0.5)
    edge_plain = _render(scan, _params(**ec)).astype(int)
    edge_masked = _render(scan, _params(ms, {"edgecolor": drawn()}, **ec)).astype(int)
    assert np.abs(edge_masked[away] - none[away]).max() <= 1 and np.abs(edge_plain - none).max() > 3, "edge colour on the cropped picture, only inside the mask"
    hal = dict(hal_amount=0.9, hal_threshold=0.3)
    h_plain = _render(scan, _params(**hal)).astype(int)
    h_masked = _render(scan, _params(ms, {"halation": drawn()}, **hal)).astype(int)
    assert np.abs(h_masked[away] - none[away]).max() <= 1 and np.abs(h_plain[away] - none[away]).max() > 3


def test_the_colour_modules_can_be_blended_each_on_its_own():
    scan = _scan()
    ms, mid = _circle_masks(0.3, 0.5, 0.15, 0.02)
    cx, cy = int(0.3 * W), int(0.5 * H)
    away = np.s_[:, 300:]
    none = _render(scan, _params()).astype(int)
    for key, kw in (("contrast", dict(contrast=0.8)), ("color", dict(saturation=0.9, temperature=0.4)), ("shadows_highlights", dict(shadows=0.8, highlights=-0.6)),
                    ("colormixer", dict(vibrance=0.8, mix_sat_red=0.6)), ("colortoning", dict(tone_hue_mids=200.0, tone_amt_mids=0.8)), ("denoise", dict(chroma_denoise=3.0)),
                    ("localcontrast", dict(local_contrast=0.9)), ("lablook", dict(lab_fade=0.6, lab_by_mids=0.7)), ("printresponse", dict(print_snap=0.6, print_toe=0.5)),
                    ("tonecurve", dict(tone_curve_points=((0, 0), (128, 60), (255, 255))))):
        full = _render(scan, _params(**kw)).astype(int)
        masked = _render(scan, _params(ms, {key: B.Blend(mode=B.DRAWN, mask_id=mid)}, **kw)).astype(int)
        assert np.abs(full - none).max() > 3, f"{key}: the setting does something"
        assert np.abs(masked[away] - none[away]).max() <= 3, f"{key}: untouched away from the mask ({np.abs(masked[away] - none[away]).max()})"
        near = np.s_[cy - 12:cy + 12, cx - 12:cx + 12]
        assert np.abs(masked[near] - full[near]).mean() < np.abs(masked[near] - none[near]).mean() + 1e-9 or np.abs(full[near] - none[near]).mean() < 0.3, f"{key}: applied inside it"


def test_a_sixteen_bit_scan_is_blended_too():
    scan16 = (_scan().astype(np.uint16) * 257)
    ms, mid = _circle_masks()
    plain = _render(scan16, _params(exposure_ev=1.0))
    blended = _render(scan16, _params(ms, {"exposure": B.Blend(mode=B.DRAWN, mask_id=mid)}, exposure_ev=1.0))
    assert blended.dtype == np.uint8 and blended.shape == plain.shape
    cx, cy = int(0.3 * W), int(0.5 * H)
    assert abs(int(blended[cy, cx, 0]) - int(plain[cy, cx, 0])) <= 3 and int(blended[10, 390, 0]) != int(plain[10, 390, 0])


def test_a_blend_pointing_at_a_mask_that_is_gone_applies_everywhere():
    scan = _scan()
    lifted = _render(scan, _params(exposure_ev=1.0))
    gone = _render(scan, _params(M.MaskSet(), {"exposure": B.Blend(mode=B.DRAWN, mask_id=99)}, exposure_ev=1.0))
    assert np.abs(gone.astype(int) - lifted.astype(int)).max() <= 4, "darktable's rule: a drawn mask with no shape is everywhere"
    inv = _render(scan, _params(M.MaskSet(), {"exposure": B.Blend(mode=B.DRAWN, mask_id=99, invert=True)}, exposure_ev=1.0))
    assert np.abs(inv.astype(int) - _render(scan, _params()).astype(int)).max() <= 4, "and inverted, nowhere"
