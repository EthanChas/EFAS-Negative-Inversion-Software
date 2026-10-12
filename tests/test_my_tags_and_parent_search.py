"""The drop-down of the tags you have made (not a built-in list), the search box offering a nested tag by its last level, and parent search everywhere."""
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from photoeditor.features.library import query as Q
from photoeditor.features.library import suggest
from photoeditor.features.tags import logic as T
from photoeditor.features.tags import tagging as G

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_there_is_no_built_in_list():
    assert not hasattr(T, "PREMADE")


def _row(name, tags):
    return {"name": name, "tags": tags, "tags_text": " ".join(tags), "rating": 0, "flag": "", "edited": False, "camera": "", "roll_camera": "", "lens": "", "roll_lens": "",
            "film": "", "folder": "f", "iso": 0, "day": "2026-01-01", "path": name, "note": "", "place": "", "taken": "", "mtime_ns": 0,
            "_blob": f"{name} {' '.join(tags)}".lower()}


# the tags as they really are: a photo tagged Friends, photos tagged Friends/Ghitta and Friends/Dogass, two tagged ghitta
ROWS = [_row("a", ["Friends/Ghitta"]), _row("b", ["Friends"]), _row("c", ["cr2", "ghitta"]), _row("d", ["ghitta"]), _row("e", ["Friends/Dogass"]), _row("f", [])]


def test_searching_a_parent_finds_every_photo_inside_it():
    names = lambda q: sorted(r["name"] for r in Q.filter_rows(ROWS, q))
    assert names(Q.Query(text="Friends")) == ["a", "b", "e"]
    assert names(Q.Query(text="tag:Friends")) == ["a", "b", "e"]
    assert names(Q.Query(tag="Friends")) == ["a", "b", "e"]
    assert names(Q.Query(text="tag:Friends/Dogass")) == ["e"] and names(Q.Query(text="dogass")) == ["e"]


def matching(token, rows=ROWS):
    return [t for t, _h in suggest.matching(suggest.build(rows), token)]


def test_the_search_box_offers_a_nested_tag_by_its_last_level():
    assert "tag:Friends/Dogass" in matching("Dog"), "typing the last level is enough"
    assert "tag:Friends/Dogass" in matching("tag:Dog"), "and with tag: in front"
    assert "tag:Friends/Dogass" in matching("tag:Friends/Dog")
    assert "tag:Friends/Dogass" in matching("dogass") and "tag:Friends/Dogass" in matching("Friends/Dog")
    assert set(matching("Ghi")) >= {"tag:Friends/Ghitta", "tag:ghitta"}
    assert "tag:Friends/Dogass" in matching("ogas"), "three letters or more can be from anywhere in the name"
    assert "tag:Friends/Dogass" not in matching("tag:Gh"), "another tag's level does not match"
    assert matching("zzzz") == [] and matching("") == [] and matching("tag:") != [], "typing only tag: offers the tags"


def test_a_parent_and_all_its_children_are_offered_with_the_parent_first():
    got = matching("Friends")
    assert got[0] == "tag:Friends" and set(got[:3]) == {"tag:Friends", "tag:Friends/Ghitta", "tag:Friends/Dogass"}
    crowd = [_row(f"x{i}", [f"Busy{i}"]) for i in range(60) for _ in range(3)]
    offered = [t for t, _h in suggest.matching(suggest.build(crowd + ROWS), "Friends")]
    assert {"tag:Friends", "tag:Friends/Ghitta", "tag:Friends/Dogass"} <= set(offered), "not just the most used few"
    only_child = suggest.build([_row("z", ["Pets/Cats/Tabby"])])
    assert {t for t, _h in suggest.matching(only_child, "Pets")} >= {"tag:Pets", "tag:Pets/Cats", "tag:Pets/Cats/Tabby"}
    assert "tag:Pets/Cats/Tabby" in [t for t, _h in suggest.matching(only_child, "Tab")]


def test_a_finished_term_is_not_offered_again_but_fields_still_are():
    assert "tag:Friends/Dogass" not in matching("tag:Friends/Dogass")
    assert "tag:" in matching("tag") or "tag:" in matching("ta")


def test_the_dictionary_shows_a_parent_and_all_its_children_together():
    dictionary = {"Friends": 1, "Friends/Ghitta": 2, "Friends/Dogass": 1, "ghitta": 2, "Test": 1}
    rows = G.dictionary_rows(dictionary, {}, 0, "Friends")
    assert {e.tag for e in rows} == {"Friends", "Friends/Ghitta", "Friends/Dogass"} and rows[0].tag == "Friends"
    assert "Friends/Dogass" in [e.tag for e in G.dictionary_rows(dictionary, {}, 0, "Dog")], "its last level finds it"
    tree = G.build_tree(dictionary, {}, 0, "Friends")
    assert [n.name for n in tree] == ["Friends"] and sorted(c.name for c in tree[0].children) == ["Dogass", "Ghitta"]


def test_a_parent_shows_a_dash_when_something_inside_it_is_attached():
    dictionary = {"People/Family": 2, "People/Friends": 1, "Holiday": 3}
    tree = G.build_tree(dictionary, {"People/Family": 1}, 1)
    people = next(n for n in tree if n.name == "People")
    assert not people.defined and people.mark == G.SOME
    assert next(n for n in tree if n.name == "Holiday").mark == G.NONE
    deep = G.build_tree({"a/b/c": 1}, {"a/b/c": 1}, 1)
    assert deep[0].mark == G.SOME and deep[0].children[0].mark == G.SOME and deep[0].children[0].children[0].mark == G.ALL


_UI = textwrap.dedent(r'''
    import os, sys, time, faulthandler
    faulthandler.enable()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    import numpy as np, cv2
    from PyQt6.QtCore import QItemSelectionModel, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    DATA = os.environ["PHOTOEDITOR_DATA_DIR"]
    folder = os.path.join(DATA, "photos"); os.makedirs(folder)
    rng = np.random.default_rng(1)
    paths = []
    for name in ("a.png", "b.png", "c.png"):
        img = cv2.GaussianBlur(rng.random((200, 300, 3)).astype(np.float32), (0, 0), 15)
        p = os.path.join(folder, name); cv2.imwrite(p, (60 + 140 * (img - img.min()) / np.ptp(img)).astype(np.uint8)); paths.append(p)
    A, B, C = paths
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); win.show(); app.processEvents()
    win.open_folder(folder, prefer=A)
    def pump(cond=lambda: False, secs=15.0):
        end = time.time() + secs
        while time.time() < end:
            app.processEvents()
            if cond(): return True
            time.sleep(0.01)
        return cond()
    c = win.controller
    assert pump(lambda: c.state.image_rgb is not None); pump(secs=0.3)
    items = lambda combo: [combo.itemText(i) for i in range(combo.count())]

    # ---- the Metadata tab's drop-down: nothing made yet, then every tag made - used on a photo or not
    editor = win._tags_panel.editor
    assert items(editor._mytags) == ["No tags made yet - type one above"]
    c.set_tags_for([A], add=["Friends/Dogass"])
    c.set_tags_for([B], add=["Friends", "Friends/Ghitta"])
    c.create_tag("Places/Paris")          # made, on no photo
    pump(secs=0.4)
    assert items(editor._mytags) == ["Add one of my tags...", "Friends", "Friends › Dogass", "Friends › Ghitta", "Places › Paris"], items(editor._mytags)
    got = []
    editor.add_requested.connect(got.append)
    editor._mytags.activated.emit(editor._mytags.findData("Places/Paris"))
    assert got == [["Places/Paris"]] and editor._mytags.currentIndex() == 0

    # ---- the Workbench's Selection: the same list, with every tag - not just those on the photos shown
    win.set_view("lighttable"); pump(secs=1.0)
    lt = win._lighttable
    for i in range(lt._model.rowCount()):
        if lt._model.row_dict(i)["name"] == "c":
            lt._list.setCurrentIndex(lt._model.index(i, 0))
            lt._list.selectionModel().select(lt._model.index(i, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect)
    pump(secs=0.4)
    assert [os.path.basename(p) for p in lt.selected_paths()] == ["c.png"] and lt._tags._list.count() == 0, "photo c has no tags"
    assert items(lt._tags._mytags) == items(editor._mytags), items(lt._tags._mytags)
    got2 = []
    lt.tags_requested.connect(lambda paths, add, remove: got2.append((paths, add, remove)))
    lt._tags._mytags.activated.emit(lt._tags._mytags.findData("Friends/Dogass"))
    assert got2 == [([C], ["Friends/Dogass"], [])], got2
    pump(secs=0.5)
    assert [lt._tags._list.item(i).text() for i in range(lt._tags._list.count())] == ["Friends › Dogass"], "the Selection list now shows the tag"
    assert "Friends/Dogass" in c.photo_tags(C)
    # a tag made later shows up at once in both
    c.create_tag("Gear/Pentax"); pump(secs=0.3)
    assert "Gear › Pentax" in items(lt._tags._mytags) and "Gear › Pentax" in items(editor._mytags)
    # the completer of the tag box knows them too
    assert "Gear/Pentax" in lt._tags._model.stringList() and "Places/Paris" in lt._tags._model.stringList()

    # ---- the search box: type the last level of a nested tag and it is offered
    lt._search.setFocus(); pump(secs=0.2)
    for text, expected in (("Dog", "tag:Friends/Dogass"), ("tag:Dog", "tag:Friends/Dogass"), ("tag:Friends/", "tag:Friends/Ghitta"), ("Pari", "tag:Places/Paris")):
        lt._search.clear(); pump(secs=0.2)
        for ch in text:
            QTest.keyClick(lt._search, ch); pump(secs=0.03)
        pump(secs=0.4)
        offered = [lt._suggest_model.item(i).text().split("  ")[0].strip() for i in range(lt._suggest_model.rowCount())]
        assert expected in offered, (text, offered)
        assert lt._completer.completionCount() >= 1, (text, lt._completer.completionCount())
    lt._search.clear(); pump(secs=0.2)
    for ch in "tag:Friends/Dogass":
        QTest.keyClick(lt._search, ch); pump(secs=0.03)
    pump(secs=0.6)
    assert sorted(r["name"] for r in lt._shown) == ["a", "c"], [r["name"] for r in lt._shown]
    print("MY TAGS UI OK"); sys.stdout.flush(); os._exit(0)
''')


def test_my_tags_drop_down_and_search_in_the_running_app():
    data = tempfile.mkdtemp()
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""), PHOTOEDITOR_DATA_DIR=data)
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _UI], env=env, capture_output=True, text=True, timeout=600)
    assert "MY TAGS UI OK" in done.stdout, done.stdout[-1500:] + done.stderr[-4000:]
