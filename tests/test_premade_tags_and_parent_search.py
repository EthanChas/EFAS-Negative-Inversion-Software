"""The user's own pre-made tags (a list they keep, not a built-in one), and searching a parent tag finds every tag inside it everywhere you can search."""
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

from photoeditor.features.library import query as Q
from photoeditor.features.library import suggest
from photoeditor.features.tags import logic as T
from photoeditor.features.tags import premade
from photoeditor.features.tags import tagging as G

SRC = str(Path(__file__).resolve().parents[1] / "src")


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    return tmp_path


def test_there_is_no_built_in_list():
    assert not hasattr(T, "PREMADE")


def test_the_users_list_starts_empty_and_keeps_what_they_add(data):
    assert premade.load() == []
    assert premade.add(["People/Family", "Holiday"]) == ["People/Family", "Holiday"]
    assert premade.add(["holiday", "Places/Paris", "  "]) == ["People/Family", "Holiday", "Places/Paris"], "no repeats (any capitals), the order they were added in"
    assert premade.load() == ["People/Family", "Holiday", "Places/Paris"]
    assert (data / "premade-tags.json").exists()


def test_removing_from_the_list_only_changes_the_list(data):
    premade.add(["A/B", "C", "D"])
    assert premade.remove(["a/b", "nothing"]) == ["C", "D"]
    assert premade.load() == ["C", "D"]
    assert premade.remove(["C", "D"]) == [] and premade.load() == []


def test_a_damaged_file_is_an_empty_list(data):
    (data / "premade-tags.json").write_text("not json")
    assert premade.load() == []
    (data / "premade-tags.json").write_text('{"a": 1}')
    assert premade.load() == []
    (data / "premade-tags.json").write_text('["ok", 5, null, "also ok"]')
    assert premade.load() == ["ok", "also ok"]


def test_the_list_goes_with_a_data_export(data):
    from photoeditor.features.persistence import export

    assert "premade-tags.json" in export.DATA_FILES


def _row(name, tags):
    return {"name": name, "tags": tags, "tags_text": " ".join(tags), "rating": 0, "flag": "", "edited": False, "camera": "", "roll_camera": "", "lens": "", "roll_lens": "",
            "film": "", "folder": "f", "iso": 0, "day": "2026-01-01", "path": name, "note": "", "place": "", "taken": "", "mtime_ns": 0,
            "_blob": f"{name} {' '.join(tags)}".lower()}


# the tags as they really are: a photo tagged Friends, one tagged Friends/Ghitta, two tagged ghitta
ROWS = [_row("a", ["Friends/Ghitta"]), _row("b", ["Friends"]), _row("c", ["cr2", "ghitta"]), _row("d", ["ghitta"]), _row("e", ["Friends/Dog"]), _row("f", [])]


def test_searching_a_parent_finds_every_photo_inside_it():
    names = lambda q: sorted(r["name"] for r in Q.filter_rows(ROWS, q))
    assert names(Q.Query(text="Friends")) == ["a", "b", "e"], "typed in the search box"
    assert names(Q.Query(text="tag:Friends")) == ["a", "b", "e"]
    assert names(Q.Query(tag="Friends")) == ["a", "b", "e"], "chosen in the Tag filter"
    assert names(Q.Query(tag="Friends/Ghitta")) == ["a"] and names(Q.Query(tag="friends/dog")) == ["e"]
    assert names(Q.Query(text="ghitta")) == ["a", "c", "d"]


def test_the_search_box_offers_the_parent_and_every_child():
    rows = [_row(f"p{i}", [f"Tag{i}"] * 1) for i in range(60)] + ROWS
    for r in rows[:60]:
        r["tags"] = [r["tags"][0]] * 1
    # sixty other tags, each on more photos than Friends/Ghitta: it must still be offered
    crowd = [_row(f"x{i}", [f"Busy{i}"]) for i in range(60) for _ in range(3)]
    candidates = suggest.build(crowd + ROWS)
    offered = [t for t, _h in suggest.matching(candidates, "Friends")]
    assert "tag:Friends" in offered and "tag:Friends/Ghitta" in offered and "tag:Friends/Dog" in offered, offered
    only_child = suggest.build([_row("z", ["Pets/Cats/Tabby"])])
    assert {t for t, _h in suggest.matching(only_child, "Pets")} >= {"tag:Pets", "tag:Pets/Cats", "tag:Pets/Cats/Tabby"}, "a level that is not a tag itself is offered too"
    counts = dict((t, h) for t, h in only_child)
    assert counts["tag:Pets"] == "tag, 1 photo"


def test_the_dictionary_shows_a_parent_and_all_its_children_together():
    dictionary = {"Friends": 1, "Friends/Ghitta": 1, "Friends/Dog": 1, "ghitta": 2, "Test": 1}
    rows = G.dictionary_rows(dictionary, {}, 0, "Friends")
    assert {e.tag for e in rows} == {"Friends", "Friends/Ghitta", "Friends/Dog"}
    assert rows[0].tag == "Friends", "the parent first"
    tree = G.build_tree(dictionary, {}, 0, "Friends")
    assert [n.name for n in tree] == ["Friends"] and sorted(c.name for c in tree[0].children) == ["Dog", "Ghitta"]
    only_children = G.dictionary_rows({"Friends/Ghitta": 1, "Friends/Dog": 1}, {}, 0, "friends")
    assert {e.tag for e in only_children} == {"Friends/Ghitta", "Friends/Dog"}


def test_a_parent_shows_a_dash_when_something_inside_it_is_attached():
    dictionary = {"People/Family": 2, "People/Friends": 1, "Holiday": 3}
    tree = G.build_tree(dictionary, {"People/Family": 1}, 1)
    people = next(n for n in tree if n.name == "People")
    assert not people.defined and people.mark == G.SOME, "darktable shows a dash on a node with an attached child"
    assert next(n for n in tree if n.name == "Holiday").mark == G.NONE
    deep = G.build_tree({"a/b/c": 1}, {"a/b/c": 1}, 1)
    assert deep[0].mark == G.SOME and deep[0].children[0].mark == G.SOME and deep[0].children[0].children[0].mark == G.ALL


_UI = textwrap.dedent(r'''
    import os, sys, time, faulthandler
    faulthandler.enable()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    import numpy as np, cv2
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtWidgets import QApplication, QMenu
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    DATA = os.environ["PHOTOEDITOR_DATA_DIR"]
    folder = os.path.join(DATA, "photos"); os.makedirs(folder)
    rng = np.random.default_rng(1)
    paths = []
    for name in ("a.png", "b.png"):
        img = cv2.GaussianBlur(rng.random((200, 300, 3)).astype(np.float32), (0, 0), 15)
        p = os.path.join(folder, name); cv2.imwrite(p, (60 + 140 * (img - img.min()) / np.ptp(img)).astype(np.uint8)); paths.append(p)
    A, B = paths
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view.premade_dialog import PremadeTagsDialog
    from photoeditor.desktop.view.quick_tag_dialog import QuickTagDialog
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
    editor = win._tags_panel.editor
    combo = editor._premade
    items = lambda: [combo.itemText(i) for i in range(combo.count())]

    # ---- nothing is pre-made until the user makes it
    assert items() == ["No pre-made tags yet - click Manage"] and c.premade_tags() == []
    assert not combo.model().item(0).isEnabled()

    # ---- Manage...: add typed tags and tags already used, remove one
    c.set_tags_for([A], add=["Friends/Ghitta", "Holiday"])
    pump(secs=0.2)
    dlg = PremadeTagsDialog([], editor._known_tags)
    assert dlg.tags() == [] and dlg._all.count() >= 2
    dlg._add([dlg._all.item(0).data(256)])
    dlg._entry.setText("People/Family"); dlg._add_typed()
    dlg._entry.setText("people/family"); dlg._add_typed()
    assert dlg.tags()[-1] == "People/Family" and len(dlg.tags()) == 2, dlg.tags()
    assert "People/Family" not in [dlg._all.item(i).data(256) for i in range(dlg._all.count())], "already on the list: not offered again"
    dlg._mine.item(0).setSelected(True); dlg._remove()
    assert dlg.tags() == ["People/Family"]
    # through the Tags section: Manage... applies the dialog's list
    PremadeTagsDialog.exec = lambda self: (self._add(["Holiday", "Friends/Ghitta"]), True)[1]
    editor._manage_premade()
    assert pump(lambda: c.premade_tags() == ["Holiday", "Friends/Ghitta"]), c.premade_tags()
    assert items() == ["Add a pre-made tag...", "Holiday", "Friends › Ghitta"], items()
    assert "Holiday" in c.tagging_data([])[1], "pre-made tags are in the dictionary too"
    assert win._lighttable._tags._premade.count() == 3, "the Workbench's tag box has the same list"
    assert win._tagging_panel._premade == ["Holiday", "Friends/Ghitta"]

    # ---- pick one: it is added to the photo
    c.set_tags_for([A], remove=["Holiday"])
    pump(secs=0.2)
    got = []
    editor.add_requested.connect(got.append)
    combo.activated.emit(combo.findData("Holiday"))
    assert got == [["Holiday"]] and combo.currentIndex() == 0

    # ---- the quick tag bar offers them even when no photo has them yet
    c.add_premade(["Subject/Night"])
    usage = c.tag_usage()
    dlg = QuickTagDialog(usage, 1, premade=c.premade_tags())
    dlg._entry.setText("nigh")
    assert dlg.results()[0] == "Subject/Night"
    dlg2 = QuickTagDialog(usage, 1)
    dlg2._entry.setText("nigh")
    assert dlg2.results() != ["Subject/Night"] or "Subject/Night" in usage
    QuickTagDialog.exec = lambda self: (self._entry.setText("nigh"), self._pick(self.selected()))
    win.quick_tag()
    assert "Subject/Night" in c.photo_tags(A)

    # ---- the Tagging panel's right-click: add to / remove from the pre-made list
    P = win._tagging_panel
    P._entry.setText("")
    chosen = {}
    QMenu.exec = lambda self, *a: next(x for x in self.actions() if x.text() == chosen["action"])
    row = next(i for i in range(P._list.count()) if P._list.item(i).data(256) == "Friends/Ghitta")
    P._list.itemAt = lambda pos: P._list.item(row)
    chosen["action"] = "Remove from my pre-made tags"
    P._dictionary_menu(P._list, QPoint(2, 2)); pump(secs=0.2)
    assert c.premade_tags() == ["Holiday", "Subject/Night"] and "Friends/Ghitta" in c.tagging_data([])[1], "the tag itself is untouched"
    assert "Friends/Ghitta" in c.photo_tags(A)
    chosen["action"] = "Add to my pre-made tags"
    P._dictionary_menu(P._list, QPoint(2, 2)); pump(secs=0.2)
    assert c.premade_tags() == ["Holiday", "Subject/Night", "Friends/Ghitta"]
    P._attached.itemAt = lambda pos: P._attached.item(0)
    c.remove_premade(["Holiday"]); pump(secs=0.2)
    assert win._tags_panel.editor._premade_list == ["Subject/Night", "Friends/Ghitta"]

    # ---- it survives a restart (a new window reads the same file)
    win2 = aw.AppWindow(); app.processEvents()
    assert win2.controller.premade_tags() == ["Subject/Night", "Friends/Ghitta"]
    assert win2._tags_panel.editor._premade.count() == 3
    print("PREMADE UI OK"); sys.stdout.flush(); os._exit(0)
''')


def test_premade_tags_in_the_running_app():
    data = tempfile.mkdtemp()
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""), PHOTOEDITOR_DATA_DIR=data)
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _UI], env=env, capture_output=True, text=True, timeout=600)
    assert "PREMADE UI OK" in done.stdout, done.stdout[-1500:] + done.stderr[-4000:]
