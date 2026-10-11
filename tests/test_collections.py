"""Smart collections: saved Workbench filters that re-run on the library each time."""
import os
import subprocess
import sys
import textwrap
from datetime import date
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from photoeditor.features.library import query as Q  # noqa: E402
from photoeditor.features.persistence import edit_store  # noqa: E402


def row(name, **kw):
    r = {"path": f"/x/{name}.jpg", "folder": "/x", "name": name, "ext": "jpg", "taken": "2026-10-05 10:00:00", "taken_exif": 1, "camera": "Canon A", "lens": "", "iso": 400, "make": ""}
    r.update(kw)
    return r


def test_a_state_is_cleaned_before_use_and_defaults_fill_the_gaps():
    s = Q.clean_state({"text": "canon", "rating": "five", "flag": "bogus", "sort": "nope", "edited": "yes", "junk": 1, "iso": 400, "descending": True})
    assert s["text"] == "canon" and s["rating"] == 0 and s["flag"] == "any" and s["sort"] == "taken" and s["edited"] is None and s["iso"] == 400 and s["descending"] is True
    assert "junk" not in s and Q.clean_state(None) == Q.default_state() and Q.clean_state([1]) == Q.default_state()


def test_relative_dates_follow_the_day_they_are_used_on():
    assert Q.when_range("7", today=date(2026, 10, 10)) == ("2026-10-03", "2026-10-10")
    assert Q.when_range("year", today=date(2026, 3, 1)) == ("2026-01-01", "2026-12-31")
    assert Q.when_range("custom", "2026-01-01", "2026-02-01") == ("2026-01-01", "2026-02-01")
    assert Q.when_range("", today=date(2026, 1, 1)) == ("", "")
    s = {**Q.default_state(), "when": "7"}
    assert Q.query_from_state(s, date(2026, 10, 10)).date_from == "2026-10-03" and Q.query_from_state(s, date(2026, 11, 10)).date_from == "2026-11-03"


def test_a_state_becomes_the_same_query_the_panel_would_make():
    q = Q.query_from_state({**Q.default_state(), "text": "x", "rating": 3, "flag": "not_rejected", "edited": False, "camera": "Canon A", "iso": 400, "sort": "name", "descending": True})
    assert (q.text, q.rating_min, q.flags, q.edited, q.camera, q.iso, q.sort, q.descending) == ("x", 3, ("keeper", "none"), False, "Canon A", 400, "name", True)
    assert q.is_filtering() and not Q.query_from_state({}).is_filtering()


def test_collections_pick_up_new_photos_without_being_edited():
    state = {**Q.default_state(), "rating": 4}
    meta = Q.Meta(ratings={Q.norm("/x/a.jpg"): 5})
    rows = Q.build_rows([row("a")], meta)
    assert [r["name"] for r in Q.filter_rows(rows, Q.query_from_state(state))] == ["a"]
    meta.ratings[Q.norm("/x/b.jpg")] = 4
    rows = Q.build_rows([row("a"), row("b"), row("c")], meta)
    assert [r["name"] for r in Q.filter_rows(rows, Q.query_from_state(state))] == ["a", "b"]


def test_describe_says_what_the_filters_are():
    assert Q.describe_state({}) == "everything"
    d = Q.describe_state({**Q.default_state(), "text": "light leak", "rating": 4, "camera": "Canon A", "when": "30", "edited": True})
    assert "light leak" in d and "4+ stars" in d and "camera Canon A" in d and "last 30 days" in d and "edited" in d


def test_the_store_saves_replaces_renames_and_deletes(tmp_path):
    conn = edit_store.connect(str(tmp_path / "e.db"))
    edit_store.save_collection(conn, "Keepers", {"rating": 4})
    edit_store.save_collection(conn, "keepers", {"rating": 5})
    edit_store.save_collection(conn, "Portra", {"film": "Portra"})
    assert edit_store.list_collections(conn) == [("Keepers", {"rating": 5}), ("Portra", {"film": "Portra"})]
    assert edit_store.rename_collection(conn, "Portra", "Portra 400")
    assert not edit_store.rename_collection(conn, "Portra 400", "keepers"), "a name already in use is refused"
    assert edit_store.delete_collection(conn, "Keepers") and not edit_store.delete_collection(conn, "Keepers")
    assert [n for n, _s in edit_store.list_collections(conn)] == ["Portra 400"]


_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox
    from photoeditor.features.settings import logic as S
    from photoeditor.features.persistence import edit_store
    from photoeditor.features.library.index import LibraryIndex
    S.save({"scan_quality": False})
    folder = os.path.join(work, "roll"); os.makedirs(folder)
    paths = []
    for i in range(4):
        p = os.path.join(folder, f"img{i}.png"); paths.append(p)
        cv2.imwrite(p, np.full((40, 60, 3), 30 * i + 20, np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); c = win.controller; lt = win._lighttable
    index = LibraryIndex(); index.refresh([folder]); index.close()
    win.open_folder(folder, prefer=paths[0])
    c.set_rating_for(paths[1], 5); c.set_rating_for(paths[2], 4)
    win._lighttable_reload_rows()
    def shown(): return sorted(os.path.basename(r["path"]) for r in lt._shown)
    assert len(shown()) == 4 and lt._collection_box.count() == 1 and not lt._collection_delete.isEnabled()

    # save the current filters under a name
    lt._rating.setCurrentIndex(lt._rating.findData(4)); assert shown() == ["img1.png", "img2.png"]
    QInputDialog.getText = staticmethod(lambda *a, **k: ("Best of", True))
    lt._save_collection()
    assert [n for n, _s in edit_store.list_collections(c._db)] == ["Best of"]
    assert lt._collection_box.currentData() == "Best of" and "Best of  (2)" in lt._collection_box.currentText()

    # clearing the filters and picking the collection restores them
    lt.clear_filters(); assert len(shown()) == 4
    lt._collection_box.setCurrentIndex(0); lt._collection_box.setCurrentIndex(1)
    assert shown() == ["img1.png", "img2.png"] and lt._rating.currentData() == 4

    # a new photo that fits shows up in it without touching the collection
    c.set_rating_for(paths[3], 5); win._lighttable_reload_rows()
    assert shown() == ["img1.png", "img2.png", "img3.png"], shown()
    assert "Best of  (3)" in lt._collection_box.currentText()

    # a collection that mentions a camera the library lacks keeps it and matches nothing
    lt.set_filter_state({"camera": "Leica M3", "text": ""})
    assert shown() == [] and lt._camera.currentData() == "Leica M3"
    win._lighttable_reload_rows(); assert lt._camera.currentData() == "Leica M3" and shown() == []
    lt.clear_filters(); assert len(shown()) == 4

    # collections are remembered by the next window, and deleting asks first
    win2 = aw.AppWindow()
    assert win2._lighttable._collection_box.count() == 2
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    win._on_collection_delete("Best of"); assert len(edit_store.list_collections(c._db)) == 1
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    win._on_collection_delete("Best of"); assert edit_store.list_collections(c._db) == [] and lt._collection_box.count() == 1
    win2.close(); win.close()
    print("COLLECTIONS OK")
''')


def test_smart_collections_in_the_workbench():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert "COLLECTIONS OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3500:]
