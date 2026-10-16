"""The Workbench's Live Folder: turn it on (it asks for the folder the first time), and each photo that lands in the folder - or a day folder inside it - is read in, selected in the
Workbench and, if asked, opened in the editor; turn it off and nothing more arrives."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from photoeditor.features.settings import logic as S

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_the_settings_for_the_live_folder_are_kept_and_checked(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    assert S.load()["live_folder"] == "" and S.load()["live_open_editor"] is True
    S.save({"live_folder": "  D:/Scans/Live  ", "live_open_editor": False})
    assert S.load()["live_folder"] == "D:/Scans/Live" and S.load()["live_open_editor"] is False
    S.save({"live_folder": 5, "live_open_editor": "yes"})
    assert S.load()["live_folder"] == "" and S.load()["live_open_editor"] is True, "a wrong-typed value falls back to the default"


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp()
    shoot = os.path.join(work, "shoot"); other = os.path.join(work, "other")
    os.makedirs(shoot); os.makedirs(other)
    import numpy as np, cv2
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False, "advanced_mode": False})
    def frame(path, seed):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cv2.imwrite(path, np.random.default_rng(seed).integers(30, 220, (60, 90, 3), dtype=np.uint8))
    frame(os.path.join(shoot, "old1.png"), 1); frame(os.path.join(shoot, "old2.png"), 2); frame(os.path.join(other, "elsewhere.png"), 3)
    from PyQt6.QtWidgets import QApplication, QFileDialog
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.features.library import query as Q
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
    lt = win._lighttable; live = win._live
    live._interval = 60
    got = []; live.arrived.connect(got.append)
    win.set_view("lighttable"); pump(0.5)
    assert until(lambda: win._index_worker is None)

    # asked for the folder and said no: it stays off
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
    lt._live_btn.click(); pump(0.2)
    assert not live.running() and not lt.live_checked() and not win._live_action.isChecked()

    # asked and chosen: it is on, remembered, and the folder's photos are read into the Workbench
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: shoot)
    lt._live_btn.click(); pump(0.3)
    assert live.running() and live.folder() == shoot and lt.live_checked() and win._live_action.isChecked()
    assert S.load()["live_folder"] == shoot and shoot in lt._live_btn.toolTip()
    assert until(lambda: win._index_worker is None and lt.row_count() >= 3), lt.row_count()
    base = lt.row_count()

    # a photo lands in a day folder (as EOS Utility makes them): it is selected in the Workbench and the editor is left alone
    lt._live_editor_action.setChecked(False); assert S.load()["live_open_editor"] is False
    new1 = os.path.join(shoot, "2026_10_16", "new1.png")
    frame(new1, 11)
    assert until(lambda: got), "the photo arrived"
    assert got[-1] == [new1]
    assert lt.row_count() == base + 1 and [Q.norm(p) for p in lt.selected_paths()] == [Q.norm(new1)], lt.selected_paths()
    assert win.lighttable_active() and "new1.png arrived" in win._coord_label.text()

    # with "show in the editor" on, the next one opens large, and the filmstrip has it
    lt._live_editor_action.setChecked(True); assert S.load()["live_open_editor"] is True
    new2 = os.path.join(shoot, "new2.png")
    n = len(got); frame(new2, 12)
    assert until(lambda: len(got) > n) and got[-1] == [new2]
    assert until(lambda: not win.lighttable_active() and Q.norm(win.controller.state.image_path or "") == Q.norm(new2)), (win.lighttable_active(), win.controller.state.image_path)
    assert Q.norm(new2) in [Q.norm(p) for p in win._filmstrip.paths()], "the strip lists the new frame"

    # a search that hides the new photo does not break it, and says so
    win.set_view("lighttable"); pump(0.5)
    lt._live_editor_action.setChecked(False)
    lt._search.setText("old1"); lt.apply_filters()
    new3 = os.path.join(shoot, "new3.png")
    n = len(got); frame(new3, 13)
    assert until(lambda: len(got) > n)
    assert "hiding it" in win._coord_label.text() and win.lighttable_active(), win._coord_label.text()
    lt.clear_filters(); lt._search.setText(""); lt.apply_filters()

    # off from the File menu: nothing more arrives; on again from the menu uses the remembered folder (no question)
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked again")))
    win._live_action.setChecked(False); pump(0.2)
    assert not live.running() and not lt.live_checked()
    n = len(got); frame(os.path.join(shoot, "new4.png"), 14); pump(0.6)
    assert len(got) == n, "off: nothing arrives"
    win._live_action.setChecked(True); pump(0.3)
    assert live.running() and live.folder() == shoot and lt.live_checked()
    n = len(got); frame(os.path.join(shoot, "new5.png"), 15)
    assert until(lambda: len(got) > n) and got[-1] == [os.path.join(shoot, "new5.png")], "new4 was there when it was turned on, so it is not news"
    win.close()
    print("OK")
""")


def test_the_live_folder_shows_each_photo_as_it_arrives():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC, "PHOTOEDITOR_AUDIO": "off"})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-2500:]
