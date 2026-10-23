"""Retouch (the darktable port): the wavelet split puts the picture back together, clone / heal / blur / fill do what they say on the shapes they are given, and the scale a shape is on decides
what it acts on."""
import numpy as np

from photoeditor.features.retouchdt import bilateral, dwt, heal as H
from photoeditor.features.retouchdt import logic as R


def _disc(h, w, cx, cy, r, feather=2.0):
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.hypot(xx - cx, yy - cy)
    return np.clip((r + feather - d) / feather, 0.0, 1.0).astype(np.float32)


def _ctx(masks, deltas=None, opacity=1.0, view="", ps=1.0):
    return R.Context(lambda i: masks.get(i), lambda i: (deltas or {}).get(i), lambda i: opacity, ps, view)


def _textured(h=120, w=160, seed=3):
    rng = np.random.default_rng(seed)
    base = np.linspace(60, 180, w, dtype=np.float32)[None, :, None] * np.ones((h, 1, 3), np.float32)
    return np.clip(base + rng.normal(0, 6, (h, w, 3)), 0, 255).astype(np.uint8)


def test_the_layers_add_up_to_the_picture():
    rng = np.random.default_rng(1)
    img = rng.random((90, 130, 3)).astype(np.float32)
    for scales, merge in ((1, 0), (4, 0), (5, 3), (6, 1)):
        back, used = dwt.decompose(img.copy(), scales, None, 0, merge)
        assert used == scales and np.abs(back - img).max() < 1e-4, (scales, merge, np.abs(back - img).max())


def test_a_detail_layer_has_no_overall_brightness_and_the_residual_has_it():
    img = np.full((64, 64, 3), 0.5, np.float32) + np.random.default_rng(2).normal(0, 0.05, (64, 64, 3)).astype(np.float32)
    detail, _ = dwt.decompose(img.copy(), 3, None, 1, 0)
    resid, _ = dwt.decompose(img.copy(), 3, None, 4, 0)
    assert abs(float(detail.mean())) < 0.01 and abs(float(resid.mean()) - 0.5) < 0.02
    assert detail.std() > 0.03 and resid.std() < detail.std(), "the finest layer carries the grain, the residual is smooth"


def test_the_scales_a_picture_takes_are_limited_by_its_size():
    assert dwt.scales_for(64, 64) < dwt.scales_for(4000, 3000)
    assert dwt.scales_for(4000, 3000) >= 10 and dwt.first_scale_visible(8, 1.0) == 1 and dwt.first_scale_visible(8, 0.25) == 3
    img = np.zeros((40, 40, 3), np.float32)
    _, used = dwt.decompose(img, 12, None, 0, 0)
    assert used == dwt.scales_for(40, 40)


def test_clone_copies_the_source_over_the_shape():
    img = _textured()
    img[40:46, 100:106] = 250                                   # a bright blemish
    masks = {1: _disc(120, 160, 103, 43, 6.0)}
    out = R.process(img, R.Settings([R.FormSetting(1, 0, R.CLONE)]), _ctx(masks, {1: (30, 0)}))   # the source is 30 pixels to the left of the shape
    before, after = img[40:46, 100:106].mean(), out[40:46, 100:106].mean()
    assert before > 240 and after < 140, (before, after)
    assert np.array_equal(out[:, :90], img[:, :90]) and np.array_equal(out[80:], img[80:]), "nothing outside the shape is touched"
    half = R.process(img, R.Settings([R.FormSetting(1, 0, R.CLONE)]), _ctx(masks, {1: (30, 0)}, opacity=0.5))
    assert after < half[40:46, 100:106].mean() < before, "the shape's opacity sets how much of the source is let in"


def test_heal_fits_the_source_to_what_is_round_the_shape():
    h, w = 120, 160
    rng = np.random.default_rng(5)
    img = np.clip(100 + rng.normal(0, 4, (h, w, 3)), 0, 255).astype(np.uint8)
    img[:, :70] = np.clip(img[:, :70].astype(int) + 70, 0, 255)       # the source lies on a brighter part of the picture
    mask = _disc(h, w, 110, 60, 12.0)
    ctx = _ctx({1: mask}, {1: (60, 0)})
    cloned = R.process(img, R.Settings([R.FormSetting(1, 0, R.CLONE)]), ctx)
    healed = R.process(img, R.Settings([R.FormSetting(1, 0, R.HEAL)]), ctx)
    inside = (slice(52, 69), slice(102, 119))
    around = img[40:80, 120:140].mean()
    assert abs(float(cloned[inside].mean()) - around) > 40, "a plain copy brings the source's brightness with it"
    assert abs(float(healed[inside].mean()) - around) < 8, (healed[inside].mean(), around)
    assert healed[inside].std() > 1.5, "but keeps the texture"


def test_heal_leaves_pixels_outside_the_mask_alone_and_ends_early_when_it_has_settled():
    src = np.zeros((20, 20, 3), np.float32)
    dest = np.full((20, 20, 3), 0.4, np.float32)
    mask = np.zeros((20, 20), np.float32)
    mask[8:12, 8:12] = 1.0
    out = H.heal(src, dest, mask, 5000)
    assert np.allclose(out[mask == 0], 0.4) and np.allclose(out[8:12, 8:12], 0.4, atol=0.01)


def test_blur_smooths_inside_the_shape_only():
    img = _textured()
    mask = {1: _disc(120, 160, 80, 60, 25.0)}
    out = R.process(img, R.Settings([R.FormSetting(1, 0, R.BLUR, blur_radius=8.0)]), _ctx(mask))
    rough = lambda a: np.abs(np.diff(a[45:75, 65:95].astype(float), axis=1)).mean()
    assert rough(out) < 0.5 * rough(img), (rough(out), rough(img))
    assert np.array_equal(out[:, :40], img[:, :40])
    bi = R.process(img, R.Settings([R.FormSetting(1, 0, R.BLUR, blur_type=R.BILATERAL, blur_radius=8.0)]), _ctx(mask))
    assert np.array_equal(bi[:, :40], img[:, :40]) and not np.array_equal(bi, img)
    assert R.process(img, R.Settings([R.FormSetting(1, 0, R.BLUR, blur_radius=0.1)]), _ctx(mask)) is img, "a radius of 0.1 or less does nothing"


def test_the_bilateral_grid_smooths_lightness_and_keeps_an_edge():
    h, w = 80, 80
    rng = np.random.default_rng(0)
    lab = np.zeros((h, w, 3))
    lab[..., 0] = np.where(np.arange(w)[None, :] < 40, 30.0, 70.0) + rng.normal(0, 1.5, (h, w))
    out = bilateral.bilateral_lightness(lab, 4.0)
    flat = out[:, 5:30, 0]
    assert flat.std() < lab[:, 5:30, 0].std(), "the noise is smoothed"
    assert out[:, 45:75, 0].mean() - out[:, 5:35, 0].mean() > 35, "and the step between the two tones stays"
    rgb = np.random.default_rng(1).random((10, 10, 3))
    assert np.abs(bilateral.lab_to_rgb(bilateral.rgb_to_lab(rgb)) - rgb).max() < 1e-6


def test_fill_paints_the_shape_with_a_colour_or_erases_it():
    img = _textured()
    mask = {1: _disc(120, 160, 80, 60, 20.0, feather=0.5)}
    red = R.process(img, R.Settings([R.FormSetting(1, 0, R.FILL, fill_mode=R.COLOR, fill_color=[1.0, 0.0, 0.0])]), _ctx(mask))
    assert tuple(red[60, 80]) == (255, 0, 0)
    black = R.process(img, R.Settings([R.FormSetting(1, 0, R.FILL, fill_mode=R.ERASE)]), _ctx(mask))
    assert tuple(black[60, 80]) == (0, 0, 0)
    lit = R.process(img, R.Settings([R.FormSetting(1, 0, R.FILL, fill_mode=R.ERASE, fill_brightness=0.2)]), _ctx(mask))
    assert 100 < lit[60, 80, 0] < 140


def test_a_shape_on_a_detail_scale_only_changes_that_scale():
    """Blurring the finest detail layer smooths grain and leaves the broad tones; blurring the residual does the opposite."""
    h, w = 128, 128
    rng = np.random.default_rng(4)
    grain = rng.normal(0, 8, (h, w, 1)).astype(np.float32)
    broad = (np.sin(np.arange(w) / 9.0)[None, :, None] * 40).astype(np.float32) * np.ones((h, 1, 1), np.float32)
    img = np.clip(120 + grain + broad, 0, 255).astype(np.uint8) * np.ones((1, 1, 3), np.uint8)
    full = {1: np.ones((h, w), np.float32)}
    fine = R.process(img, R.Settings([R.FormSetting(1, 1, R.BLUR, blur_radius=40.0)], num_scales=3), _ctx(full))
    resid = R.process(img, R.Settings([R.FormSetting(1, 4, R.BLUR, blur_radius=40.0)], num_scales=3), _ctx(full))
    low = lambda a: np.abs(np.cumsum(a[..., 0].astype(float).mean(axis=0)))[-1]
    hf = lambda a: np.abs(np.diff(a[..., 0].astype(float), axis=1)).mean()
    assert hf(fine) < 0.8 * hf(img), "the grain went"
    assert abs(float(fine[..., 0].mean(axis=0).std()) - float(img[..., 0].mean(axis=0).std())) < 6, "the broad swell stayed"
    assert hf(resid) > 0.7 * hf(img), "the grain stayed"


def test_viewing_a_scale_shows_that_layer_and_suppress_shows_the_picture_without_retouch():
    img = _textured()
    masks = {1: _disc(120, 160, 80, 60, 20.0)}
    s = R.Settings([R.FormSetting(1, 0, R.FILL, fill_mode=R.COLOR, fill_color=[1.0, 0.0, 0.0])], num_scales=3, curr_scale=1)
    assert R.process(img, s, _ctx(masks, view="suppress")) is img
    layer = R.process(img, s, _ctx(masks, view="scale"))
    assert layer.shape == img.shape and not np.array_equal(layer, img)
    shown = R.process(img, R.Settings([R.FormSetting(1, 1, R.BLUR)], num_scales=3, curr_scale=1), _ctx(masks, view="mask"))
    assert shown[60, 80, 0] > shown[5, 5, 0] and shown[60, 80, 2] < shown[60, 80, 0], "yellow where the shape acts"
    assert R.auto_levels(np.random.default_rng(0).normal(0, 0.02, (20, 20, 3)).astype(np.float32))[0] < R.auto_levels(np.random.default_rng(0).normal(0, 0.02, (20, 20, 3)).astype(np.float32))[2]


def test_settings_are_cleaned_when_read_back():
    s = R.Settings.from_dict({"forms": [{"formid": 3, "scale": 99, "algorithm": "bogus", "blur_radius": -5}, {"formid": 3}, {"formid": "x"}, 7], "num_scales": 40, "merge_from_scale": 90,
                              "preview_levels": ["a"], "fill_color": "no"})
    assert len(s.forms) == 1 and s.forms[0].scale == R.MAX_SCALES + 1 and s.forms[0].algorithm == R.HEAL and s.forms[0].blur_radius == 0.1
    assert s.num_scales == R.MAX_SCALES and s.merge_from_scale == R.MAX_SCALES and s.preview_levels == [R.PREVIEW_LVL_MIN, 0.0, R.PREVIEW_LVL_MAX]
    assert R.Settings.from_dict(s.to_dict()).to_dict() == s.to_dict() and R.is_neutral(None) and R.is_neutral({"forms": []})


def test_a_wavelet_scale_can_be_looked_at_before_any_shape_is_on_it():
    img = _textured()
    s = R.Settings(num_scales=3, curr_scale=2)
    assert R.process(img, s, _ctx({})) is img, "with no shapes and no view the picture is as it was"
    shown = R.process(img, s, _ctx({}, view="scale"))
    assert shown.shape == img.shape and not np.array_equal(shown, img), "the layer is shown"
    assert R.to_json(s.to_dict()) != "" and R.to_json(R.Settings().to_dict()) == "", "settings other than the starting ones reach the renderer even without shapes"
    resid = R.process(img, R.Settings(num_scales=3, curr_scale=4), _ctx({}, view="scale"))
    assert abs(float(resid.mean()) - float(img.mean())) < 40, "the residual is the broad light of the picture"


def test_mask_properties_read_and_change_the_picked_shape():
    from photoeditor.features.masks import model as M
    from photoeditor.features.masks import properties as P
    ms = M.MaskSet()
    c = ms.add(M.CIRCLE, M.circle(0.5, 0.5, 0.05, 0.02))
    b = ms.add(M.BRUSH, [M.brush_node(0.1, 0.1), M.brush_node(0.2, 0.2)])
    e = ms.add(M.ELLIPSE, M.ellipse(0.5, 0.5, 0.06, 0.03))
    g = ms.add(M.GRADIENT, M.gradient(0.5, 0.5))
    assert P.available(M.CIRCLE) == ("size", "feather") and "hardness" in P.available(M.BRUSH) and P.available(M.GROUP) == ()
    assert P.read(c)["size"] == 0.05 and P.apply(c, "size", 0.2)[0]["radius"] == 0.2 and P.apply(c, "hardness", 0.5) is None
    assert abs(P.read(b)["size"] - 0.1) < 1e-9 and all(n["border"][0] == 0.15 for n in P.apply(b, "size", 0.3))
    pts = P.apply(e, "size", 0.12)
    assert pts[0]["radius"][0] == 0.12 and abs(pts[0]["radius"][1] - 0.06) < 1e-9, "an ellipse keeps its shape when it is resized"
    assert P.apply(g, "curvature", 9.0)[0]["curvature"] == 2.0, "values are held to the limits"
