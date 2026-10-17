"""Folders of the Library on disk: making, renaming and deleting them (features/library/folders.py), following a renamed folder in the edit database and the library
index, and leaving removed folders out of the index scan."""
import json
import os
import shutil
import sqlite3

import pytest
from PIL import Image

from photoeditor.features.library import folders as f
from photoeditor.features.library.index import LibraryIndex, scan_files
from photoeditor.features.library.removal import TrashUnavailable
from photoeditor.features.persistence import edit_store


def _photo(path, size=(16, 12)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", size, (90, 80, 70)).save(path)
    return path


def test_names_that_cannot_be_a_folder_say_why():
    assert f.check_name("  Roll 12  ") == "Roll 12"
    for bad, word in (("", "name"), ("   ", "name"), ("a/b", "/"), ("a:b", ":"), ("a?b", "?"), ('a"b', '"'), ("ends.", "dot"), ("..", "dot"), ("CON", "keeps"), ("nul.txt", "keeps"),
                      ("x" * 300, "long"), ("a\x01b", "control")):
        with pytest.raises(f.FolderError) as err:
            f.check_name(bad)
        assert word in str(err.value), (bad, str(err.value))


def test_making_a_folder(tmp_path):
    base = str(tmp_path)
    made = f.create_folder(base, "  1995 Italy ")
    assert os.path.isdir(made) and os.path.basename(made) == "1995 Italy"
    with pytest.raises(f.FolderError, match="already"):
        f.create_folder(base, "1995 Italy")
    with pytest.raises(f.FolderError, match="not there"):
        f.create_folder(os.path.join(base, "gone"), "x")
    with pytest.raises(f.FolderError):
        f.create_folder(base, "a/b")
    assert sorted(os.listdir(base)) == ["1995 Italy"], "nothing else was made"


def test_renaming_never_replaces_another_folder(tmp_path):
    base = str(tmp_path)
    a, b = os.path.join(base, "RollA"), os.path.join(base, "RollB")
    os.makedirs(a)
    os.makedirs(b)
    _photo(os.path.join(a, "x.png"))
    with pytest.raises(f.FolderError, match="already|there already"):
        f.rename_folder(a, "RollB")
    with pytest.raises(f.FolderError, match="already"):
        f.rename_folder(a, "RollA")
    assert f.plan_rename(a, "Fuji") == os.path.join(base, "Fuji") and os.path.isdir(a), "planning changes nothing"
    new = f.rename_folder(a + os.sep, "Fuji")   # a trailing slash does not matter
    assert new == os.path.join(base, "Fuji") and os.path.isfile(os.path.join(new, "x.png")) and not os.path.exists(a)
    with pytest.raises(f.FolderError, match="not there"):
        f.rename_folder(a, "Again")
    root = os.path.splitdrive(base)[0] + os.sep
    with pytest.raises(f.FolderError, match="drive"):
        f.rename_folder(root, "Nope")


@pytest.mark.skipif(os.name != "nt", reason="the case of a name only counts on Windows")
def test_a_change_of_capitals_alone_is_a_rename(tmp_path):
    a = os.path.join(str(tmp_path), "roll")
    os.makedirs(a)
    new = f.rename_folder(a, "Roll")
    assert os.listdir(str(tmp_path)) == ["Roll"] and new.endswith("Roll")


def test_moving_a_folder_into_another(tmp_path):
    base = str(tmp_path)
    a, b = os.path.join(base, "RollA"), os.path.join(base, "Archive")
    os.makedirs(os.path.join(a, "inner"))
    os.makedirs(b)
    _photo(os.path.join(a, "inner", "x.png"))
    assert f.plan_move(a, b) == os.path.join(b, "RollA") and os.path.isdir(a), "planning changes nothing"
    with pytest.raises(f.FolderError, match="itself"):
        f.plan_move(a, a)
    with pytest.raises(f.FolderError, match="itself"):
        f.plan_move(a, os.path.join(a, "inner"))
    with pytest.raises(f.FolderError, match="already in"):
        f.plan_move(a, base)
    with pytest.raises(f.FolderError, match="not there"):
        f.plan_move(a, os.path.join(base, "gone"))
    with pytest.raises(f.FolderError, match="not there"):
        f.plan_move(os.path.join(base, "gone"), b)
    os.makedirs(os.path.join(b, "RollA"))
    with pytest.raises(f.FolderError, match="already"):
        f.plan_move(a, b)
    os.rmdir(os.path.join(b, "RollA"))
    new = f.move_folder(a + os.sep, b)
    assert new == os.path.join(b, "RollA") and os.path.isfile(os.path.join(new, "inner", "x.png")) and not os.path.exists(a)
    assert f.remap(os.path.join(a, "inner", "x.png"), a, new) == os.path.join(new, "inner", "x.png"), "paths follow a move"
    root = os.path.splitdrive(base)[0] + os.sep
    with pytest.raises(f.FolderError, match="drive"):
        f.plan_move(root, b)


def test_remap_follows_a_renamed_folder_and_keeps_each_paths_own_spelling():
    old, new = "C:/Photos/Roll 1", "C:/Photos/Fuji"
    assert f.remap("C:/Photos/Roll 1/a.png", old, new) == "C:/Photos/Fuji/a.png"
    assert f.remap("C:\\Photos\\Roll 1\\sub\\a.png", old, new) == "C:\\Photos\\Fuji\\sub\\a.png", "backslashes stay backslashes"
    assert f.remap("C:/Photos/Roll 1", old, new) == "C:/Photos/Fuji", "the folder itself"
    assert f.remap("C:/Photos/Roll 10/a.png", old, new) == "C:/Photos/Roll 10/a.png", "a folder that only starts with the same letters is not in it"
    assert f.remap("C:/Elsewhere/a.png", old, new) == "C:/Elsewhere/a.png"
    assert f.remap("", old, new) == ""
    assert f.remap("C:/Photos/Roll 1/a.png", old + "/", new + "/") == "C:/Photos/Fuji/a.png", "trailing slashes do not matter"
    assert f.remap_all(["C:/Photos/Roll 1/a.png", "D:/x.png"], old, new) == ["C:/Photos/Fuji/a.png", "D:/x.png"]
    # a folder moved somewhere else is given the new place
    assert f.remap("C:/Photos/Roll 1/sub/a.png", old, "D:/Archive/Roll 1") == "D:/Archive/Roll 1/sub/a.png"
    if os.name == "nt":
        assert f.remap("c:\\photos\\ROLL 1\\a.png", old, new) == "c:\\photos\\Fuji\\a.png", "Windows does not mind the capitals"


def test_what_a_folder_holds(tmp_path):
    base = str(tmp_path / "Roll")
    _photo(os.path.join(base, "a.png"))
    _photo(os.path.join(base, "b.png"))
    _photo(os.path.join(base, "inner", "deep", "c.png"))
    open(os.path.join(base, "a.png.xmp"), "w").write("x")
    open(os.path.join(base, "notes.txt"), "w").write("hello")
    s = f.summarise(base)
    assert (s.photos, s.folders, s.others) == (3, 2, 1), s
    assert s.bytes > 0 and s.names == ("inner",)
    assert [os.path.basename(p) for p in f.photos_under(base)] == ["a.png", "b.png", "c.png"]
    assert f.summarise(str(tmp_path / "nope")).photos == 0


def test_deleting_goes_to_the_recycle_bin_and_never_for_good(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    folder = str(tmp_path / "Roll")
    _photo(os.path.join(folder, "a.png"))

    sent = []

    def trasher(path):
        sent.append(path)
        shutil.move(path, str(bin_dir / os.path.basename(path)))

    f.delete_folder(folder, trasher)
    assert sent == [folder] and not os.path.exists(folder) and (bin_dir / "Roll" / "a.png").is_file()

    stuck = str(tmp_path / "Stuck")
    _photo(os.path.join(stuck, "a.png"))
    with pytest.raises(f.FolderError, match="still"):
        f.delete_folder(stuck, lambda p: None)   # a Recycle Bin that did nothing: it is not called deleted
    assert os.path.isfile(os.path.join(stuck, "a.png"))

    def refuses(path):
        raise OSError("in use")

    with pytest.raises(f.FolderError, match="in use"):
        f.delete_folder(stuck, refuses)

    def no_bin(path):
        raise TrashUnavailable("no Recycle Bin")

    with pytest.raises(TrashUnavailable):
        f.delete_folder(stuck, no_bin)
    assert os.path.isfile(os.path.join(stuck, "a.png")), "no fallback to a permanent delete"


def test_folders_that_are_never_deleted(tmp_path):
    data = str(tmp_path / "EFAS data")
    os.makedirs(os.path.join(data, "thumbs"))
    for danger in (data, os.path.join(data, "thumbs"), str(tmp_path)):   # the data folder, one inside it, one that holds it
        with pytest.raises(f.FolderError, match="own data"):
            f.check_deletable(danger, [data])
    root = os.path.splitdrive(str(tmp_path))[0] + os.sep
    with pytest.raises(f.FolderError, match="drive"):
        f.check_deletable(root)
    with pytest.raises(f.FolderError, match="not there"):
        f.check_deletable(str(tmp_path / "gone"))
    target = str(tmp_path / "real")
    os.makedirs(target)
    link = str(tmp_path / "link")
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        return   # a link cannot be made here (no privilege)
    with pytest.raises(f.FolderError, match="link"):
        f.check_deletable(link)


def test_the_database_follows_a_renamed_folder(tmp_path):
    conn = edit_store.connect(str(tmp_path / "edits.db"))
    old, new = str(tmp_path / "Roll 1"), str(tmp_path / "Fuji")
    inside = [os.path.join(old, "a.png"), os.path.join(old, "sub", "b.png")]
    other = os.path.join(str(tmp_path), "Roll 10", "c.png")   # starts with the same letters, is not in the folder
    for p in inside + [other]:
        edit_store.set_rating(conn, p, 4)
        edit_store.add_tags(conn, [p], ["keeper"])
        edit_store.set_flag(conn, p, "pick")
        edit_store.set_photo_film_base(conn, p, (200, 120, 60))
    edit_store.hide_photos(conn, [inside[0]])
    edit_store.set_folder_roll(conn, edit_store.folder_key(old, False), {"film": "Portra"})
    edit_store.set_folder_roll(conn, edit_store.folder_key(os.path.join(old, "sub"), False), {"film": "Sub"})
    edit_store.set_folder_roll(conn, edit_store.folder_key(os.path.dirname(other), False), {"film": "Other"})
    edit_store.save_collection(conn, "Roll 1 picks", {"under": old, "text": ""})
    edit_store.save_collection(conn, "Elsewhere", {"under": os.path.dirname(other)})

    edit_store.move_folder_records(conn, lambda p: f.remap(p, old, new), old, new)

    moved = [os.path.join(new, "a.png"), os.path.join(new, "sub", "b.png")]
    for p in moved:
        assert edit_store.get_rating(conn, p) == 4 and edit_store.get_flag(conn, p) == "pick" and edit_store.get_photo_film_base(conn, p) == (200, 120, 60)
        assert edit_store.get_tags(conn, [p])[p] == ["keeper"]
    for p in inside:
        assert edit_store.get_rating(conn, p) == 0 and edit_store.get_flag(conn, p) is None, "nothing is left under the old names"
    assert edit_store.get_rating(conn, other) == 4 and edit_store.get_flag(conn, other) == "pick", "a folder that only looks alike is not touched"
    assert edit_store.hidden_paths(conn) == [moved[0]], "a photo taken off the Workbench stays off"
    assert edit_store.get_folder_roll(conn, edit_store.folder_key(new, False)) == {"film": "Portra"}
    assert edit_store.get_folder_roll(conn, edit_store.folder_key(os.path.join(new, "sub"), False)) == {"film": "Sub"}, "the folders in it too"
    assert edit_store.get_folder_roll(conn, edit_store.folder_key(old, False)) is None
    assert edit_store.get_folder_roll(conn, edit_store.folder_key(os.path.dirname(other), False)) == {"film": "Other"}
    by_name = dict(edit_store.list_collections(conn))
    assert by_name["Roll 1 picks"]["under"] == new and by_name["Elsewhere"]["under"] == os.path.dirname(other), "a smart collection that looks in the folder follows it"


def test_the_library_index_follows_a_renamed_folder(tmp_path):
    old = str(tmp_path / "Roll 1")
    other = str(tmp_path / "Roll 10")
    for p in (os.path.join(old, "a.png"), os.path.join(old, "sub", "b.png"), os.path.join(other, "c.png")):
        _photo(p)
    index = LibraryIndex(str(tmp_path / "index.db"))
    index.refresh([old, other])
    before = {r["path"]: r for r in index.all()}
    assert len(before) == 3
    new = str(tmp_path / "Fuji")
    os.rename(old, new)
    assert index.move_under(lambda p: f.remap(p, old, new), old) == 2
    after = {r["path"]: r for r in index.all()}
    assert sorted(after) == sorted([os.path.join(new, "a.png"), os.path.join(new, "sub", "b.png"), os.path.join(other, "c.png")])
    moved = after[os.path.join(new, "sub", "b.png")]
    assert moved["folder"] == os.path.join(new, "sub") and moved["size"] == before[os.path.join(old, "sub", "b.png")]["size"], "the record is the same, at its new path"
    added, changed, removed = index.refresh([new, other])
    assert (added, changed, removed) == (0, 0, 0), "the next scan finds nothing to do: the records match the files"
    index.close()


def test_removed_folders_are_left_out_of_the_scan_and_the_index(tmp_path):
    root = str(tmp_path / "Library")
    keep, skip = os.path.join(root, "Keep"), os.path.join(root, "Skip")
    for p in (os.path.join(keep, "a.png"), os.path.join(skip, "b.png"), os.path.join(skip, "deep", "c.png")):
        _photo(p)
    names = lambda files: sorted(os.path.basename(p) for p, _s, _m in files)
    assert names(scan_files([root])) == ["a.png", "b.png", "c.png"]
    assert names(scan_files([root], [skip])) == ["a.png"], "the folder and the ones in it are not entered"
    assert names(scan_files([skip], [skip])) == [], "nor a root that was removed"
    index = LibraryIndex(str(tmp_path / "index.db"))
    index.refresh([root])
    assert len(index.all()) == 3
    added, changed, removed = index.refresh([root], excluded=[skip])
    assert (added, changed, removed) == (0, 0, 2) and [os.path.basename(r["path"]) for r in index.all()] == ["a.png"]
    added, changed, removed = index.refresh([root])
    assert added == 2, "when the folder comes back its photos are read again"
    index.close()
