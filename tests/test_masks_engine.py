"""The mask engine, ported from darktable's masks: the shapes (their numbers and fall-offs), how a group combines them, how a mask is saved and read back, and how a module is blended through it."""
import json
import math

import numpy as np
import pytest

from photoeditor.features.masks import blend as B
from photoeditor.features.masks import model as M
from photoeditor.features.masks import raster as R


def _mask(form_type, points, w=400, h=300):
    ms = M.MaskSet()
    form = ms.add(form_type, points)
    return ms, form, R.render_mask(ms, form.id, w, h)


# ------------------------------------------------------------------ the shapes
def test_a_circle_is_one_inside_and_falls_off_with_darktables_law():
    ms, form, m = _mask(M.CIRCLE, M.circle(0.5, 0.5, 0.1, 0.1))   # on a 400 x 300 frame: radius 30 px, outer edge 60 px (sizes are fractions of the shorter side)
    assert m.shape == (300, 400) and m.dtype == np.float32
    assert m[150, 200] == 1.0 and m[150, 200 + 25] == 1.0, "one inside the radius"
    assert m[150, 200 + 60] == 0.0 and m[0, 0] == 0.0, "nothing past the feathered edge"
    # darktable: f = (total^2 - l^2) / (total^2 - radius^2), the mask is f squared
    d = 45.5
    f = (60.0 ** 2 - d ** 2) / (60.0 ** 2 - 30.0 ** 2)
    assert abs(m[150, 200 + 45] - f * f) < 0.02, (m[150, 200 + 45], f * f)
    assert abs(m[150, 200 + 45] - m[150, 200 - 46]) < 0.02, "round"
    left = R.render_mask(ms, form.id, 400, 300)
    assert np.array_equal(left, m), "drawing is repeatable"


def test_an_ellipse_has_its_two_radii_its_rotation_and_either_kind_of_feather():
    ms, form, m = _mask(M.ELLIPSE, M.ellipse(0.5, 0.5, 0.2, 0.1, 0.0, 0.05))   # radii 60 and 30 px, feather 15 px, long axis along x
    assert m[150, 200 + 58] == 1.0 and m[150, 200 + 70] > 0.0 and m[150, 200 + 76] == 0.0
    assert m[150 + 28, 200] == 1.0 and m[150 + 50, 200] == 0.0, "the short radius up and down"
    ms2, _f, turned = _mask(M.ELLIPSE, M.ellipse(0.5, 0.5, 0.2, 0.1, 90.0, 0.05))
    assert turned[150 + 58, 200] == 1.0 and turned[150, 200 + 50] == 0.0, "rotation 90 puts the long axis up and down"
    ms3, _f, prop = _mask(M.ELLIPSE, M.ellipse(0.5, 0.5, 0.2, 0.1, 0.0, 0.5, M.ELLIPSE_PROPORTIONAL))   # the feather is half the radius: 30 px along x, 15 px along y
    assert prop[150, 200 + 85] > 0.0 and prop[150, 200 + 92] == 0.0 and prop[150 + 44, 200] > 0.0 and prop[150 + 47, 200] == 0.0, 'proportional feather: half of each radius'


def test_a_gradient_ramps_across_the_picture_and_turns_and_bends():
    ms, form, m = _mask(M.GRADIENT, M.gradient(0.5, 0.5, 0.0, 0.2))
    assert m[5, 200] > 0.95 and m[295, 200] < 0.05 and abs(m[150, 200] - 0.5) < 0.05, "a ramp from the top (1) to the bottom (0) at rotation 0"
    assert np.allclose(m[:, 10], m[:, 390], atol=1e-4), "the same all along the ramp"
    _ms, _f, side = _mask(M.GRADIENT, M.gradient(0.5, 0.5, 90.0, 0.2))
    assert side[150, 5] > 0.95 and side[150, 395] < 0.05, "rotation 90 turns it to run across"
    _ms, _f, bent = _mask(M.GRADIENT, M.gradient(0.5, 0.5, 0.0, 0.2, curvature=1.5))
    assert abs(bent[150, 200] - bent[150, 5]) > 0.01, "curvature bends the line"
    _ms, _f, linear = _mask(M.GRADIENT, M.gradient(0.5, 0.5, 0.0, 0.5, state=M.GRADIENT_LINEAR))
    assert abs(linear[150, 200] - 0.5) < 0.05 and linear[60, 200] > 0.65 and linear[240, 200] < 0.35 and abs((linear[130, 200] + linear[170, 200]) - 1.0) < 0.05, "linear: symmetric about the anchor"


def test_a_path_is_one_inside_and_falls_off_linearly_outside():
    square = [M.path_node(0.3, 0.3, 0.05, False), M.path_node(0.7, 0.3, 0.05, False), M.path_node(0.7, 0.7, 0.05, False), M.path_node(0.3, 0.7, 0.05, False)]
    ms, form, m = _mask(M.PATH, square)   # the square is x 120..280, y 90..210; the feather is 15 px
    assert m[150, 200] == 1.0 and m[100, 130] == 1.0
    assert abs(m[150, 120 - 8] - (1 - 8 / 15)) < 0.1, m[150, 112]
    assert m[150, 120 - 20] == 0.0 and m[2, 2] == 0.0
    assert m[150, 112] > m[150, 109] > m[150, 107] > 0.0, "it fades the further out you go"
    assert float(R.render_mask(ms, form.id, 400, 300).sum()) == float(m.sum())
    two = M.MaskSet().add(M.PATH, square[:2])
    ms2 = M.MaskSet(); ms2.forms[1] = two
    assert not R.render_mask(ms2, 1, 400, 300).any(), "fewer than three nodes is no shape"


def test_a_path_through_smooth_nodes_is_rounded():
    smooth = [M.path_node(0.3, 0.3, 0.05), M.path_node(0.7, 0.3, 0.05), M.path_node(0.7, 0.7, 0.05), M.path_node(0.3, 0.7, 0.05)]
    ms, form, m = _mask(M.PATH, smooth)
    assert m[150, 200] == 1.0
    hard = _mask(M.PATH, [M.path_node(0.3, 0.3, 0.05, False), M.path_node(0.7, 0.3, 0.05, False), M.path_node(0.7, 0.7, 0.05, False), M.path_node(0.3, 0.7, 0.05, False)])[2]
    assert not np.array_equal(m, hard)
    c1, c2 = R.smooth_handles(np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]), True)
    assert np.allclose(c2[1] - c1[1], ([10.0, 10.0] - np.array([0.0, 0.0])) / 3.0) and np.allclose((c1[1] + c2[1]) / 2, [10.0, 0.0]), "the handles sit either side of the corner, along (next - previous)"


def test_a_brush_stroke_has_a_hard_core_a_soft_edge_round_ends_and_a_density():
    ms, form, m = _mask(M.BRUSH, [M.brush_node(0.2, 0.5, 0.05, 0.5, 1.0), M.brush_node(0.8, 0.5, 0.05, 0.5, 1.0)])   # size 15 px, hardness 0.5: solid within 7.5 px of the line
    assert m[150, 200] == 1.0 and m[150 - 6, 200] == 1.0, "solid core"
    assert 0.2 < m[150 - 11, 200] < 0.9 and m[150 - 16, 200] == 0.0, "softening to the size"
    assert m[150, 80 - 8] > 0.5 and m[150, 80 - 20] == 0.0, "round end"
    faint = _mask(M.BRUSH, [M.brush_node(0.2, 0.5, 0.05, 0.5, 0.4), M.brush_node(0.8, 0.5, 0.05, 0.5, 0.4)])[2]
    assert abs(faint[150, 200] - 0.4) < 1e-6, "density scales the stroke"
    dab = _mask(M.BRUSH, [M.brush_node(0.5, 0.5, 0.05, 1.0, 1.0)])[2]
    assert dab[150, 200] == 1.0 and dab[150, 200 + 20] == 0.0, "one node is a dab"
    hard = _mask(M.BRUSH, [M.brush_node(0.5, 0.5, 0.05, 1.0, 1.0)])[2]
    assert hard[150, 200 + 14] == 1.0, "hardness 1 is solid to the edge"


# ------------------------------------------------------------------ groups
def _arrays():
    return np.array([[0.0, 0.5, 1.0, 0.25]], np.float32), np.array([[1.0, 0.5, 0.0, 0.75]], np.float32)


def test_a_group_combines_its_shapes_by_darktables_formulas():
    a, b = _arrays()
    U, I, D, S, X, INV = M.STATE_UNION, M.STATE_INTERSECTION, M.STATE_DIFFERENCE, M.STATE_SUM, M.STATE_EXCLUSION, M.STATE_INVERSE
    assert np.allclose(R.combine(a.copy(), b, U, 1.0), [[1.0, 0.5, 1.0, 0.75]]), "union is the larger"
    assert np.allclose(R.combine(a.copy(), b, U, 0.5), [[0.5, 0.5, 1.0, 0.375]]), "scaled by the shape's opacity first"
    assert np.allclose(R.combine(a.copy(), b, I, 1.0), [[0.0, 0.5, 0.0, 0.25]]), "intersection is the smaller, and only where both are there"
    assert np.allclose(R.combine(a.copy(), b, D, 1.0), [[0.0, 0.25, 1.0, 0.0625]]), "difference takes the shape away: a x (1 - b) where both are positive"
    assert np.allclose(R.combine(a.copy(), b, S, 1.0), [[1.0, 1.0, 1.0, 1.0]]), "sum adds, to at most one"
    x = R.combine(a.copy(), b, X, 1.0)
    assert np.allclose(x, [[1.0, 0.25, 1.0, 0.5625]]), x   # where both are there: the larger of (1 - a) x b and a x (1 - b)
    assert np.allclose(R.combine(a.copy(), b, U | INV, 1.0), [[0.0, 0.5, 1.0, 0.25]]), "inverted: the shape is one minus itself, so the union with a is the larger of a and 1 - b"
    assert np.allclose(R.combine(np.zeros((1, 4), np.float32), b, M.STATE_USE, 0.8), [[0.8, 0.4, 0.0, 0.6]]), "no operation: just this shape at its opacity"


def test_a_group_of_shapes_is_a_mask_of_its_own():
    ms = M.MaskSet()
    left = ms.add(M.CIRCLE, M.circle(0.3, 0.5, 0.1, 0.01))
    right = ms.add(M.CIRCLE, M.circle(0.7, 0.5, 0.1, 0.01))
    group = ms.add_group([left.id, right.id], "both")
    both = R.render_mask(ms, group.id, 400, 300)
    assert both[150, 120] == 1.0 and both[150, 280] == 1.0 and both[150, 200] == 0.0
    ms.set_element(group.id, right.id, op=M.STATE_DIFFERENCE)
    cut = R.render_mask(ms, group.id, 400, 300)
    assert cut[150, 120] == 1.0 and cut[150, 280] == 0.0, "the second shape is taken away"
    ms.set_element(group.id, right.id, op=M.STATE_UNION, inverse=True)
    inverted = R.render_mask(ms, group.id, 400, 300)
    assert inverted[150, 200] == 1.0 and inverted[150, 280] == 1.0 * 0 + inverted[150, 280], "the union with the inverse of the right circle covers everything but it"
    ms.set_element(group.id, left.id, opacity=0.5)
    half = R.render_mask(ms, group.id, 400, 300)
    assert abs(half[150, 120] - 0.5) < 1e-6 or half[150, 120] == 1.0, "a shape's opacity scales it (the other may still cover the spot)"
    inner = ms.add_group([group.id], "inside")
    assert np.array_equal(R.render_mask(ms, inner.id, 400, 300), half), "a group inside a group"


def test_a_big_picture_is_drawn_smaller_and_enlarged():
    ms, form, m = _mask(M.CIRCLE, M.circle(0.5, 0.5, 0.1, 0.1), 6000, 4000)
    assert m.shape == (4000, 6000) and m[2000, 3000] == 1.0 and m[0, 0] == 0.0
    assert R.render_mask(ms, 999, 100, 100) is None, "no such mask"


# ------------------------------------------------------------------ saving
def test_masks_are_saved_and_read_back_and_a_damaged_file_cannot_break_them():
    ms = M.MaskSet()
    ms.add(M.CIRCLE, M.circle(0.4, 0.4))
    ms.add(M.ELLIPSE, M.ellipse(0.5, 0.5))
    ms.add(M.PATH, [M.path_node(0.1, 0.1), M.path_node(0.5, 0.1), M.path_node(0.3, 0.5)])
    ms.add(M.BRUSH, [M.brush_node(0.2, 0.2), M.brush_node(0.4, 0.4)])
    ms.add(M.GRADIENT, M.gradient(0.5, 0.5))
    ms.add_group([1, 2, 3], "mine")
    back = M.MaskSet.from_json(ms.to_json())
    assert back == ms and back.next_id == ms.next_id and [f.name for f in back.shapes()] == [f.name for f in ms.shapes()]
    ms.remove(2)
    fresh = ms.add(M.CIRCLE, M.circle(0.1, 0.1))
    assert fresh.id == 7, "a deleted form's id is not used again"
    assert all(p["formid"] != 2 for p in ms.get(6).points), "and it leaves the groups it was in"
    # a damaged file
    assert M.MaskSet.from_json("not json") == M.MaskSet() and M.MaskSet.from_json(None) == M.MaskSet() and M.MaskSet.from_json("[]") == M.MaskSet()
    bad = {"next_id": "x", "forms": [{"id": 1, "type": "circle", "name": "c", "points": [{"center": [float("nan"), "z"], "radius": 99, "border": -3}]},
                                      {"id": 2, "type": "nonsense", "points": []}, {"id": -3, "type": "circle", "points": [{}]}, {"id": 4, "type": "group", "points": [{"formid": 4}, {"formid": 1}, {"formid": 77}]}, 5, None]}
    got = M.MaskSet.from_dict(bad)
    c = got.get(1)
    assert c is not None and got.get(2) is None and got.get(-3) is None
    assert c.points[0]["center"] == [0.5, 0.5] and c.points[0]["radius"] == 1.0 and c.points[0]["border"] == M.MIN_CIRCLE_BORDER, c.points
    assert [p["formid"] for p in got.get(4).points] == [1], "a group keeps only elements that point at forms that exist, and not itself"
    assert got.next_id >= 5
    # nothing a saved edit can hold makes drawing fail
    for f in got.forms.values():
        R.render_mask(got, f.id, 120, 80)


def test_a_group_may_not_hold_itself():
    ms = M.MaskSet()
    c = ms.add(M.CIRCLE, M.circle(0.5, 0.5))
    a = ms.add_group([c.id], "a")
    b = ms.add_group([a.id], "b")
    assert not ms.add_to_group(a.id, b.id) and not ms.add_to_group(a.id, a.id), "no loops"
    assert ms.add_to_group(b.id, c.id) and ms.remove_from_group(b.id, c.id)
    assert ms.duplicate(c.id).points == c.points and ms.duplicate(a.id) is None


# ------------------------------------------------------------------ blending a module through a mask
def test_the_blend_makes_a_mask_in_darktables_order_and_mixes_through_it():
    shape = (60, 80)
    drawn = np.zeros(shape, np.float32); drawn[:, 40:] = 1.0
    assert not B.Blend().active() and B.Blend(mode=B.UNIFORM).active() and B.Blend(mode=B.DRAWN).uses_mask()
    m = B.make_mask(B.Blend(mode=B.DRAWN, opacity=60.0), shape, drawn)
    assert np.allclose(m[:, :40], 0.0) and np.allclose(m[:, 40:], 0.6), "opacity scales the drawn mask"
    inv = B.make_mask(B.Blend(mode=B.DRAWN, invert=True), shape, drawn)
    assert np.allclose(inv[:, :40], 1.0) and np.allclose(inv[:, 40:], 0.0), "polarity"
    assert np.allclose(B.make_mask(B.Blend(mode=B.UNIFORM, opacity=30.0), shape), 0.3)
    assert np.allclose(B.make_mask(B.Blend(mode=B.DRAWN), shape, None), 1.0) and np.allclose(B.make_mask(B.Blend(mode=B.DRAWN, invert=True), shape, None), 0.0), "no mask chosen: everywhere"
    soft = B.make_mask(B.Blend(mode=B.DRAWN, blur=3.0), shape, drawn)
    assert 0.2 < soft[30, 40] < 0.8 and soft[30, 5] < 0.01 and soft[30, 75] > 0.99, "blur softens the edge"
    twice = B.make_mask(B.Blend(mode=B.DRAWN, blur=3.0), shape, drawn, scale=2.0)
    assert abs(twice[30, 44] - soft[30, 44]) > 1e-3, "the blur radius follows the picture's size"
    hard = B.make_mask(B.Blend(mode=B.DRAWN, contrast=0.9), shape, soft)
    assert hard[30, 38] < soft[30, 38] or hard[30, 41] > soft[30, 41], "contrast steepens the mask's edge"
    bright = B.make_mask(B.Blend(mode=B.DRAWN, brightness=0.5), shape, soft)
    assert bright[30, 36] >= soft[30, 36] and float(bright.mean()) > float(soft.mean()), "brightness lifts it"
    base = np.full((60, 80, 3), 100, np.uint8)
    result = np.full((60, 80, 3), 200, np.uint8)
    out = B.blend_images(base, result, m)
    assert out.dtype == np.uint8 and (out[:, :40] == 100).all() and (out[:, 40:] == 160).all(), "base + (result - base) x mask"
    wide = B.blend_images(base.astype(np.uint16) * 257, result.astype(np.uint16) * 257, m)
    assert wide.dtype == np.uint16 and abs(int(wide[0, 60, 0]) - 160 * 257) <= 2
    shown = B.mask_overlay(base, m)
    assert shown.shape == base.shape and shown[0, 60, 0] > shown[0, 60, 2] + 30 and abs(int(shown[0, 5, 0]) - int(shown[0, 5, 2])) <= 1, "yellow where the mask is, grey elsewhere"


def test_the_feather_follows_the_pictures_edges():
    shape = (80, 120)
    guide = np.zeros((80, 120, 3), np.uint8); guide[:, 60:] = 255      # a hard edge in the picture at x = 60
    drawn = np.zeros(shape, np.float32); drawn[:, 54:] = 1.0            # a mask whose edge is 6 pixels off it
    plain = B.make_mask(B.Blend(mode=B.DRAWN), shape, drawn)
    pulled = B.make_mask(B.Blend(mode=B.DRAWN, feather=6.0), shape, drawn, guide=guide)
    assert pulled.shape == shape and pulled.dtype == np.float32 and 0.0 <= pulled.min() and pulled.max() <= 1.0
    assert abs(float(pulled[40, 57]) - float(plain[40, 57])) > 0.2, "the mask's edge moved towards the picture's"


def test_blends_are_saved_and_checked():
    blends = {"exposure": B.Blend(mode=B.DRAWN, mask_id=3, opacity=70.0, invert=True, blur=4.0), "color": B.Blend()}
    saved = B.blends_to_dict(blends)
    assert list(saved) == ["exposure"], "only the active ones are kept"
    assert B.blends_from_dict(json.loads(json.dumps(saved))) == {"exposure": blends["exposure"]}
    got = B.blends_from_dict({"x": {"mode": "drawn", "opacity": 5000, "blur": float("nan"), "mask_id": "no"}, 7: {"mode": "drawn"}, "y": "text", "z": {"mode": "nonsense"}})
    assert list(got) == ["x"] and got["x"].opacity == 100.0 and got["x"].blur == 0.0 and got["x"].mask_id == 0
