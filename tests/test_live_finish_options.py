"""The flame button's two settings for Finish Session, in the window: where the dated folders go (chosen once, kept) and "Clear the Hotstack Folder When Finished" (the older photos lying
loose in the hotstack folder are put away too). And keys pressed while a photo is opening are held and applied to the new photo instead of the one going out."""
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
    shoot = os.path.join(work, "shoot"); archive = os.path.join(work, "archive")
    os.makedirs(os.path.join(shoot, "keep")); os.makedirs(archive)
    import numpy as np, cv2
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False, "advanced_mode": False})
    def frame(path, seed, when=None):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cv2.imwrite(path, np.random.default_rng(seed).integers(30, 220, (60, 90, 3), dtype=np.uint8))
        if when is not None: os.utime(path, (when, when))
        return path
    def stamp(y, m, d, h=12): return datetime(y, m, d, h).timestamp()
    from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.features.library import query as Q
    win = aw.AppWindow(); win.show()
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
    pump(0.5)
    lt = win._lighttable; live = win._live
    live._interval = 3600
    asked = []; warned = []
    QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[2]), QMessageBox.StandardButton.Yes)[1])
    QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a[2]))
    win.set_view("lighttable"); pump(0.3)
    win._on_hotstack_requested(shoot, True); pump(0.3)
    assert live.folders() == [shoot]

    # the flame button's menu has both settings, off / not chosen at the start
    texts = [a.text() for a in lt._hot_btn.menu().actions()]
    assert "Date Folder Location..." in texts and "Clear the Hotstack Folder When Finished" in texts and "Use the Hotstack Folder for Dated Folders" in texts, texts
    assert lt.date_folder() == "" and not lt.clear_folder() and not lt._date_folder_reset_action.isEnabled()
    assert S.load()["live_date_folder"] == "" and S.load()["live_clear_folder"] is False

    # choose the folder the dated folders go into: it is remembered, and the menu names it
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: archive)
    lt._date_folder_action.trigger(); pump(0.1)
    assert os.path.normcase(S.load()["live_date_folder"]) == os.path.normcase(os.path.normpath(archive)), S.load()["live_date_folder"]
    assert lt._date_folder_action.text() == "Date Folder Location: archive..." and lt._date_folder_reset_action.isEnabled()
    assert "not in your Library" in win._coord_label.text(), win._coord_label.text()

    # turn the clearing on: kept too
    lt._clear_folder_action.trigger(); pump(0.1)
    assert lt.clear_folder() and S.load()["live_clear_folder"] is True

    # a session of two photos, some older photos lying loose in the hotstack folder, one that is still arriving, and one in a folder inside it
    s1 = frame(os.path.join(shoot, "s1.png"), 1, stamp(2026, 10, 16)); s2 = frame(os.path.join(shoot, "s2.png"), 2, stamp(2026, 10, 17))
    old1 = frame(os.path.join(shoot, "old1.png"), 3, stamp(2026, 9, 3)); old2 = frame(os.path.join(shoot, "old2.png"), 4, stamp(2026, 9, 4))
    arriving = frame(os.path.join(shoot, "arriving.png"), 5, time.time())
    inner = frame(os.path.join(shoot, "keep", "loose.png"), 6, stamp(2026, 9, 3))
    live.ignore([s1, s2, old1, old2, arriving, inner])
    win._live_session = [s1, s2]; win._refresh_hotstack_ui()
    lt.select_path(s1); pump(0.3)
    win.finish_live_session(); pump(1.0)
    assert asked and "inside" in asked[-1] and archive in asked[-1] and "2 older photos" in asked[-1] and "still arriving" in asked[-1], asked[-1]
    for name, day in (("s1.png", "16-10-2026"), ("s2.png", "17-10-2026"), ("old1.png", "03-09-2026"), ("old2.png", "04-09-2026")):
        assert os.path.isfile(os.path.join(archive, day, name)), (name, os.listdir(archive))
        assert not os.path.exists(os.path.join(shoot, name)), name
    assert os.path.isfile(arriving) and os.path.isfile(inner), "the one still arriving and the one in a folder inside it stay"
    assert win._live_session == [] and "2 of them were older photos" in win._coord_label.text(), win._coord_label.text()

    # the clearing off: only the session is filed; and the dated folders go back inside the hotstack folder
    lt._clear_folder_action.trigger(); pump(0.1)
    assert not lt.clear_folder() and S.load()["live_clear_folder"] is False
    lt._date_folder_reset_action.trigger(); pump(0.1)
    assert S.load()["live_date_folder"] == "" and lt.date_folder() == "" and not lt._date_folder_reset_action.isEnabled()
    t1 = frame(os.path.join(shoot, "t1.png"), 7, stamp(2026, 10, 18)); old3 = frame(os.path.join(shoot, "old3.png"), 8, stamp(2026, 9, 5))
    live.ignore([t1, old3])
    win._live_session = [t1]; win._refresh_hotstack_ui()
    win.finish_live_session(); pump(0.8)
    assert os.path.isfile(os.path.join(shoot, "18-10-2026", "t1.png")) and os.path.isfile(old3), "no clearing: the older photo stays"
    assert "older photo" not in asked[-1] and "inside" not in asked[-1], asked[-1]

    # clearing on, nothing in the session: the older photos are still put away (from the menu command)
    lt._clear_folder_action.trigger(); pump(0.1)
    win._live_session = []
    win.finish_live_session(); pump(0.8)
    assert os.path.isfile(os.path.join(shoot, "05-09-2026", "old3.png")) and not os.path.exists(old3)
    assert "older photo" in asked[-1] and "from this live session" not in asked[-1], asked[-1]

    # a folder chosen for the dated folders that is not there any more (its drive is gone): nothing moves, and the person is told
    gone = os.path.join(work, "no-such-drive", "inner", "dates")
    S.save({"live_date_folder": gone}); lt.set_date_folder(S.load()["live_date_folder"])
    t2 = frame(os.path.join(shoot, "t2.png"), 9, stamp(2026, 10, 19)); live.ignore([t2])
    win._live_session = [t2]; n = len(asked)
    win.finish_live_session(); pump(0.3)
    assert warned and "not there" in warned[-1] and os.path.isfile(t2) and len(asked) == n, warned
    win.close()
    print("OK")
""")


def test_the_flame_menu_sets_where_dated_folders_go_and_clears_the_hotstack_folder():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=400, env={**os.environ, "PYTHONPATH": SRC, "PHOTOEDITOR_AUDIO": "off"})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1800:] + out.stderr[-3000:]


_KEYS_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False, "advanced_mode": False})
    paths = []
    for i in range(3):
        p = os.path.join(work, f"p{i}.png"); cv2.imwrite(p, np.random.default_rng(i).integers(30, 220, (60, 90, 3), dtype=np.uint8)); paths.append(p)
    from PyQt6.QtCore import Qt, QCoreApplication
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.show(); win.open_folder(work)
    c = win.controller
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
    pump(0.5)
    win.set_view("editor"); win.activateWindow(); pump(0.3)
    p0, p1, p2 = paths
    c.open_file(p0); pump(0.3)
    assert c.state.rotation_quarter_turns == 0 and not c.opening
    def press(key, text):
        QCoreApplication.postEvent(win.focusWidget() or win, QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text))

    # the key is already waiting when the next photo starts to open: it must turn the NEW photo, not the one going out
    posted = []
    def press_once():
        if not posted:
            posted.append(1); press(Qt.Key.Key_BracketRight, "]")
    c.loading_started.connect(press_once)
    c.open_file(p1)
    c.loading_started.disconnect(press_once)
    assert until(lambda: c.state.rotation_quarter_turns == 1, 5), "the new photo was turned"
    assert os.path.normcase(c.state.image_path) == os.path.normcase(p1)
    c.open_file(p0); pump(0.5)
    assert c.state.rotation_quarter_turns == 0, "the photo that went out was not turned"

    # several keys, in the order pressed: rotate then step to the next photo. The step must happen after the turn, and the turn must be of this photo
    posted.clear()
    def press_two():
        if not posted:
            posted.append(1); press(Qt.Key.Key_BracketLeft, "["); press(Qt.Key.Key_BracketLeft, "[")
    c.loading_started.connect(press_two)
    c.open_file(p2)
    c.loading_started.disconnect(press_two)
    assert until(lambda: c.state.rotation_quarter_turns == 2, 5), c.state.rotation_quarter_turns
    c.open_file(p0); pump(0.3)
    assert c.state.rotation_quarter_turns == 0

    # a plain press, with no photo opening, is applied at once
    assert not c.opening
    press(Qt.Key.Key_BracketRight, "]"); assert until(lambda: c.state.rotation_quarter_turns == 1, 5)
    # nothing held is left over
    assert win._hotkey_filter._held == []
    win.close()
    print("OK")
""")


def test_keys_pressed_while_a_photo_opens_are_held_and_applied_to_the_new_photo():
    out = subprocess.run([sys.executable, "-c", _KEYS_SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC, "PHOTOEDITOR_AUDIO": "off"})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1800:] + out.stderr[-3000:]
