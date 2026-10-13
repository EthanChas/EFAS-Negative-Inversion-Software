"""Error marking: the kinds, cleaning stored marks, and mapping a point of the scan back to the picture on screen."""
import itertools
import random

import pytest

from photoeditor.features.errormarks import logic as em
from photoeditor.features.geometry.logic import map_display_to_raw, map_raw_to_display


def test_kinds_have_the_colours_that_were_asked_for():
    colours = {k.id: k.colour for k in em.KINDS}
    assert colours["scratch"] == "#e5484d", "scratches are red"
    assert colours["watermark"] == "#f5d90a", "watermarks are yellow"
    r, g, b = (int(colours["transport"][i:i + 2], 16) for i in (1, 3, 5))
    assert b > r and b > g and max(r, g, b) < 140, "transport lines are dark navy blue"
    assert len(set(colours.values())) == len(colours), "every kind has its own colour"
    assert {"newton", "unknown"} <= set(em.KIND_IDS) and em.DEFAULT_KIND in em.KIND_IDS
    assert em.kind("scratch").label == "Scratches" and em.kind("zzz").id == "unknown"


def test_tag_text_is_readable_on_every_colour():
    assert em.text_colour("#f5d90a") == "#000000" and em.text_colour("#1f2f7a") == "#ffffff" and em.text_colour("#e5484d") == "#ffffff"


def test_clean_keeps_good_marks_and_drops_the_rest():
    good = {"kind": "scratch", "pts": [[0.1, 0.1], [0.2, 0.1], [0.2, 0.2], [0.1, 0.2]]}
    out = em.clean([good, {"kind": "from-the-future", "pts": good["pts"]}, {"kind": "dust", "pts": [[0, 0]]}, "junk", {"kind": "dust"},
                    {"kind": "dust", "pts": [["a", 1], [0, 0], [0, 0], [0, 0]]}, {"kind": "dust", "pts": [[9, 9], [0, 0], [0, 0], [0, 0]]}])
    assert [m["kind"] for m in out] == ["scratch", "unknown"] and out[0] == good and out[0] is not good
    assert em.clean(None) == [] and em.clean("x") == []
    assert len(em.clean([good] * 800)) == em.MAX_MARKS


def test_summary_and_counts():
    marks = [{"kind": "scratch", "pts": []}, {"kind": "scratch", "pts": []}, {"kind": "watermark", "pts": []}]
    assert em.counts(marks) == {"scratch": 2, "watermark": 1}
    assert em.summary(marks) == "3 marks: 2 scratches, 1 watermarks" and em.summary([]) == "No marks on this photo."
    assert em.summary(marks[:1]) == "1 mark: 1 scratches"


@pytest.mark.parametrize("turns,flip_h,flip_v", list(itertools.product(range(4), (False, True), (False, True))))
def test_raw_to_display_undoes_crop_flips_and_turns(turns, flip_h, flip_v):
    frame = (700, 1000)
    crop = (120, 90, 880, 640)
    for u, v in ((0.5, 0.5), (0.1, 0.9), (0.93, 0.07)):
        raw = map_display_to_raw(u, v, crop, frame, turns, flip_h, flip_v)
        back = map_raw_to_display(*raw, crop, frame, turns, flip_h, flip_v)
        assert back == pytest.approx((u, v), abs=1e-9)
    # with no crop too
    raw = map_display_to_raw(0.3, 0.6, None, frame, turns, flip_h, flip_v)
    assert map_raw_to_display(*raw, None, frame, turns, flip_h, flip_v) == pytest.approx((0.3, 0.6), abs=1e-9)


def test_raw_to_display_solves_for_fine_rotation_distortion_and_keystone():
    rng = random.Random(4)
    frame = (700, 1000)
    for _ in range(40):
        crop = (rng.randint(0, 100), rng.randint(0, 100), rng.randint(800, 1000), rng.randint(500, 700)) if rng.random() < 0.7 else None
        args = (crop, frame, rng.randint(0, 3), rng.random() < 0.5, rng.random() < 0.5, rng.uniform(-6, 6), rng.uniform(-0.3, 0.3), rng.uniform(-0.2, 0.2),
                rng.uniform(-0.2, 0.2))
        u, v = rng.uniform(0.05, 0.95), rng.uniform(0.05, 0.95)
        raw = map_display_to_raw(u, v, *args)
        back = map_raw_to_display(*raw, *args)
        assert back == pytest.approx((u, v), abs=1e-5), args


def test_a_point_that_was_cropped_away_maps_outside_the_picture():
    u, v = map_raw_to_display(0.05, 0.5, (400, 0, 900, 700), (700, 1000), 0, False, False)
    assert u < 0
