"""Sorting the Library's folders (by name, date, number of photos, or as added), in the editor's panel and the Workbench's, remembered between runs."""
import os
import subprocess
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path

import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")


def make_roll(base: Path, name: str, photos: int, when: datetime, subs: tuple[str, ...] = ()) -> str:
    folder = base / name
    folder.mkdir(parents=True)
    stamp = when.timestamp()
    for i in range(photos):
        f = folder / f"{i}.jpg"
        f.write_bytes(b"x")
        os.utime(f, (stamp, stamp))
    for sub in subs:
        (folder / sub).mkdir()
    return str(folder)


@pytest.fixture
def rolls(tmp_path):
    return {
        "Zebra": make_roll(tmp_path, "Zebra", 3, datetime(2026, 3, 1)),
        "apple": make_roll(tmp_path, "apple", 10, datetime(2026, 1, 5)),
        "Mango": make_roll(tmp_path, "Mango", 0, datetime(2026, 6, 6)),   # no photos: dated by the folder itself (below)
        "Kiwi": make_roll(tmp_path, "Kiwi", 7, datetime(2026, 9, 9)),
    }


def test_the_sort_modes_and_what_they_sort_on():
    from photoeditor.features.browse import logic as B

    assert [k for k, _l in B.SORT_MODES] == ["added", "name", "name_desc", "date_new", "date_old", "count_most", "count_fewest"]
    assert B.sort_fact("name") == ("name", False) and B.sort_fact("name_desc") == ("name", True) and B.sort_fact("date_new") == ("date", True)
    assert B.sort_fact("count_most") == ("count", True) and B.sort_fact("nonsense") == ("order", False) and B.DEFAULT_SORT == "added"


def test_a_folders_date_is_its_newest_photo_or_the_folder_itself(tmp_path):
    from photoeditor.features.browse import logic as B

    roll = make_roll(tmp_path, "Roll", 2, datetime(2026, 2, 2), subs=("a", "b"))
    older = Path(roll) / "0.jpg"
    os.utime(older, (datetime(2025, 1, 1).timestamp(), datetime(2025, 1, 1).timestamp()))
    images, subfolders, newest = B.folder_stats(roll)
    assert (images, subfolders) == (2, 2) and datetime.fromtimestamp(newest).date() == datetime(2026, 2, 2).date(), "the newest of its photos"
    empty = tmp_path / "Empty"
    empty.mkdir()
    os.utime(empty, (datetime(2024, 4, 4).timestamp(), datetime(2024, 4, 4).timestamp()))
    assert B.folder_stats(str(empty))[0] == 0 and datetime.fromtimestamp(B.folder_stats(str(empty))[2]).year == 2024
    assert B.folder_stats(str(tmp_path / "missing")) == (0, 0, 0.0)


@pytest.fixture
def qt(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path / "data"))
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def names(tree) -> list[str]:
    return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]


def test_the_tree_lists_its_roots_in_every_order(qt, rolls):
    from photoeditor.desktop.view.folder_tree import FolderTree

    order = ["Zebra", "apple", "Mango", "Kiwi"]
    tree = FolderTree()
    tree.set_roots([rolls[n] for n in order])
    assert names(tree) == order, "as added is the default"
    expected = {
        "name": ["apple", "Kiwi", "Mango", "Zebra"], "name_desc": ["Zebra", "Mango", "Kiwi", "apple"],
        "count_most": ["apple", "Kiwi", "Zebra", "Mango"], "count_fewest": ["Mango", "Zebra", "Kiwi", "apple"],
        "date_old": ["apple", "Zebra", "Kiwi"], "date_new": ["Kiwi", "Zebra", "apple"],  # (Mango is dated by its folder: today, so it is newest/last - checked below)
    }
    for mode in ("name", "name_desc", "count_most", "count_fewest"):
        tree.set_sort(mode)
        assert names(tree) == expected[mode], (mode, names(tree))
    tree.set_sort("date_old")
    assert names(tree)[:3] == ["apple", "Zebra", "Kiwi"] and names(tree)[-1] == "Mango", "an empty folder is dated by itself, which is the newest"
    tree.set_sort("date_new")
    assert names(tree)[0] == "Mango" and names(tree)[1:] == ["Kiwi", "Zebra", "apple"]
    tree.set_sort("added")
    assert names(tree) == order, "back to the order they were added in"
    tree.set_sort("bogus")
    assert tree.sort_mode == "added"


def test_the_right_hand_column_shows_the_date_in_a_date_sort_and_the_count_otherwise(qt, rolls):
    from photoeditor.desktop.view.folder_tree import FolderTree

    tree = FolderTree()
    tree.set_roots([rolls["Kiwi"], rolls["apple"]])
    texts = lambda: {tree.topLevelItem(i).text(0): tree.topLevelItem(i).text(1) for i in range(tree.topLevelItemCount())}
    assert texts() == {"Kiwi": "7 photos", "apple": "10 photos"}
    tree.set_sort("date_new")
    assert texts() == {"Kiwi": "09 Sep 2026", "apple": "05 Jan 2026"}
    assert "7 photos, newest photo 09 Sep 2026" in tree.topLevelItem(0).toolTip(1)
    tree.set_sort("count_most")
    assert texts() == {"Kiwi": "7 photos", "apple": "10 photos"}


def test_subfolders_follow_the_sort_and_new_roots_land_in_the_right_place(qt, tmp_path):
    from photoeditor.desktop.view.folder_tree import FolderTree

    year = tmp_path / "2026"
    year.mkdir()
    a = make_roll(year, "RollA", 2, datetime(2026, 1, 1))
    b = make_roll(year, "RollB", 9, datetime(2026, 5, 5))
    c = make_roll(year, "RollC", 5, datetime(2026, 3, 3))
    tree = FolderTree()
    tree.set_sort("count_most")
    tree.set_roots([str(year)])
    root = tree.topLevelItem(0)
    tree.expandItem(root)
    assert [root.child(i).text(0) for i in range(root.childCount())] == ["RollB", "RollC", "RollA"], "expanded: its subfolders are sorted the same way"
    tree.set_sort("date_old")
    assert [root.child(i).text(0) for i in range(root.childCount())] == ["RollA", "RollC", "RollB"], "an open folder re-sorts in place"
    assert root.isExpanded()
    tree.set_sort("added")
    assert [root.child(i).text(0) for i in range(root.childCount())] == ["RollA", "RollB", "RollC"], "subfolders have no 'added' order: by name"
    extra = make_roll(tmp_path, "Another", 20, datetime(2020, 1, 1))
    tree.set_sort("count_most")
    tree.add_root(extra)
    assert names(tree) == ["Another", "2026"] or names(tree)[0] == "Another"
    tree.set_sort("added")
    assert names(tree) == ["2026", "Another"]


# ------------------------------------------------------------------ the panels (a real window: editor and Workbench kept in step, remembered)
_SCRIPT = textwrap.dedent(r"""
    import os, sys, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    sys.path.insert(0, __SRC__)
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    from photoeditor.desktop.settings_store import qsettings
    from photoeditor.desktop.view.folder_tree import ROOTS_SETTINGS_KEY, SORT_SETTINGS_KEY
    roots = __ROOTS__
    qsettings().setValue(ROOTS_SETTINGS_KEY, roots); qsettings().sync()
    from photoeditor.desktop.view import app_window as aw
    w = aw.AppWindow()
    editor, bench = w._library_panel, w._lighttable.library_panel
    names = lambda p: [p._tree.topLevelItem(i).text(0) for i in range(p._tree.topLevelItemCount())]
    assert editor._sort.currentData() == "added" and bench._sort.currentData() == "added"
    assert [editor._sort.itemText(i) for i in range(editor._sort.count())][:3] == ["As added", "Name A-Z", "Name Z-A"]
    start = names(editor)

    editor._sort.setCurrentIndex(editor._sort.findData("count_most"))   # the user picks in the editor's Library
    assert names(editor)[0] == "apple" and names(bench) == names(editor), names(bench)
    assert bench._sort.currentData() == "count_most", "the Workbench's Library follows"
    bench._sort.setCurrentIndex(bench._sort.findData("name"))           # and the other way round
    assert names(editor) == sorted(start, key=str.lower) and editor._sort.currentData() == "name"
    assert qsettings().value(SORT_SETTINGS_KEY, "", type=str) == "name", "remembered"
    w.close()

    w2 = aw.AppWindow()                                                  # a fresh start reads it back
    assert w2._library_panel._sort.currentData() == "name" and w2._lighttable.library_panel._sort.currentData() == "name"
    assert names(w2._library_panel) == sorted(start, key=str.lower)
    w2._library_panel._tree.refresh()
    assert names(w2._library_panel) == sorted(start, key=str.lower), "refreshing keeps the sort"
    print("SORT OK")
    sys.stdout.flush(); os._exit(0)
""")


def test_both_library_panels_share_one_remembered_sort(tmp_path, rolls):
    script = _SCRIPT.replace("__SRC__", repr(SRC)).replace("__ROOTS__", repr(list(rolls.values())))
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=180)
    assert "SORT OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3000:]
