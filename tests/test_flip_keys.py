"""Shift+[ flips the picture horizontally and Shift+] flips it vertically, on a keyboard where Shift+[ makes a "{" (the keys marked [ and ]) as well as one where it stays [; the plain keys still turn it."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp(); folder = os.path.join(work, "r"); os.makedirs(folder)
    import numpy as np, cv2
    from PyQt6.QtCore import Qt, QEvent
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    cv2.imwrite(os.path.join(folder, "a.png"), np.random.default_rng(0).integers(0, 255, (300, 400, 3), dtype=np.uint8))
    app = QApplication([])
    from photoeditor.desktop.keybinds import KeyMap
    km = KeyMap()
    def ev(key, mods):
        return QKeyEvent(QEvent.Type.KeyPress, key, mods)
    shift = Qt.KeyboardModifier.ShiftModifier
    assert km.action_for(ev(Qt.Key.Key_BraceLeft, shift)) == "flip_h", "Shift+[ that arrives as {"
    assert km.action_for(ev(Qt.Key.Key_BraceRight, shift)) == "flip_v"
    assert km.action_for(ev(Qt.Key.Key_BracketLeft, shift)) == "flip_h", "Shift+[ that arrives as ["
    assert km.action_for(ev(Qt.Key.Key_BracketRight, shift)) == "flip_v"
    assert km.action_for(ev(Qt.Key.Key_BracketLeft, Qt.KeyboardModifier.NoModifier)) == "rotate_left", "the plain keys still turn it"
    assert km.action_for(ev(Qt.Key.Key_BracketRight, Qt.KeyboardModifier.NoModifier)) == "rotate_right"
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1400, 900); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=os.path.join(folder, "a.png"))
    end = time.time() + 15
    while time.time() < end and c.state.image_rgb is None: app.processEvents(); time.sleep(0.01)
    assert not c.state.flip_h and not c.state.flip_v
    win.run_photo_action("flip_h"); assert c.state.flip_h and not c.state.flip_v
    win.run_photo_action("flip_v"); assert c.state.flip_h and c.state.flip_v
    win.run_photo_action("flip_h"); win.run_photo_action("flip_v"); assert not c.state.flip_h and not c.state.flip_v, "the same key again flips it back"
    QTest.keyClick(win, Qt.Key.Key_BraceLeft, shift); app.processEvents()
    assert c.state.flip_h, "the key itself, through the window"
    print("OK flips")
""")


def test_shift_brackets_flip_the_picture():
    r = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "OK flips" in r.stdout, r.stdout[-1500:] + r.stderr[-3000:]
