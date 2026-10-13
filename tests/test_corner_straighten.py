"""Straightening from four clicked corners: the angle, keystone and crop that make the clicked shape an upright rectangle."""
import itertools
import math

import numpy as np
import pytest

from photoeditor.features.geometry.corners import order_corners, straighten_from_corners
from photoeditor.features.geometry.logic import map_display_to_raw, map_raw_to_display

FRAME = (600, 900)  # height, width of the picture as shown
RECT = [(0.12, 0.10), (0.88, 0.10), (0.88, 0.92), (0.12, 0.92)]  # a rectangle in the corrected picture (TL, TR, BR, BL)


def _clicks_for(theta, v, h, dist=0.0, turns=0, flip_h=False, flip_v=False):
    """Where the corners of RECT are in the uncorrected picture, given the true correction (theta, v, h) - what a person would click."""
    dh, dw = FRAME
    frame = (dh, dw)
    raw = [map_display_to_raw(u, w, None, frame, turns, flip_h, flip_v, theta, dist, v, h) for u, w in RECT]
    return [map_raw_to_display(x, y, None, frame, turns, flip_h, flip_v) for x, y in raw]


def test_order_corners_from_any_click_order():
    corners = [(0.1, 0.1), (0.9, 0.12), (0.88, 0.9), (0.12, 0.88)]
    for perm in itertools.permutations(corners):
        assert order_corners(list(perm)) == corners
    # a tilted shape too
    tilted = [(0.2, 0.05), (0.95, 0.2), (0.8, 0.95), (0.05, 0.8)]
    assert order_corners([tilted[2], tilted[0], tilted[3], tilted[1]]) == tilted


@pytest.mark.parametrize("theta,v,h", [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (-2.5, 0.0, 0.0), (1.5, 0.12, 0.0), (-1.0, -0.1, 0.06), (4.0, 0.15, -0.08), (0.0, 0.2, 0.2)])
def test_it_finds_the_correction_that_was_used(theta, v, h):
    result = straighten_from_corners(_clicks_for(theta, v, h), FRAME)
    assert result.fine_rotation == pytest.approx(theta, abs=0.08)
    assert result.keystone_v == pytest.approx(v, abs=0.012) and result.keystone_h == pytest.approx(h, abs=0.012)
    assert result.residual < 0.5 and not result.notes
    # the crop is the rectangle, as pixels of the picture
    x1, y1, x2, y2 = result.crop_rect
    dh, dw = FRAME
    assert x1 == pytest.approx(0.12 * dw, abs=6) and x2 == pytest.approx(0.88 * dw, abs=6)
    assert y1 == pytest.approx(0.10 * dh, abs=6) and y2 == pytest.approx(0.92 * dh, abs=6)


def test_the_picture_that_is_already_corrected_stays_as_it_is():
    result = straighten_from_corners(_clicks_for(0.0, 0.0, 0.0), FRAME, fine_rotation=0.0)
    assert (result.fine_rotation, result.keystone_v, result.keystone_h) == (0.0, 0.0, 0.0)


def test_it_takes_account_of_the_correction_already_on_the_picture():
    # the picture is shown already turned 2 degrees and keystoned; the corners are clicked on that
    theta0, v0 = 2.0, 0.05
    dh, dw = FRAME
    raw = [map_display_to_raw(u, w, None, FRAME, 0, False, False, 4.0, 0.0, 0.1, 0.0) for u, w in RECT]
    clicks = [map_raw_to_display(x, y, None, FRAME, 0, False, False, theta0, 0.0, v0, 0.0) for x, y in raw]
    result = straighten_from_corners(clicks, FRAME, fine_rotation=theta0, keystone_v=v0)
    assert result.fine_rotation == pytest.approx(4.0, abs=0.1) and result.keystone_v == pytest.approx(0.1, abs=0.015), "the total, not an extra step on top"


@pytest.mark.parametrize("turns,flip_h,flip_v", [(0, True, False), (1, False, False), (2, False, True), (3, True, True)])
def test_it_works_on_a_turned_and_flipped_picture(turns, flip_h, flip_v):
    frame = FRAME if turns % 2 == 0 else (FRAME[1], FRAME[0])   # the shown picture's (height, width)
    raw_frame = (FRAME[0], FRAME[1])
    theta, v = 2.0, 0.08
    raw = [map_display_to_raw(u, w, None, frame, turns, flip_h, flip_v, theta, 0.0, v, 0.0) for u, w in RECT]
    clicks = [map_raw_to_display(x, y, None, frame, turns, flip_h, flip_v) for x, y in raw]
    result = straighten_from_corners(clicks, frame, turns, flip_h, flip_v)
    assert result.residual < 1.0
    dh, dw = frame
    x1, y1, x2, y2 = result.crop_rect
    assert 0 <= x1 < x2 <= dw and 0 <= y1 < y2 <= dh and (x2 - x1) > 0.4 * dw


def test_it_works_with_lens_distortion_on():
    result = straighten_from_corners(_clicks_for(2.0, 0.06, 0.0, dist=0.03), FRAME, distortion=0.03)
    assert result.fine_rotation == pytest.approx(2.0, abs=0.15) and result.keystone_v == pytest.approx(0.06, abs=0.02)


def test_points_that_are_not_a_rectangle_get_a_best_fit_and_a_note():
    clicks = [(0.1, 0.1), (0.9, 0.2), (0.7, 0.9), (0.2, 0.7)]   # a lopsided quadrilateral: no angle and keystone make it square
    result = straighten_from_corners(clicks, FRAME)
    assert result.notes and -45 <= result.fine_rotation <= 45 and -1 <= result.keystone_v <= 1


def test_bad_input_is_refused_in_words():
    with pytest.raises(ValueError, match="Four corners"):
        straighten_from_corners([(0, 0), (1, 1)], FRAME)
    with pytest.raises(ValueError, match="too close together"):
        straighten_from_corners([(0.5, 0.5), (0.51, 0.5), (0.51, 0.51), (0.5, 0.51)], FRAME)
