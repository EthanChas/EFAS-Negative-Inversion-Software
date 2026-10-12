"""Deleting one auto-detected speck leaves it in the picture and every other detection repaired; Reset brings them back."""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
from photoeditor.features.retouch.logic import apply_exclusions, detect_dust_masks, drop_marked, remove_dust_and_scratches  # noqa: E402

SPECKS = [(200, 150), (600, 400), (450, 520)]
W, H = 900, 600


def scan():
    rng = np.random.default_rng(5)
    base = cv2.GaussianBlur(rng.random((H, W, 3)).astype(np.float32), (0, 0), 25)
    img = (110 + 60 * (base - base.min()) / np.ptp(base)).astype(np.uint8)
    img = np.clip(img.astype(int) + rng.normal(0, 2, img.shape), 0, 255).astype(np.uint8)
    for x, y in SPECKS:
        cv2.circle(img, (x, y), 3, (30, 30, 30), -1)
    return img


def frac(p):
    return (p[0] / W, p[1] / H)


def components(mask):
    return int(cv2.connectedComponents(np.ascontiguousarray(mask > 0, dtype=np.uint8))[0] - 1)


def at(img, p, r=2):
    x, y = p
    return img[y - r:y + r + 1, x - r:x + r + 1].astype(int).mean()


def test_drop_marked_removes_only_the_region_at_the_point():
    mask = np.zeros((100, 200), np.uint8)
    mask[10:20, 10:20] = 1
    mask[50:60, 100:110] = 1
    mask[80:90, 150:160] = 1
    out = drop_marked(mask, [(15 / 200, 15 / 100)], slack_px=2)
    assert out[10:20, 10:20].sum() == 0 and out[50:60, 100:110].sum() == 100 and out[80:90, 150:160].sum() == 100
    assert drop_marked(mask, [(0.5, 0.2)], slack_px=2) is mask or np.array_equal(drop_marked(mask, [(0.5, 0.2)], slack_px=2), mask), "a click on nothing changes nothing"
    both = drop_marked(mask, [(15 / 200, 15 / 100), (105 / 200, 55 / 100)])
    assert both.sum() == 100
    assert drop_marked(None, [(0.1, 0.1)]) is None and drop_marked(mask, []) is mask
    near = drop_marked(mask, [(21 / 200, 15 / 100)], slack_px=2)
    assert near[10:20, 10:20].sum() == 0, "a click just beside a region counts as on it"


def test_detection_overlay_loses_only_the_deleted_one():
    img = scan()
    full = detect_dust_masks(img, threshold=0.5, size=4)
    assert components(full.specks) == 3
    some = detect_dust_masks(img, threshold=0.5, size=4, excluded=[frac(SPECKS[1])])
    assert components(some.specks) == 2
    sh, sw = some.specks.shape
    assert some.specks[int(400 / H * sh), int(600 / W * sw)] == 0, "the deleted speck is no longer marked"
    assert some.specks[int(150 / H * sh), int(200 / W * sw)] == 1 and some.specks[int(520 / H * sh), int(450 / W * sw)] == 1
    none = detect_dust_masks(img, threshold=0.5, size=4, excluded=[frac(p) for p in SPECKS])
    assert none.specks is None or components(none.specks) == 0


def test_a_deleted_detection_is_left_in_the_picture_the_others_are_repaired():
    img = scan()
    out = remove_dust_and_scratches(img, auto=True, threshold=0.5, size=4, excluded=[frac(SPECKS[1])])
    assert at(out.pixels, SPECKS[1]) < 50, "the deleted one is still there, as it was"
    assert at(out.pixels, SPECKS[0]) > 90 and at(out.pixels, SPECKS[2]) > 90, "the others were repaired"
    plain = remove_dust_and_scratches(img, auto=True, threshold=0.5, size=4)
    assert all(at(plain.pixels, p) > 90 for p in SPECKS), "with nothing deleted, all three are repaired"
    away = remove_dust_and_scratches(img, auto=True, threshold=0.5, size=4, excluded=[(0.9, 0.05)])
    assert np.array_equal(away.pixels, plain.pixels), "a point where nothing was found changes nothing"
    # everything outside the deleted speck is the same as in the all-repaired picture
    mask = np.ones((H, W), bool)
    mask[400 - 40:400 + 40, 600 - 40:600 + 40] = False
    assert np.abs(out.pixels.astype(int) - plain.pixels.astype(int))[mask].max() <= 2


def test_it_survives_a_change_of_threshold():
    img = scan()
    for threshold in (0.3, 0.5, 0.7):
        out = remove_dust_and_scratches(img, auto=True, threshold=threshold, size=4, excluded=[frac(SPECKS[1])])
        assert at(out.pixels, SPECKS[1]) < 50, threshold


def test_ai_mask_regions_can_be_deleted_too():
    img = scan()
    ai = np.zeros((H, W), np.uint8)
    for x, y in SPECKS:
        cv2.circle(ai, (x, y), 6, 1, -1)
    out = remove_dust_and_scratches(img, auto=False, ai_mask=ai, excluded=[frac(SPECKS[0])])
    assert at(out.pixels, SPECKS[0]) < 50 and at(out.pixels, SPECKS[1]) > 90 and at(out.pixels, SPECKS[2]) > 90


def test_apply_exclusions_with_nothing_found():
    assert apply_exclusions(None, None, [(0.5, 0.5)]) == (None, None)
    score = np.ones((50, 50), np.float32)
    s2, h2 = apply_exclusions(score, None, [(0.5, 0.5)])
    assert (s2 >= 1).all() and h2 is None
