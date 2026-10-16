"""Filing a live session into dated folders and setting a retaken photo aside: the files (and their sidecars) move without being overwritten or deleted, and everything saved
for a photo - edits, rating, flag, tags, versions - and its folder's flat field and Roll Card follow it."""
import os
from datetime import datetime

import numpy as np

from photoeditor.features.livefolder import filing as F
from photoeditor.features.livefolder import logic as L
from photoeditor.features.persistence import edit_store as E


def _photo(path, size=100, when=None, sidecar=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)
    if sidecar:
        with open(path + ".xmp", "w") as f:
            f.write("<x/>")
    if when is not None:
        os.utime(path, (when, when))
    return path


def _stamp(year, month, day, hour=12):
    return datetime(year, month, day, hour).timestamp()


def test_a_photo_moves_with_its_sidecars_and_never_over_another(tmp_path):
    a = _photo(str(tmp_path / "live" / "a.CR2"), sidecar=True)
    to = str(tmp_path / "live" / "16-10-2026" / "a.CR2")
    assert F.move_photo(a, to) == to
    assert not os.path.exists(a) and not os.path.exists(a + ".xmp") and os.path.isfile(to) and os.path.isfile(to + ".xmp")
    b = _photo(str(tmp_path / "live" / "a.CR2"), 7, sidecar=True)
    second = F.move_photo(b, to)
    assert second == str(tmp_path / "live" / "16-10-2026" / "a_1.CR2") and os.path.getsize(to) == 100, "the one already there is untouched"
    assert os.path.isfile(second + ".xmp")


def test_a_session_is_filed_into_a_folder_for_the_day_of_each_photo(tmp_path):
    live = str(tmp_path / "live")
    p1 = _photo(os.path.join(live, "4N0A1.CR2"), when=_stamp(2026, 10, 16))
    p2 = _photo(os.path.join(live, "2026_10_16", "4N0A2.CR2"), when=_stamp(2026, 10, 16))
    p3 = _photo(os.path.join(live, "4N0A3.CR2"), when=_stamp(2026, 10, 17, 1))
    aside = _photo(os.path.join(live, "Retakes", "4N0A1.CR2"), when=_stamp(2026, 10, 16))
    elsewhere = _photo(str(tmp_path / "other" / "x.CR2"), when=_stamp(2026, 10, 16))
    already = _photo(os.path.join(live, "16-10-2026", "4N0A4.CR2"), when=_stamp(2026, 10, 16))
    plan = F.finish_plan([p1, p2, p3, elsewhere, already, os.path.join(live, "gone.CR2")], [aside], [live])
    assert plan == [
        (p1, os.path.join(live, "16-10-2026", "4N0A1.CR2")),
        (p2, os.path.join(live, "16-10-2026", "4N0A2.CR2")),
        (p3, os.path.join(live, "17-10-2026", "4N0A3.CR2")),
        (elsewhere, str(tmp_path / "other" / "16-10-2026" / "x.CR2")),
        (aside, os.path.join(live, "16-10-2026", "Retakes", "4N0A1.CR2")),
    ], "the one already in its day folder and the missing one are left out"


def test_a_retake_takes_the_name_and_place_of_the_photo_and_the_old_one_is_set_aside(tmp_path):
    old = _photo(str(tmp_path / "16-10-2026" / "4N0A7.CR2"), 100, sidecar=True)
    new = _photo(str(tmp_path / "2026_10_16" / "4N0A9.CR2"), 555)
    assert F.retake_names(old, new) == (str(tmp_path / "16-10-2026" / "Retakes" / "4N0A7.CR2"), old)
    aside, target = F.swap_in_retake(old, new)
    assert aside == str(tmp_path / "16-10-2026" / "Retakes" / "4N0A7.CR2") and target == old
    assert os.path.getsize(old) == 555 and not os.path.exists(new), "the retake is in the old photo's place, under its name"
    assert os.path.getsize(aside) == 100 and os.path.isfile(aside + ".xmp") and not os.path.exists(old + ".xmp"), "the old one is kept, with its sidecar"
    again = _photo(str(tmp_path / "2026_10_16" / "4N0A10.CR2"), 777)
    aside2, target2 = F.swap_in_retake(old, again)
    assert aside2 == str(tmp_path / "16-10-2026" / "Retakes" / "4N0A7_1.CR2") and os.path.getsize(aside) == 100, "a second retake does not overwrite the first set-aside photo"
    assert os.path.getsize(target2) == 777


def test_a_retake_in_another_format_keeps_the_stem_and_has_its_own_extension(tmp_path):
    old = _photo(str(tmp_path / "a" / "frame.CR2"))
    new = _photo(str(tmp_path / "b" / "IMG_5.JPG"))
    aside, target = F.swap_in_retake(old, new)
    assert target == str(tmp_path / "a" / "frame.JPG") and os.path.isfile(aside)


def test_the_watch_can_be_told_to_ignore_the_files_the_editor_put_there(tmp_path):
    watch = L.LiveWatch(str(tmp_path), settle_polls=1)
    aside = _photo(str(tmp_path / "Retakes" / "x.CR2"))
    watch.ignore([aside])
    for _ in range(3):
        assert watch.poll() == []


def _db(tmp_path):
    return E.connect(str(tmp_path / "edits.db"))


def test_everything_saved_for_a_photo_follows_it_to_its_new_path(tmp_path):
    conn = _db(tmp_path)
    old, new = str(tmp_path / "live" / "a.CR2"), str(tmp_path / "live" / "16-10-2026" / "a.CR2")
    E.set_rating(conn, old, 4)
    E.set_flag(conn, old, E.FLAG_KEEPER)
    E.add_tags(conn, [old], ["family"])
    E.hide_photos(conn, [old])
    E.move_photo_records(conn, old, new)
    assert E.get_ratings(conn, [old, new]) == {new: 4}
    assert E.get_flags(conn, [old, new]) == {new: E.FLAG_KEEPER}
    assert E.get_tags(conn, [old, new]) == {new: ["family"]}
    assert E.hidden_paths(conn) == [new]


def test_copying_records_leaves_the_original_and_forgetting_the_judgement_clears_rating_and_flag(tmp_path):
    conn = _db(tmp_path)
    old, other = str(tmp_path / "a.CR2"), str(tmp_path / "Retakes" / "a.CR2")
    E.set_rating(conn, old, 2)
    E.set_flag(conn, old, E.FLAG_REJECTED)
    E.add_tags(conn, [old], ["blurry"])
    E.copy_photo_records(conn, old, other)
    assert E.get_ratings(conn, [old, other]) == {old: 2, other: 2}
    E.forget_judgement(conn, old)
    assert E.get_ratings(conn, [old, other]) == {other: 2} and E.get_flags(conn, [old, other]) == {other: E.FLAG_REJECTED}
    assert E.get_tags(conn, [old, other]) == {old: ["blurry"], other: ["blurry"]}, "tags stay with the photo that is in the place"


def test_the_flat_field_and_roll_card_of_a_folder_are_given_to_the_folder_photos_move_into(tmp_path):
    conn = _db(tmp_path)
    live = E.folder_key(str(tmp_path / "live"), is_file=False)
    day = E.folder_key(str(tmp_path / "live" / "16-10-2026"), is_file=False)
    taken = E.folder_key(str(tmp_path / "live" / "17-10-2026"), is_file=False)
    E.set_folder_flatfield(conn, live, np.ones((4, 4, 3), np.float32), source="ref.CR2")
    E.set_folder_roll(conn, live, {"film": "Portra 400"})
    E.set_folder_roll(conn, taken, {"film": "its own"})
    E.copy_folder_records(conn, live, day)
    E.copy_folder_records(conn, live, taken)
    assert E.get_folder_flatfield(conn, day)["source"] == "ref.CR2" and E.get_folder_roll(conn, day) == {"film": "Portra 400"}
    assert E.get_folder_roll(conn, taken) == {"film": "its own"}, "a folder that has its own is left alone"
    assert E.get_folder_flatfield(conn, live) is not None, "the live folder keeps its own"
