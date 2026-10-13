"""Crop Roll > Make every crop the same size: the shared size is worked out per orientation, odd frames are left alone, and the roll-undo step follows."""
import os

import cv2
import numpy as np
import pytest

from photoeditor.features.geometry import stabilize as st


def test_orientation_groups_and_median_size():
    found = [(1000, 700, (100, 100, 900, 600)), (1000, 700, (110, 90, 905, 604)), (1000, 700, (95, 105, 895, 598)), (700, 1000, (50, 80, 650, 920)),
             (700, 1000, (60, 70, 660, 905))]
    shared = st.targets(found)
    assert set(shared) == {"landscape", "portrait"}
    land = shared["landscape"]
    assert land.median_width == pytest.approx(0.8, abs=0.01) and land.median_height == pytest.approx(0.714, abs=0.01)
    assert land.width <= land.median_width and land.height <= land.median_height, "the shared size never takes in more than most frames had"


def test_each_crop_gets_the_shared_size_centred_where_it_was_found():
    found = [(1000, 700, (100, 100, 900, 600)), (1000, 700, (110, 90, 905, 604)), (1000, 700, (95, 105, 895, 598))]
    shared = st.targets(found)
    sizes = set()
    for w, h, rect in found:
        new = st.stabilize(rect, w, h, shared)
        sizes.add((new[2] - new[0], new[3] - new[1]))
        assert abs((new[0] + new[2]) / 2 - (rect[0] + rect[2]) / 2) <= 1 and abs((new[1] + new[3]) / 2 - (rect[1] + rect[3]) / 2) <= 1
        assert 0 <= new[0] < new[2] <= w and 0 <= new[1] < new[3] <= h
    assert len(sizes) == 1, sizes


def test_a_crop_at_the_edge_moves_inward_instead_of_leaving_the_frame():
    shared = st.targets([(1000, 700, (0, 0, 800, 500)), (1000, 700, (10, 10, 800, 500)), (1000, 700, (200, 100, 1000, 600))])
    for rect in ((0, 0, 800, 500), (200, 100, 1000, 600)):
        new = st.stabilize(rect, 1000, 700, shared)
        assert 0 <= new[0] and new[2] <= 1000 and 0 <= new[1] and new[3] <= 700


def test_odd_frames_and_single_frames_are_left_alone():
    ordinary = [(1000, 700, (100, 100, 900, 600)), (1000, 700, (102, 98, 902, 599)), (1000, 700, (98, 101, 898, 601))]
    half = (1000, 700, (100, 100, 500, 350))   # a half-frame: nowhere near the usual size
    shared = st.targets(ordinary + [half])
    assert st.stabilize(half[2], 1000, 700, shared) == half[2]
    assert st.targets([ordinary[0]]) == {} and st.stabilize(ordinary[0][2], 1000, 700, {}) == ordinary[0][2]
    assert st.targets([(1000, 700, (0, 0, 0, 0)), (0, 0, (1, 1, 2, 2))]) == {}


def test_a_group_of_orientation_is_not_stabilised_by_the_other():
    shared = st.targets([(1000, 700, (100, 100, 900, 600)), (1000, 700, (102, 100, 902, 600)), (700, 1000, (50, 50, 650, 950))])
    assert "portrait" not in shared, "one portrait frame has nothing to share a size with"
    assert st.stabilize((50, 50, 650, 950), 700, 1000, shared) == (50, 50, 650, 950)


def _roll(folder, sizes):
    """Frames with a dark border and a textured picture of the given (width, height) in the middle, each slightly off-centre by a different amount."""
    paths = []
    for i, (pw, ph) in enumerate(sizes):
        img = np.full((300, 420, 3), 25, np.uint8)
        rng = np.random.default_rng(i)
        pic = cv2.GaussianBlur(rng.random((ph, pw, 3)).astype(np.float32), (0, 0), 4)
        pic = (90 + 110 * (pic - pic.min()) / np.ptp(pic)).astype(np.uint8)
        x, y = (420 - pw) // 2 + i, (300 - ph) // 2 - i
        img[y:y + ph, x:x + pw] = pic
        path = os.path.join(folder, f"f{i}.png")
        cv2.imwrite(path, img)
        paths.append(path)
    return paths


@pytest.fixture
def roll(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path / "data"))
    os.makedirs(tmp_path / "data", exist_ok=True)
    folder = tmp_path / "roll"
    folder.mkdir()
    paths = _roll(str(folder), [(260, 180), (250, 176), (268, 184), (256, 178)])
    db = str(tmp_path / "data" / "photo-edits.db")
    from photoeditor.features.persistence import edit_store

    edit_store.connect(db).close()
    return paths, db


def _rects(paths, db):
    from photoeditor.features.persistence import edit_store

    conn = edit_store.connect(db)
    try:
        return [tuple(edit_store.load_edit_state(conn, p)["crop_rect"]) for p in paths]
    finally:
        conn.close()


def test_crop_roll_makes_the_crops_one_size_and_keeps_the_undo_step_true(roll):
    from photoeditor.desktop import bulk_crop

    paths, db = roll
    plain = bulk_crop.run("auto", paths, db)
    own = _rects(paths, db)
    assert len({(r[2] - r[0], r[3] - r[1]) for r in own}) > 1, "without it each crop is the size of its own border"
    bulk_crop.run("reset", paths, db)
    summary = bulk_crop.run("auto", paths, db, same_size=True)
    rects = _rects(paths, db)
    assert len(summary["done"]) == 4 and len({(r[2] - r[0], r[3] - r[1]) for r in rects}) == 1, rects
    assert len(summary["resized"]) >= 1 and "landscape" in summary["shared"]
    for op, rect in zip(summary["ops"], rects):
        assert tuple(op["after"]["crop_rect"]) == rect, "undo records the crop that was finally saved"
    # each crop still sits on its own picture
    for own_rect, new_rect in zip(own, rects):
        assert abs((own_rect[0] + own_rect[2]) - (new_rect[0] + new_rect[2])) <= 2 and abs((own_rect[1] + own_rect[3]) - (new_rect[1] + new_rect[3])) <= 2
    assert plain["resized"] == []


def test_crop_roll_same_size_leaves_a_small_odd_frame_as_found(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path / "data"))
    os.makedirs(tmp_path / "data", exist_ok=True)
    folder = tmp_path / "roll"
    folder.mkdir()
    paths = _roll(str(folder), [(260, 180), (262, 181), (258, 179), (190, 130)])
    db = str(tmp_path / "data" / "photo-edits.db")
    from photoeditor.desktop import bulk_crop
    from photoeditor.features.persistence import edit_store

    edit_store.connect(db).close()
    bulk_crop.run("auto", paths, db)
    before = _rects(paths, db)
    bulk_crop.run("reset", paths, db)
    bulk_crop.run("auto", paths, db, same_size=True)
    after = _rects(paths, db)
    assert after[3] == before[3], "the odd one keeps the crop it was found with"
    assert len({(r[2] - r[0], r[3] - r[1]) for r in after[:3]}) == 1
