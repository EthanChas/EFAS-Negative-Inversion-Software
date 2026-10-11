"""Keystone correction (features/geometry): the warp, its point mapping, and the automatic suggestion on synthetic scenes with known tilt."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photoeditor.features.geometry import keystone_detect as kd  # noqa: E402
from photoeditor.features.geometry import logic as G  # noqa: E402

H, W = 600, 900


def grid(spacing_x=90, spacing_y=75, thickness=3, seed=0):
    img = np.zeros((H, W), np.uint8)
    rng = np.random.default_rng(seed)
    for x in range(spacing_x // 2, W, spacing_x):
        img[:, x:x + thickness] = 255
    for y in range(spacing_y // 2, H, spacing_y):
        img[y:y + thickness, :] = 255
    img[rng.random((H, W)) < 0.002] = 255
    return img


def tilted(scene, v, h):
    """The scene as a tilted camera would have recorded it: keystone(result, v, h) gives the scene back."""
    import cv2

    m = G._keystone_matrix(v, h, W, H)
    return cv2.warpPerspective(scene, m, (W, H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_CONSTANT)


def test_no_correction_returns_the_same_picture_object():
    a = np.zeros((10, 10, 3), np.uint8)
    assert G.keystone(a, 0.0, 0.0) is a and G.unkeystone_point(0.3, 0.4, 0.0, 0.0, 10, 10) == (0.3, 0.4)


def test_the_quad_insets_the_edge_that_the_sign_names():
    top = G.keystone_quad(0.5, 0.0)
    assert top[0, 0] == pytest.approx(0.15) and top[1, 0] == pytest.approx(0.85) and top[2, 0] == 1.0 and top[3, 0] == 0.0
    bottom = G.keystone_quad(-1.0, 0.0)
    assert bottom[2, 0] == pytest.approx(0.7) and bottom[3, 0] == pytest.approx(0.3) and bottom[0, 0] == 0.0
    left = G.keystone_quad(0.0, 1.0)
    assert left[0, 1] == pytest.approx(0.3) and left[3, 1] == pytest.approx(0.7) and left[1, 1] == 0.0
    assert np.allclose(G.keystone_quad(5, -5), G.keystone_quad(1, -1)), "values are limited to the slider range"


def test_corrected_pictures_have_no_empty_corners_and_keep_their_size():
    scene = np.full((H, W, 3), 128, np.uint8)
    out = G.keystone(scene, 0.8, -0.6)
    assert out.shape == scene.shape and out.min() == 128


def test_a_point_maps_back_to_where_it_came_from():
    for v, h in ((0.4, 0.0), (-0.5, 0.3), (0.2, -0.7)):
        m = G._keystone_matrix(v, h, W, H)
        src = np.array([0.31 * (W - 1), 0.62 * (H - 1), 1.0])
        x, y, z = m @ src
        back = G.unkeystone_point(x / z / (W - 1), y / z / (H - 1), v, h, W, H)
        assert back == pytest.approx((0.31, 0.62), abs=1e-6)


def test_display_to_raw_undoes_keystone_before_distortion_and_rotation():
    plain = G.map_display_to_raw(0.4, 0.6, None, (H, W), 0, False, False, 0.0, 0.0)
    assert plain == (0.4, 0.6)
    moved = G.map_display_to_raw(0.4, 0.6, None, (H, W), 0, False, False, 0.0, 0.0, 0.5, 0.0)
    assert moved == G.unkeystone_point(0.4, 0.6, 0.5, 0.0, W, H) and moved != plain


@pytest.mark.parametrize("v,h", [(0.5, 0.0), (-0.5, 0.0), (0.0, 0.5), (0.0, -0.4), (0.4, 0.3)])
def test_the_suggestion_recovers_the_tilt_that_was_put_in(v, h):
    s = kd.suggest_keystone(tilted(grid(), v, h))
    assert s.found()
    assert s.v == pytest.approx(v, abs=0.05) and s.h == pytest.approx(h, abs=0.05), (s, v, h)


def test_applying_the_suggestion_makes_lines_parallel_again():
    d = tilted(grid(), 0.5, 0.0)
    s = kd.suggest_keystone(d)
    fixed = G.keystone(d, s.v, s.h)
    again = kd.suggest_keystone(fixed)
    assert abs(again.v) < 0.1 and abs(again.h) < 0.1


def test_a_straight_scene_and_a_scene_without_lines_get_no_suggestion():
    assert not kd.suggest_keystone(grid()).found()
    noise = (np.random.default_rng(1).random((H, W)) * 255).astype(np.uint8)
    s = kd.suggest_keystone(noise)
    assert not s.found() and s.notes


def test_lines_in_one_corner_only_are_not_enough():
    img = np.zeros((H, W), np.uint8)
    for x in (30, 60, 90, 120, 150):
        img[0:300, x:x + 3] = 255
    s = kd.suggest_keystone(img)
    assert not s.found() and any("one part" in n or "Too few" in n for n in s.notes)
