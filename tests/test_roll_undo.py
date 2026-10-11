"""Undoing whole-roll actions: the journal, what an undo will and will not touch, and the Undo button for Crop Roll, Reset Crops and paste to folder."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from photoeditor.desktop.export_worker import default_edit_state  # noqa: E402
from photoeditor.features.persistence import edit_store, roll_undo  # noqa: E402


@pytest.fixture
def conn(tmp_path):
    return edit_store.connect(str(tmp_path / "e.db"))


def seed(conn, path, **fields):
    s = default_edit_state(True)
    s.update(fields)
    edit_store.save_edit_state(conn, path, s)
    return s


def test_an_undo_restores_what_the_action_changed_and_removes_its_entry(conn, tmp_path):
    folder = str(tmp_path)
    paths = [str(tmp_path / f"p{i}.png") for i in range(3)]
    ops = []
    for p in paths:
        seed(conn, p, crop_rect=None, fine_rotation=0.0)
        ops.append(roll_undo.fields_op(p, {"crop_rect": None, "fine_rotation": 0.0}, {"crop_rect": (10, 20, 300, 200), "fine_rotation": 1.5}))
        s = edit_store.load_edit_state(conn, p)
        s["crop_rect"], s["fine_rotation"] = (10, 20, 300, 200), 1.5
        edit_store.save_edit_state(conn, p, s)
    roll_undo.record(conn, folder, "Crop Roll", ops)
    entry = roll_undo.latest(conn, folder)
    assert entry.label == "Crop Roll" and len(entry.ops) == 3
    res = roll_undo.undo(conn, entry)
    assert sorted(res.restored) == sorted(paths) and not res.skipped
    for p in paths:
        s = edit_store.load_edit_state(conn, p)
        assert s["crop_rect"] is None and s["fine_rotation"] == 0.0
    assert roll_undo.latest(conn, folder) is None


def test_a_photo_edited_since_is_left_alone_and_reported(conn, tmp_path):
    a, b = str(tmp_path / "a.png"), str(tmp_path / "b.png")
    after = {"crop_rect": (1, 2, 30, 40)}
    ops = []
    for p in (a, b):
        seed(conn, p, crop_rect=after["crop_rect"])
        ops.append(roll_undo.fields_op(p, {"crop_rect": None}, after))
    s = edit_store.load_edit_state(conn, b)
    s["crop_rect"] = (5, 5, 50, 50)
    edit_store.save_edit_state(conn, b, s)
    roll_undo.record(conn, str(tmp_path), "Crop Roll", ops)
    res = roll_undo.undo(conn, roll_undo.latest(conn, str(tmp_path)))
    assert res.restored == [a] and res.skipped == [(b, "it was edited since")]
    assert edit_store.load_edit_state(conn, b)["crop_rect"] == (5, 5, 50, 50) and edit_store.load_edit_state(conn, a)["crop_rect"] is None


def test_other_edits_made_since_do_not_block_an_undo_of_the_crop(conn, tmp_path):
    p = str(tmp_path / "a.png")
    seed(conn, p, crop_rect=(1, 2, 30, 40))
    roll_undo.record(conn, str(tmp_path), "Crop Roll", [roll_undo.fields_op(p, {"crop_rect": None}, {"crop_rect": (1, 2, 30, 40)})])
    s = edit_store.load_edit_state(conn, p)
    s["exposure_ev"] = 0.7
    edit_store.save_edit_state(conn, p, s)
    res = roll_undo.undo(conn, roll_undo.latest(conn, str(tmp_path)))
    now = edit_store.load_edit_state(conn, p)
    assert res.restored == [p] and now["crop_rect"] is None and now["exposure_ev"] == 0.7, "later work on other things is kept"


def test_a_deleted_edit_row_and_the_open_photo_are_not_touched(conn, tmp_path):
    a, b = str(tmp_path / "a.png"), str(tmp_path / "b.png")
    for p in (a, b):
        seed(conn, p, crop_rect=(1, 1, 9, 9))
    roll_undo.record(conn, str(tmp_path), "Crop Roll", [roll_undo.fields_op(p, {"crop_rect": None}, {"crop_rect": (1, 1, 9, 9)}) for p in (a, b)])
    conn.execute("DELETE FROM edits WHERE path = ?", (a,))
    conn.commit()
    res = roll_undo.undo(conn, roll_undo.latest(conn, str(tmp_path)), skip_paths={b})
    assert res.skipped == [(a, "it no longer has saved edits")] and res.restored == []
    assert edit_store.load_edit_state(conn, b)["crop_rect"] == (1, 1, 9, 9), "the open photo is left to Ctrl+Z"


def test_per_photo_film_base_changes_are_journalled_too(conn, tmp_path):
    p = str(tmp_path / "a.png")
    edit_store.set_photo_film_base(conn, p, (200, 150, 100))
    roll_undo.record(conn, str(tmp_path), "Even Out Roll", [roll_undo.film_base_op(p, None, (200, 150, 100))])
    res = roll_undo.undo(conn, roll_undo.latest(conn, str(tmp_path)))
    assert res.restored == [p] and edit_store.get_photo_film_base(conn, p) is None
    edit_store.set_photo_film_base(conn, p, (1, 2, 3))
    roll_undo.record(conn, str(tmp_path), "Even Out Roll", [roll_undo.film_base_op(p, None, (200, 150, 100))])
    res = roll_undo.undo(conn, roll_undo.latest(conn, str(tmp_path)))
    assert res.skipped and edit_store.get_photo_film_base(conn, p) == (1, 2, 3)


def test_effective_film_base_prefers_the_photos_own(conn, tmp_path):
    p = str(tmp_path / "a.png")
    edit_store.set_folder_base(conn, edit_store.folder_key(p), (10, 20, 30))
    assert edit_store.effective_film_base(conn, p) == (10, 20, 30)
    edit_store.set_photo_film_base(conn, p, (40, 50, 60))
    assert edit_store.effective_film_base(conn, p) == (40, 50, 60)
    edit_store.set_photo_film_base(conn, p, None)
    assert edit_store.effective_film_base(conn, p) == (10, 20, 30)


def test_only_the_last_few_actions_per_folder_are_kept_and_an_empty_action_is_not_recorded(conn, tmp_path):
    f1, f2 = str(tmp_path / "one"), str(tmp_path / "two")
    for i in range(8):
        roll_undo.record(conn, f1, f"A{i}", [roll_undo.fields_op("/x/a.png", {"crop_rect": None}, {"crop_rect": [i]})])
    roll_undo.record(conn, f2, "Other", [roll_undo.fields_op("/x/b.png", {"crop_rect": None}, {"crop_rect": [1]})])
    assert roll_undo.record(conn, f1, "Nothing", []) is None
    assert conn.execute("SELECT COUNT(*) FROM roll_undo WHERE folder = ?", (edit_store.folder_key(f1, is_file=False),)).fetchone()[0] == roll_undo.KEEP
    assert roll_undo.latest(conn, f1).label == "A7" and roll_undo.latest(conn, f2).label == "Other"


_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    folder = os.path.join(work, "roll"); os.makedirs(folder)
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from photoeditor.features.settings import logic as S
    from photoeditor.features.persistence import edit_store
    S.save({"scan_quality": False})
    def scan(seed):
        rng = np.random.default_rng(seed)
        img = np.full((240, 360, 3), 25, np.uint8)
        pic = cv2.GaussianBlur(rng.random((160, 240, 3)).astype(np.float32), (0, 0), 4)
        img[40:200, 60:300] = (90 + 110 * (pic - pic.min()) / np.ptp(pic)).astype(np.uint8)
        return img
    paths = []
    for i in range(4):
        p = os.path.join(folder, f"f{i}.png"); cv2.imwrite(p, scan(i)); paths.append(p)
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); c = win.controller
    win.open_folder(folder, prefer=paths[0])
    shown = []
    QMessageBox.information = staticmethod(lambda *a, **k: shown.append(a[2]))
    QMessageBox.warning = staticmethod(lambda *a, **k: shown.append(a[2]))
    go = {"crop": True, "undo": True}
    win._ask_bulk_crop = lambda mode, n, cropped: (go["crop"], False)
    win._ask_undo_roll = lambda label, n: go["undo"]
    def saved(p): return edit_store.load_edit_state(c._db, p)
    def crop_roll():
        win.bulk_crop("auto"); win._bulk_worker.wait(120000); app.processEvents()
    strip = win._filmstrip
    assert not strip._undo_roll_btn.isEnabled() and strip._undo_roll_btn.text() == "Undo"

    crop_roll()
    assert all(saved(p) and saved(p)["crop_rect"] for p in paths[1:]), "the others were cropped"
    assert strip._undo_roll_btn.isEnabled() and strip._undo_roll_btn.text() == "Undo Crop Roll" and "3 photos" in strip._undo_roll_btn.toolTip()

    # one photo is edited afterwards: the undo leaves it, restores the rest, and the open photo is left to Ctrl+Z
    st = saved(paths[2]); st["crop_rect"] = (7, 7, 100, 100); edit_store.save_edit_state(c._db, paths[2], st)
    go["undo"] = False; win.undo_roll_action()
    assert saved(paths[1])["crop_rect"] is not None and strip._undo_roll_btn.isEnabled(), "declining changes nothing"
    go["undo"] = True; shown.clear(); win.undo_roll_action()
    assert saved(paths[1])["crop_rect"] is None and saved(paths[3])["crop_rect"] is None
    assert saved(paths[2])["crop_rect"] == (7, 7, 100, 100)
    assert "Undid Crop Roll on 2 photos" in shown[-1] and "f2.png" in shown[-1] and "edited since" in shown[-1]
    assert c.state.crop_rect is not None, "the open photo is not changed by the undo"
    assert not strip._undo_roll_btn.isEnabled()

    # Reset Crops can be undone too, and the journal survives a restart
    win.bulk_crop("reset"); win._bulk_worker.wait(120000); app.processEvents()
    assert saved(paths[2])["crop_rect"] is None and strip._undo_roll_btn.text() == "Undo Reset Crops"
    win.close()
    win2 = aw.AppWindow(); win2.open_folder(folder, prefer=paths[0])
    s2 = win2._filmstrip
    assert s2._undo_roll_btn.isEnabled() and s2._undo_roll_btn.text() == "Undo Reset Crops", "kept across a restart"
    win2._ask_undo_roll = lambda label, n: True
    win2.undo_roll_action()
    assert edit_store.load_edit_state(win2.controller._db, paths[2])["crop_rect"] == (7, 7, 100, 100)

    # paste to folder
    c2 = win2.controller
    c2.set_exposure_ev(0.8); c2._save_edit_state()
    n = c2.paste_settings_to_folder(c2._clean_look({"exposure_ev": 0.8}), "Pasted settings") if hasattr(c2, "_clean_look") else 0
    assert n >= 2 and edit_store.load_edit_state(c2._db, paths[3])["exposure_ev"] == 0.8
    assert s2._undo_roll_btn.text() == "Undo Pasted settings", (s2._undo_roll_btn.text(), c2.roll_undo_entry(os.path.dirname(paths[0])))
    win2.undo_roll_action()
    assert edit_store.load_edit_state(c2._db, paths[3])["exposure_ev"] == 0.0 and c2.state.exposure_ev == 0.8
    win2.close()
    print("ROLL UNDO OK")
''')


def test_undo_for_whole_roll_actions_in_the_editor():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert "ROLL UNDO OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3500:]
