"""Finishing a live session and retaking a photo, end to end in the window: the Finish Session button files the session's photos into a dated folder with everything saved for them,
and a retake lets the next photo to arrive take the place of one (the old one set aside, not deleted)."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    from datetime import datetime
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp()
    shoot = os.path.join(work, "shoot"); other = os.path.join(work, "other"); day = os.path.join(shoot, "2026_10_16")
    os.makedirs(day); os.makedirs(other)
    import numpy as np, cv2
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False, "advanced_mode": False})
    def frame(path, seed, shape=(60, 90, 3)):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cv2.imwrite(path, np.random.default_rng(seed).integers(30, 220, shape, dtype=np.uint8))
        return path
    old1 = frame(os.path.join(shoot, "old1.png"), 1); frame(os.path.join(other, "elsewhere.png"), 3)
    from PyQt6.QtWidgets import QApplication, QMessageBox
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.features.library import query as Q
    from photoeditor.features.persistence import edit_store as E
    win = aw.AppWindow(); win.show(); win.open_folder(other)
    def pump(s):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    def until(cond, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            app.processEvents()
            if cond(): return True
            time.sleep(0.01)
        return False
    pump(1.0)
    lt = win._lighttable; live = win._live; db = win.controller._db
    live._interval = 60
    got = []; live.arrived.connect(got.append)
    asked = []
    QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[2]), QMessageBox.StandardButton.Yes)[1])
    win.set_view("lighttable"); pump(0.5)
    assert until(lambda: win._index_worker is None)
    lt._live_editor_action.setChecked(False)
    win.arm_retake(old1)
    assert win._retake is None and "hotstack" in win._coord_label.text(), "a retake needs a hotstack folder to catch the new photo"
    win._on_hotstack_requested(shoot, True); pump(0.3)
    assert live.running() and live.folders() == [shoot]
    assert until(lambda: win._index_worker is None)
    assert not lt._finish_btn.isVisible(), "nothing has arrived yet: no Finish Session button"
    def arrive(path):
        n = len(got); path = path() if callable(path) else path
        assert until(lambda: len(got) > n), "arrived"
        return path
    norm = Q.norm

    # three photos arrive (in EOS Utility's day folder): the session counts them and the Finish Session button shows
    f1 = arrive(lambda: frame(os.path.join(day, "f1.png"), 11))
    f2 = arrive(lambda: frame(os.path.join(day, "f2.png"), 12))
    f3 = arrive(lambda: frame(os.path.join(day, "f3.png"), 13))
    assert lt._finish_btn.isVisible() and lt._finish_btn.text() == "Finish Session (3)", lt._finish_btn.text()
    assert win._finish_live_action.isEnabled()
    assert not hasattr(lt, "_retake_btn"), "Retake is not in the right-hand panel"

    # the button is only there while the person is in the hotstack folder: not with a photo from another folder selected, not browsing another folder in the Library list
    elsewhere = os.path.join(other, "elsewhere.png")
    lt.select_path(elsewhere); pump(0.2)
    assert not lt._finish_btn.isVisible() and not win._finish_live_action.isEnabled(), "a photo outside the hotstack is selected"
    assert not lt._hot_btn.isVisible() and not win._retake_action.isVisible(), "the flame button and Retake are only there inside the hotstack"
    assert "Retake This Photo" not in [a.text() for a in lt.build_context_menu().actions()], "not in the photo's right-click menu either"
    assert "Retake elsewhere.png" not in [a.text() for a in win._filmstrip.build_context_menu(elsewhere).actions()]
    tree = lt.library_panel._tree
    tree.add_root(shoot); tree.add_root(other)
    def click(folder):
        item = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount()) if tree.topLevelItem(i).data(0, 256) == folder)
        tree.setCurrentItem(item); item.setSelected(True); tree._on_clicked(item, 0); pump(0.2)
    click(other)
    assert not lt._finish_btn.isVisible() and not lt._hot_btn.isVisible(), "browsing another folder"
    click(shoot)
    assert lt._finish_btn.isVisible() and lt.library_panel.selected_folder() == shoot, "browsing the hotstack folder"
    assert lt._hot_btn.isVisible() and lt._retake_action.text() == "Retake This Photo"
    lt._clear_library_selection(); lt.select_path(f3); pump(0.2)
    assert lt._finish_btn.isVisible(), "a photo of the hotstack is selected"
    win.open_in_editor(f3)
    assert until(lambda: norm(win.controller.state.image_path or "") == norm(f3))
    assert win._finish_live_action.isEnabled(), "in the editor with a hotstack photo open"
    assert win._retake_action.isVisible() and f"Retake {os.path.basename(f3)}" in [a.text() for a in win._filmstrip.build_context_menu(f3).actions()]
    win.open_in_editor(elsewhere)
    assert until(lambda: norm(win.controller.state.image_path or "") == norm(elsewhere))
    assert not win._finish_live_action.isEnabled(), "in the editor with another photo open"
    assert not win._retake_action.isVisible(), "no Retake in the File menu for a photo outside the hotstack"
    win.set_view("lighttable"); pump(0.3); lt.select_path(f3); pump(0.2)
    assert lt._finish_btn.isVisible()
    assert [norm(p) for p in S.load()["live_session"]] == [norm(f1), norm(f2), norm(f3)], "kept across restarts"

    # things saved for the photos: a rating, a flag, tags, a sidecar, and a Roll Card for the folder they are in
    win.controller.set_rating_for(f1, 3); win.controller.set_flag_for(f1, "keeper")
    E.add_tags(db, [f1], ["family"]); E.add_tags(db, [f2], ["street"])
    win.controller.set_rating_for(f2, 4); win.controller.set_flag_for(f2, "rejected")
    E.set_folder_roll(db, E.folder_key(day, is_file=False), {"film": "Portra 400"})
    with open(f2 + ".xmp", "w") as fh: fh.write("<sidecar/>")
    old2_size = os.path.getsize(f2)

    # retake f2: select it, choose Retake in the flame button's menu (it says so), choose it again to cancel, and once more
    lt.select_path(f2); pump(0.2)
    assert lt._hot_btn.isVisible() and lt._retake_action.isEnabled() and lt._retake_action.text() == "Retake This Photo"
    assert "Retake This Photo" in [a.text() for a in lt.build_context_menu().actions()], "and in the photo's right-click menu, inside the hotstack"
    lt._retake_action.trigger(); pump(0.1)
    assert win._retake == f2 and lt._retake_action.text() == "Cancel Retake" and win._cancel_retake_action.isEnabled() and win._cancel_retake_action.isVisible()
    lt._retake_action.trigger(); pump(0.1)
    assert win._retake is None and lt._retake_action.text() == "Retake This Photo" and not win._cancel_retake_action.isEnabled() and not win._cancel_retake_action.isVisible()
    lt._retake_action.trigger(); pump(0.1)
    assert win._retake == f2
    new2 = arrive(lambda: frame(os.path.join(day, "4N0A_retake.png"), 22, (80, 120, 3)))
    pump(0.5)
    aside2 = os.path.join(day, "Retakes", "f2.png")
    assert win._retake is None, "the retake is used up"
    assert not os.path.exists(new2) and os.path.isfile(f2) and os.path.getsize(f2) != old2_size, "the new photo took the old one's name and place"
    assert os.path.isfile(aside2) and os.path.getsize(aside2) == old2_size and os.path.isfile(aside2 + ".xmp") and not os.path.isfile(f2 + ".xmp"), "the old one is set aside, with its sidecar"
    assert E.get_ratings(db, [f2, aside2]) == {aside2: 4} and E.get_flags(db, [f2, aside2]) == {aside2: "rejected"}, "the rating and flag judged the old photo"
    assert E.get_tags(db, [f2, aside2]) == {f2: ["street"], aside2: ["street"]}
    assert norm(aside2) in E.hidden_keys(db), "the set-aside photo is off the Workbench (still on disk)"
    assert [norm(p) for p in win._live_session] == [norm(f1), norm(f2), norm(f3)] and [norm(p) for p in win._live_aside] == [norm(aside2)]
    assert len(got) == 4 and all("Retakes" not in p for p in got), "the set-aside photo was not reported as new: " + repr(got)
    assert [norm(p) for p in lt.selected_paths()] == [norm(f2)] and "Retake" in win._coord_label.text()
    assert norm(aside2) not in {norm(r["path"]) for r in lt.all_rows()}

    # retake the photo that is open in the editor: the editor shows the new file afterwards
    win.open_in_editor(f3)
    assert until(lambda: norm(win.controller.state.image_path or "") == norm(f3))
    assert win.controller.state.original_rgb.shape[:2] == (60, 90)
    win.arm_retake(f3)
    arrive(lambda: frame(os.path.join(day, "4N0A_retake2.png"), 23, (70, 100, 3)))
    pump(0.3)
    assert norm(win.controller.state.image_path) == norm(f3) and win.controller.state.original_rgb.shape[:2] == (70, 100), win.controller.state.original_rgb.shape
    win.set_view("lighttable"); pump(0.3)

    # a photo from before the session can be retaken too: it is replaced in place, and is not part of the session
    old1_size = os.path.getsize(old1)
    win.arm_retake(old1)
    arrive(lambda: frame(os.path.join(day, "4N0A_retake3.png"), 24, (50, 50, 3)))
    pump(0.3)
    assert os.path.isfile(old1) and os.path.getsize(old1) != old1_size and os.path.getsize(os.path.join(shoot, "Retakes", "old1.png")) == old1_size
    assert norm(old1) not in {norm(p) for p in win._live_session} and len(win._live_aside) == 2

    # a retake of a photo that has gone is not an error: the new photo is just kept
    ghost = frame(os.path.join(day, "ghost.png"), 30)
    arrive(lambda: ghost); win.arm_retake(ghost)
    os.remove(ghost)
    kept = arrive(lambda: frame(os.path.join(day, "kept.png"), 31))
    assert os.path.isfile(kept) and win._retake is None and "not there any more" in win._coord_label.text(), win._coord_label.text()
    session_n = len(win._live_session)
    assert lt._finish_btn.text() == f"Finish Session ({session_n})"

    # finish the session: the photos go into a folder for today, with everything saved for them
    today = datetime.now().strftime("%d-%m-%Y")
    dated = os.path.join(shoot, today)
    win.controller.set_rating_for(f1, 5)
    n_got = len(got)
    lt.select_path(kept); pump(0.2)
    assert lt._finish_btn.isVisible()
    lt._finish_btn.click(); pump(1.0)
    assert asked and today in asked[-1] and "Nothing is deleted" in asked[-1], asked[-1]
    for name in ("f1.png", "f2.png", "f3.png", "kept.png"):
        assert os.path.isfile(os.path.join(dated, name)), name
        assert not os.path.exists(os.path.join(day, name))
    nf1, nf2 = os.path.join(dated, "f1.png"), os.path.join(dated, "f2.png")
    assert E.get_ratings(db, [f1, nf1]) == {nf1: 5} and E.get_flags(db, [f1, nf1]) == {nf1: "keeper"} and E.get_tags(db, [f1, nf1]) == {nf1: ["family"]}, "the records followed the photo"
    assert E.get_folder_roll(db, E.folder_key(dated, is_file=False)) == {"film": "Portra 400"}, "the Roll Card of the folder they were in is the new folder's too"
    moved_aside = os.path.join(dated, "Retakes", "f2.png")
    assert os.path.isfile(moved_aside) and os.path.isfile(moved_aside + ".xmp") and norm(moved_aside) in E.hidden_keys(db) and E.get_ratings(db, [moved_aside]) == {moved_aside: 4}
    assert os.path.isfile(os.path.join(shoot, "Retakes", "old1.png")) and os.path.isfile(old1), "what was not part of the session stays where it was"
    assert norm(nf1) in {norm(r["path"]) for r in lt.all_rows()} and norm(f1) not in {norm(r["path"]) for r in lt.all_rows()}
    assert win._live_session == [] and win._live_aside == [] and not lt._finish_btn.isVisible()
    assert S.load()["live_session"] == [] and S.load()["live_aside"] == []
    assert live.running(); pump(0.8); assert len(got) == n_got, "the filed photos are not news in their new folder"
    assert "Filed" in win._coord_label.text() and today in win._coord_label.text()

    # nothing left: finishing again says so; and a photo that arrives after belongs to a new session
    win.finish_live_session(); assert "Nothing to file" in win._coord_label.text()
    arrive(lambda: frame(os.path.join(shoot, "next.png"), 40))
    assert lt._finish_btn.isVisible() and lt._finish_btn.text() == "Finish Session (1)"
    win.close()
    print("OK")
""")


def test_finishing_a_session_files_the_photos_and_a_retake_replaces_one():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=400, env={**os.environ, "PYTHONPATH": SRC, "PHOTOEDITOR_AUDIO": "off"})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1800:] + out.stderr[-3000:]
