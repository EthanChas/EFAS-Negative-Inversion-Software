"""Virtual copies: the version store, switching between versions in the editor, the Workbench's badge and button, and exporting every version."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from photoeditor.features.library import query as Q  # noqa: E402
from photoeditor.features.persistence import edit_store  # noqa: E402


def state(**kw):
    from photoeditor.desktop.export_worker import default_edit_state

    s = default_edit_state(True)
    s.update(kw)
    return s


def test_the_store_keeps_every_version_and_which_one_is_being_edited(tmp_path):
    conn = edit_store.connect(str(tmp_path / "e.db"))
    p = "/x/a.jpg"
    assert edit_store.active_version(conn, p) == "Original" and edit_store.version_names(conn, p) == ["Original"]
    edit_store.put_version(conn, p, "Original", state(exposure_ev=0.5))
    edit_store.set_active_version(conn, p, "Copy 2")
    assert edit_store.active_version(conn, p) == "Copy 2"
    assert edit_store.version_names(conn, p) == ["Original", "Copy 2"]
    assert edit_store.get_version_state(conn, p, "Original")["exposure_ev"] == 0.5
    assert edit_store.get_version_state(conn, p, "missing") is None
    assert edit_store.version_counts(conn) == {p: 2}
    assert edit_store.rename_version(conn, p, "Copy 2", "Black and white") and edit_store.active_version(conn, p) == "Black and white"
    assert edit_store.rename_version(conn, p, "Original", "Colour") and edit_store.version_names(conn, p) == ["Black and white", "Colour"]
    edit_store.set_active_version(conn, p, "Original")
    assert conn.execute("SELECT COUNT(*) FROM photo_active_version").fetchone()[0] == 0, "back on the default name leaves no row"
    assert edit_store.delete_version(conn, p, "Colour") and not edit_store.delete_version(conn, p, "Colour")


def test_the_workbench_counts_versions_and_search_finds_photos_with_copies():
    rows = Q.build_rows(
        [{"path": "/x/a.jpg", "folder": "/x", "name": "a", "ext": "jpg", "taken": "2026-01-01 00:00:00", "taken_exif": 1, "camera": "", "lens": "", "iso": 0, "make": ""},
         {"path": "/x/b.jpg", "folder": "/x", "name": "b", "ext": "jpg", "taken": "2026-01-01 00:00:00", "taken_exif": 1, "camera": "", "lens": "", "iso": 0, "make": ""}],
        Q.Meta(versions={Q.norm("/x/a.jpg"): 3}),
    )
    assert [r["versions"] for r in rows] == [3, 1]
    assert [r["name"] for r in rows if Q.matches(r, Q.Query(text="versions:>1"))] == ["a"]
    assert [r["name"] for r in rows if Q.matches(r, Q.Query(text="copies:1"))] == ["b"]


_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.features.persistence import edit_store
    from photoeditor.features.library.index import LibraryIndex
    from photoeditor.features.export import logic as X
    from photoeditor.desktop.export_worker import export_photos
    S.save({"scan_quality": False})
    folder = os.path.join(work, "roll"); os.makedirs(folder)
    paths = []
    for i in range(2):
        p = os.path.join(folder, f"img{i}.png"); paths.append(p)
        img = np.zeros((60, 90, 3), np.uint8); img[..., 1] = 90; img[10:30, 10:50] = 190
        cv2.imwrite(p, img)
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw

    win = aw.AppWindow(); c = win.controller
    c.open_file(paths[0])
    assert c.version_list() == [("Original", True)]
    c.set_exposure_ev(0.75); c._save_edit_state()

    # make a copy: you are on it, Original is kept
    name = c.new_version()
    assert name == "Copy 2" and c.version_list() == [("Copy 2", True), ("Original", False)] or c.version_list() == [("Original", False), ("Copy 2", True)]
    assert win._versions_panel._list.count() == 2
    assert c.state.exposure_ev == 0.75
    c.set_exposure_ev(-1.0); c.state.rotation_quarter_turns = 1; c._save_edit_state()
    assert edit_store.get_version_state(c._db, paths[0], "Original")["exposure_ev"] == 0.75

    # switch back and forth: each version keeps its own edit
    assert c.switch_version("Original")
    assert c.state.exposure_ev == 0.75 and c.state.rotation_quarter_turns == 0 and edit_store.active_version(c._db, paths[0]) == "Original"
    assert edit_store.load_edit_state(c._db, paths[0])["exposure_ev"] == 0.75
    assert c.switch_version("Copy 2")
    assert c.state.exposure_ev == -1.0 and c.state.rotation_quarter_turns == 1
    assert not c.switch_version("Copy 2") and not c.switch_version("nope")

    # a version survives closing and reopening, and other photos are unaffected
    c.open_file(paths[1]); assert c.state.exposure_ev == 0.0 and c.version_list() == [("Original", True)]
    c.open_file(paths[0]); assert c.state.exposure_ev == -1.0 and [n for n, a in c.version_list() if a] == ["Copy 2"]

    # rules for rename and delete
    assert not c.delete_version("Copy 2"), "the version being edited cannot be deleted"
    assert not c.rename_version("Original", "copy 2"), "names are unique"
    assert c.rename_version("Copy 2", "Turned") and [n for n, a in c.version_list() if a] == ["Turned"]
    assert win._versions_panel._list.count() == 2

    # the Workbench: Make Virtual Copy on a photo that is not open, the badge count, and the search
    index = LibraryIndex(); index.refresh([folder]); index.close()
    win.open_folder(folder, prefer=paths[0]); win._lighttable_reload_rows()
    counts = {os.path.basename(r["path"]): r["versions"] for r in win._lighttable._shown}
    assert counts == {"img0.png": 2, "img1.png": 1}, counts
    win.make_virtual_copies([paths[1]])
    counts = {os.path.basename(r["path"]): r["versions"] for r in win._lighttable._shown}
    assert counts["img1.png"] == 2
    assert edit_store.active_version(c._db, paths[1]) == "Original" and edit_store.get_version_state(c._db, paths[1], "Copy 2") is not None
    win._lighttable._search.setText("versions:>1"); win._lighttable.apply_filters()
    assert len(win._lighttable._shown) == 2

    # exporting: one file per version when asked, none extra when not
    out = os.path.join(work, "out")
    base = X.ExportOptions(fmt="png", dest_mode="folder", folder=out, on_conflict="overwrite")
    export_photos([paths[0]], [("plain", base)], c.db_path)
    assert sorted(os.listdir(out)) == ["img0.png"]
    import dataclasses
    export_photos([paths[0]], [("all", dataclasses.replace(base, include_versions=True, write_record=True))], c.db_path)
    names = sorted(os.listdir(out))
    assert "img0.png" in names and "img0_Original.png" in names and "img0_Original.png.efas.json" in names, names
    a = cv2.imread(os.path.join(out, "img0.png")); b = cv2.imread(os.path.join(out, "img0_Original.png"))
    assert a.shape[:2] == (90, 60) and b.shape[:2] == (60, 90), "the turned version and the original differ"
    win.close()
    print("VERSIONS OK")
''')


def test_versions_in_the_editor_the_workbench_and_export():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert "VERSIONS OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3500:]
