"""The live folder's watch: what was there is not news, a photo is reported once and only when its file has stopped growing, and sub-folders (EOS Utility's day folders) count."""
import os

from photoeditor.features.livefolder import logic as L


def _write(path, size=100, mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_photos_that_were_there_already_are_not_news(tmp_path):
    _write(str(tmp_path / "old.CR2"))
    watch = L.LiveWatch(str(tmp_path))
    assert watch.poll() == [] and watch.poll() == [] and watch.poll() == []


def test_a_new_photo_is_reported_once_after_it_stops_changing(tmp_path):
    watch = L.LiveWatch(str(tmp_path), settle_polls=2)
    new = str(tmp_path / "4N0A7869.CR2")
    _write(new)
    assert watch.poll() == [] and watch.pending() == 1, "seen for the first time: not yet"
    assert watch.poll() == [], "unchanged once"
    assert watch.poll() == [new], "unchanged twice: complete"
    assert watch.poll() == [] and watch.poll() == [] and watch.pending() == 0, "reported once only"


def test_a_file_that_is_still_growing_waits(tmp_path):
    watch = L.LiveWatch(str(tmp_path), settle_polls=2)
    new = str(tmp_path / "frame.CR2")
    _write(new, 100, mtime=1_700_000_000)
    watch.poll(); watch.poll()
    _write(new, 5000, mtime=1_700_000_005)   # more of it arrived
    assert watch.poll() == [], "it changed, so the count starts again"
    assert watch.poll() == []
    assert watch.poll() == [new]


def test_the_day_folders_of_eos_utility_count(tmp_path):
    watch = L.LiveWatch(str(tmp_path), settle_polls=1)
    new = str(tmp_path / "2026_10_16" / "4N0A7870.CR2")
    _write(new)
    watch.poll()
    assert watch.poll() == [new]


def test_other_files_empty_files_and_temporary_names_are_ignored(tmp_path):
    watch = L.LiveWatch(str(tmp_path), settle_polls=1)
    _write(str(tmp_path / "notes.txt")); _write(str(tmp_path / "frame.CR2.tmp")); _write(str(tmp_path / "empty.CR2"), 0)
    for _ in range(4):
        assert watch.poll() == []
    assert watch.pending() == 1, "only the empty photo is being waited on"


def test_a_temporary_name_that_is_renamed_is_reported_under_its_final_name(tmp_path):
    watch = L.LiveWatch(str(tmp_path), settle_polls=1)
    temp = tmp_path / "frame.CR2"
    _write(str(temp), 100, mtime=1_700_000_000)
    watch.poll()
    os.remove(temp)
    assert watch.poll() == [] and watch.pending() == 0, "it vanished before it was complete: forgotten"
    _write(str(tmp_path / "final.CR2"), 100, mtime=1_700_000_001)
    watch.poll()
    assert watch.poll() == [str(tmp_path / "final.CR2")]


def test_several_at_once_come_oldest_first(tmp_path):
    watch = L.LiveWatch(str(tmp_path), settle_polls=1)
    a, b, c = (str(tmp_path / n) for n in ("a.CR2", "b.CR2", "c.CR2"))
    _write(b, mtime=1_700_000_002); _write(c, mtime=1_700_000_003); _write(a, mtime=1_700_000_001)
    watch.poll()
    assert watch.poll() == [a, b, c]


def test_the_status_line():
    assert L.describe([]) == ""
    assert L.describe(["x/4N0A7869.CR2"]) == "Live: 4N0A7869.CR2 arrived"
    assert L.describe(["x/a.CR2", "x/b.CR2"]) == "Live: 2 photos arrived, the newest is b.CR2"
