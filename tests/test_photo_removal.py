"""Removing photos from the Workbench and deleting them from disk: what is touched, what is refused, and that a failure never deletes anything."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photoeditor.features.library import removal  # noqa: E402
from photoeditor.features.persistence import edit_store  # noqa: E402


def make(tmp_path, names=("a.jpg", "b.png", "c.cr2"), size=100):
    out = []
    for n in names:
        p = tmp_path / n
        p.write_bytes(b"x" * size)
        out.append(str(p))
    return out


class Bin:
    """A stand-in Recycle Bin: moves the file into a folder."""

    def __init__(self, folder):
        self.folder = folder
        folder.mkdir(exist_ok=True)
        self.seen = []

    def __call__(self, path):
        self.seen.append(path)
        os.replace(path, str(self.folder / (str(len(self.seen)) + "_" + os.path.basename(path))))


def test_photos_and_their_sidecars_go_to_the_bin_and_nothing_else(tmp_path):
    photos = make(tmp_path)
    (tmp_path / "a.jpg.xmp").write_text("x")
    (tmp_path / "b.png.efas-merge.json").write_text("x")
    (tmp_path / "notes.txt").write_text("keep me")
    (tmp_path / "sub").mkdir()
    bin_ = Bin(tmp_path / "bin")
    res = removal.delete_photos(photos + [str(tmp_path / "notes.txt"), str(tmp_path / "sub"), str(tmp_path / "missing.jpg")], bin_)
    assert res.deleted == photos and not res.failed
    assert sorted(os.path.basename(p) for p in res.skipped) == ["missing.jpg", "notes.txt", "sub"]
    assert (tmp_path / "notes.txt").exists() and (tmp_path / "sub").is_dir()
    assert not any((tmp_path / n).exists() for n in ("a.jpg", "b.png", "c.cr2", "a.jpg.xmp", "b.png.efas-merge.json"))
    assert len(bin_.seen) == 5


def test_a_photo_listed_twice_is_deleted_once(tmp_path):
    photos = make(tmp_path, ("a.jpg",))
    bin_ = Bin(tmp_path / "bin")
    res = removal.delete_photos(photos * 3, bin_)
    assert res.deleted == photos and len(bin_.seen) == 1


def test_a_failure_leaves_that_file_and_carries_on(tmp_path):
    photos = make(tmp_path)
    bin_ = Bin(tmp_path / "bin")

    def flaky(path):
        if path.endswith("b.png"):
            raise OSError("locked by another program")
        bin_(path)

    res = removal.delete_photos(photos, flaky)
    assert [os.path.basename(p) for p in res.deleted] == ["a.jpg", "c.cr2"]
    assert len(res.failed) == 1 and "locked" in res.failed[0][1] and (tmp_path / "b.png").exists()


def test_a_trasher_that_claims_success_but_leaves_the_file_is_not_counted(tmp_path):
    photos = make(tmp_path, ("a.jpg",))
    res = removal.delete_photos(photos, lambda p: None)
    assert not res.deleted and res.failed and "still in its folder" in res.failed[0][1]


def test_no_recycle_bin_means_nothing_is_deleted(tmp_path):
    photos = make(tmp_path)

    def none_available(path):
        raise removal.TrashUnavailable("no bin")

    with pytest.raises(removal.TrashUnavailable):
        removal.delete_photos(photos, none_available)
    assert all(os.path.exists(p) for p in photos)


def test_the_summary_counts_what_would_go(tmp_path):
    photos = make(tmp_path, size=1500)
    s = removal.summarise(photos + [str(tmp_path / "gone.jpg")])
    assert s.count == 3 and s.bytes == 4500 and s.missing == 1 and s.names == ("a.jpg", "b.png", "c.cr2") and s.folders == (str(tmp_path),)
    assert removal.human_size(512) == "512 bytes" and removal.human_size(4500) == "4.5 KB" and removal.human_size(2_500_000) == "2.5 MB"


def test_hiding_is_remembered_reversible_and_touches_no_files(tmp_path):
    photos = make(tmp_path)
    conn = edit_store.connect(str(tmp_path / "edits.db"))
    edit_store.hide_photos(conn, photos[:2])
    edit_store.hide_photos(conn, photos[:1])
    assert sorted(edit_store.hidden_paths(conn)) == sorted(photos[:2])
    assert os.path.normcase(os.path.abspath(photos[0])) in edit_store.hidden_keys(conn)
    conn.close()
    conn = edit_store.connect(str(tmp_path / "edits.db"))
    assert len(edit_store.hidden_paths(conn)) == 2
    edit_store.unhide_photos(conn, photos[:1])
    assert edit_store.hidden_paths(conn) == [photos[1]]
    assert all(os.path.exists(p) for p in photos)


def test_off_windows_the_system_trash_is_used_through_send2trash(tmp_path, monkeypatch):
    calls = []
    fake = type(sys)("send2trash")
    fake.send2trash = calls.append
    monkeypatch.setitem(sys.modules, "send2trash", fake)
    monkeypatch.setattr(removal.sys, "platform", "linux")
    removal.send_to_trash(str(tmp_path / "a.jpg"))
    assert calls == [str(tmp_path / "a.jpg")]


def test_off_windows_without_send2trash_nothing_is_deleted(tmp_path, monkeypatch):
    photos = make(tmp_path, ("a.jpg",))
    monkeypatch.setitem(sys.modules, "send2trash", None)
    monkeypatch.setattr(removal.sys, "platform", "darwin")
    with pytest.raises(removal.TrashUnavailable):
        removal.delete_photos(photos)
    assert os.path.exists(photos[0])
