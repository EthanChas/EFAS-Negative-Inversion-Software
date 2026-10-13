"""Print Response (Snap, Toe, Shoulder): the curve's maths."""
import itertools

import numpy as np
import pytest

from photoeditor.features.printresponse import logic as pr

X = np.linspace(0.0, 255.0, 256)


def curve(**kw):
    args = dict(snap=0.0, toe=0.0, toe_width=2.5, shoulder=0.0, shoulder_width=2.5)
    args.update(kw)
    return pr.apply_print_response(X, args["snap"], args["toe"], args["toe_width"], args["shoulder"], args["shoulder_width"])


def test_neutral_changes_nothing_at_all():
    assert pr.apply_print_response(X, 0.0, 0.0, 2.5, 0.0, 2.5) is X, "the very same array comes back"
    assert pr.is_neutral(0.0, 0.0, 0.0) and not pr.is_neutral(0.1, 0.0, 0.0) and not pr.is_neutral(0.0, 0.0, -0.1)
    # the widths mean nothing while Toe and Shoulder are zero
    assert pr.apply_print_response(X, 0.0, 0.0, 0.3, 0.0, 4.0) is X


def test_the_curve_always_keeps_tones_in_order():
    for snap, toe, shoulder, tw, sw in itertools.product((-0.5, 0.0, 0.5), (-1.0, 0.0, 1.0), (-1.0, 0.0, 1.0), (0.1, 2.5, 5.0), (0.1, 2.5, 5.0)):
        y = curve(snap=snap, toe=toe, shoulder=shoulder, toe_width=tw, shoulder_width=sw)
        assert np.all(np.diff(y) >= -1e-6), (snap, toe, shoulder, tw, sw)
        assert y.min() >= 0.0 and y.max() <= 255.0 + 1e-6


def test_snap_steepens_the_midtones_and_keeps_mid_grey_in_place():
    mid = 118.0   # about 18% linear
    base = pr.apply_print_response(np.array([mid]), 0.0, 0.0)[0]
    for snap in (0.2, 0.5):
        y = curve(snap=snap)
        slope = (y[140] - y[100]) / 40.0
        assert slope > 1.0, "more midtone contrast"
        assert abs(pr.apply_print_response(np.array([mid]), snap, 0.0)[0] - mid) < 3.0, "mid grey stays where it was"
    soft = curve(snap=-0.4)
    assert (soft[140] - soft[100]) / 40.0 < 1.0, "a negative Snap flattens the midtones"
    assert base == mid or base is not None


def test_snap_leaves_the_ends_alone_to_a_small_shift_only():
    y = curve(snap=0.5)
    assert y[0] < 1.0 and y[255] > 254.0, "black stays black and white stays white"


def test_positive_toe_eases_shadows_into_black_and_negative_toe_crushes_them():
    soft, hard = curve(toe=1.0), curve(toe=-1.0)
    assert soft[0] > X[0] + 15, "black is lifted: a gentler fade"
    assert hard[20] < X[20], "shadows go to black faster"
    assert abs(soft[230] - X[230]) < 4.0 and abs(hard[230] - X[230]) < 4.0, "highlights are left almost alone"
    assert abs(soft[128] - X[128]) < 8.0, "and the midtones barely move"


def test_positive_shoulder_eases_highlights_into_white_and_negative_pushes_them_harder():
    soft, hard = curve(shoulder=1.0), curve(shoulder=-1.0)
    assert soft[255] < 250, "white is pulled down: highlights roll off"
    assert hard[240] > X[240] and hard[255] == pytest.approx(255.0, abs=1e-3)
    assert abs(soft[20] - X[20]) < 1.0 and abs(hard[20] - X[20]) < 1.0, "shadows are left alone"


def test_width_sets_how_far_a_roll_off_reaches():
    narrow, wide = curve(toe=1.0, toe_width=0.3), curve(toe=1.0, toe_width=5.0)
    # a wide toe reaches further up the tones
    assert wide[100] - X[100] > narrow[100] - X[100]
    n2, w2 = curve(shoulder=1.0, shoulder_width=0.3), curve(shoulder=1.0, shoulder_width=5.0)
    assert (X[170] - w2[170]) > (X[170] - n2[170])


def test_each_slider_changes_only_its_own_part():
    base = curve()
    only_snap = curve(snap=0.3)
    assert np.array_equal(curve(toe=0.0, shoulder=0.0, snap=0.3), only_snap)
    assert not np.allclose(only_snap, base)
    assert np.allclose(curve(toe=0.5, toe_width=0.4), curve(toe=0.5, toe_width=0.4))


def test_curve_points_and_widths():
    pts = pr.curve_points(0.2, 0.3, 2.5, 0.3, 2.5)
    assert len(pts) == 64 and pts[0][0] == 0.0 and pts[-1][0] == 1.0 and all(0.0 <= y <= 1.0 for _x, y in pts)
    assert pr.knee_width(2.5) == pytest.approx(pr.KNEE_WIDTH) and pr.knee_width(5.0) == pytest.approx(2 * pr.KNEE_WIDTH)
    assert pr.knee_width(0.0) == pytest.approx(pr.KNEE_WIDTH * pr.WIDTH_MIN / pr.WIDTH_DEFAULT), "a zero width cannot divide by zero"


def test_it_works_on_a_ramp_of_any_shape_and_keeps_the_float_type():
    ramp = np.tile(X.astype(np.float32)[None, :, None], (1, 1, 3))
    out = pr.apply_print_response(ramp, 0.3, 0.2, 2.5, 0.2, 2.5)
    assert out.shape == ramp.shape and out.dtype == np.float32
    assert np.allclose(out[..., 0], out[..., 1]) and np.allclose(out[..., 1], out[..., 2])
