"""The Slideshow: its rules, the stage, and the page - photos from the Workbench or the open folder, made with their edits, played, stepped and shown full screen."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from photoeditor.features.settings import logic as settings
from photoeditor.features.slideshow import logic as show

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_the_order_is_as_it_is_or_shuffled_with_the_first_kept():
    assert show.order(5, False) == [0, 1, 2, 3, 4]
    shuffled = show.order(20, True, seed=1)
    assert sorted(shuffled) == list(range(20)) and shuffled != list(range(20)) and shuffled == show.order(20, True, seed=1)
    kept = show.order(20, True, seed=3, first=7)
    assert kept[0] == 7 and sorted(kept) == list(range(20))
    assert show.order(1, True) == [0] and show.order(0, True) == []


def test_stepping_stops_at_the_ends_or_wraps():
    assert show.step(2, 5, 1, False) == 3 and show.step(2, 5, -1, False) == 1
    assert show.step(4, 5, 1, False) is None and show.step(0, 5, -1, False) is None
    assert show.step(4, 5, 1, True) == 0 and show.step(0, 5, -1, True) == 4
    assert show.step(0, 0, 1, True) is None


def test_the_size_a_slide_is_made_at_follows_the_screen():
    assert show.render_size(800, 600) == 1280 and show.render_size(1920, 1080) == 1920
    assert show.render_size(1920, 1080, 1.5) == 3840
    assert show.render_size(1200, 800, 2.0) == 2560 and show.render_size(9000, 9000, 3.0) == 3840


def test_the_caption_is_the_name_and_what_is_known_about_the_photo():
    assert show.caption("C:/x/IMG_0042.CR2") == "IMG_0042"
    assert show.caption("IMG_0042.CR2", {"film": "Portra 400", "roll": "Tokyo", "day": "2026-10-05"}) == "IMG_0042  \u00b7  Portra 400  \u00b7  Tokyo  \u00b7  2026-10-05"
    assert show.caption("a.png", {"film": "", "roll": None}) == "a"
    assert show.clean_interval("abc") == show.INTERVAL_DEFAULT and show.clean_interval(0) == 1.0 and show.clean_interval(900) == 120.0


def test_the_settings_are_kept_and_a_damaged_file_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    settings.save({"slideshow_interval": 8.5, "slideshow_transition": "cut", "slideshow_source": "folder", "slideshow_shuffle": True, "slideshow_loop": False})
    got = settings.load()
    assert got["slideshow_interval"] == 8.5 and got["slideshow_transition"] == "cut" and got["slideshow_source"] == "folder" and got["slideshow_shuffle"] is True
    assert got["slideshow_loop"] is False and got["slideshow_captions"] is True and got["slideshow_edits"] is True
    cleaned = settings._clean({"slideshow_interval": 9999, "slideshow_transition": "spin", "slideshow_source": "nowhere", "slideshow_shuffle": "yes"})
    assert cleaned["slideshow_interval"] == 120.0 and cleaned["slideshow_transition"] == "fade" and cleaned["slideshow_source"] == "shown" and cleaned["slideshow_shuffle"] is False


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False, "advanced_mode": False})
    from PyQt6.QtWidgets import QApplication, QLabel
    from PyQt6.QtCore import Qt, QEvent
    from PyQt6.QtGui import QKeyEvent
    paths = []
    for i, colour in enumerate(((30, 60, 200), (200, 60, 30), (40, 190, 60), (220, 200, 40))):
        img = np.zeros((300, 450, 3), np.uint8); img[:] = colour
        img[100:200, 150:300] = (255 - colour[0], 255 - colour[1], 255 - colour[2])
        p = os.path.join(work, f"s{i}.png"); cv2.imwrite(p, img[..., ::-1]); paths.append(p)
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.show(); win.open_folder(work, prefer=paths[0]); c = win.controller
    def pump(s):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    def key(widget, k):
        for t in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            app.sendEvent(widget, QKeyEvent(t, k, Qt.KeyboardModifier.NoModifier))
    def wait_for(cond, seconds=15):
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            if cond(): return True
            time.sleep(0.02)
        return False
    pump(2)
    view = win._slideshow
    assert list(win._view_buttons) == ["slideshow", "maps", "classroom", "lighttable", "editor"]

    # every transport button has its icon (a file from assets/icon), and the play button swaps between play and pause
    for button in (view._previous_btn, view._play_btn, view._next_btn, view._full_btn):
        assert not button.icon().isNull() and not button.icon().pixmap(16, 16).isNull(), button.toolTip()
    play_icon = view._play_btn.icon().pixmap(16, 16).toImage()

    # opening the page from the editor reads the library, shows the photo that was open first, and waits for Play
    win._view_buttons["slideshow"].click()
    assert win.view_name() == "slideshow" and win.slideshow_active() and win._view_buttons["slideshow"].isChecked()
    assert wait_for(lambda: view.item_count() == 4), view.item_count()
    assert wait_for(lambda: view._stage.image() is not None), "the first slide is made"
    assert not view.is_playing() and view.current_path() == paths[0] and view._counter_text() == "1 / 4"
    first = view._stage.image()
    assert first.width() > 100 and first.height() > 100

    # stepping with the keys and the buttons; the next slides were made ahead
    key(view._stage, Qt.Key.Key_Right)
    assert wait_for(lambda: view.position() == 1 and view._stage.image() is not first)
    assert view.current_path() == paths[1] and view._counter_text() == "2 / 4"
    key(view._stage, Qt.Key.Key_End); assert wait_for(lambda: view.position() == 3)
    key(view._stage, Qt.Key.Key_Home); assert wait_for(lambda: view.position() == 0)
    view._next_btn.click(); view._previous_btn.click(); assert view.position() == 0

    # the keys do not reach the editor: its roll stayed where it was, and nothing was rated
    assert c.state.image_path == paths[0]

    # play: it moves on by itself, with a crossfade, and stops at the end when not looping
    view._seconds.setValue(1.0); view._loop.setChecked(False)
    view._seconds.setMinimum(0.2); view._seconds.setValue(0.3)
    key(view._stage, Qt.Key.Key_Space)
    assert view.is_playing() and wait_for(lambda: view.position() >= 1, 20), view.position()
    assert view._play_btn.icon().pixmap(16, 16).toImage() != play_icon, "it shows pause while playing"
    assert wait_for(lambda: view.position() == 3 and not view.is_playing(), 30), (view.position(), view.is_playing())
    assert view._stage._message == "End of the slideshow"
    # play again from the end starts at the top; pause keeps the place
    key(view._stage, Qt.Key.Key_Space)
    assert wait_for(lambda: view.is_playing() and view.position() == 0)
    key(view._stage, Qt.Key.Key_Space)
    assert not view.is_playing()
    stay = view.position(); pump(1.0); assert view.position() == stay, "paused means paused"

    # looping wraps round
    view._loop.setChecked(True); view.go_to(3); assert wait_for(lambda: view.position() == 3)
    assert view.step(1) and wait_for(lambda: view.position() == 0)

    # shuffle keeps the photo on screen and shows all of them once
    view.go_to(2); assert wait_for(lambda: view.position() == 2); here = view.current_path()
    view._shuffle.setChecked(True); pump(0.3)
    assert view.current_path() == here and sorted(view._order) == [0, 1, 2, 3]
    view._shuffle.setChecked(False); pump(0.3)
    assert view.current_path() == here and view._order == [0, 1, 2, 3]

    # captions on and off (C), edits on and off
    assert view._stage._caption == "s2" or view._stage._caption.startswith("s2")
    key(view._stage, Qt.Key.Key_C); assert not view._captions.isChecked() and view._stage._caption == ""
    key(view._stage, Qt.Key.Key_C); assert view._captions.isChecked() and view._stage._caption != ""
    before = view._stage.image()
    view._edits.setChecked(False)
    assert wait_for(lambda: view._stage.image() is not before), "showing the scan as it is makes it again"
    view._edits.setChecked(True)

    # full screen: the stage moves into a window of its own, Esc brings it back
    holder = view._stage.parentWidget()
    key(view._stage, Qt.Key.Key_F)
    assert view.is_fullscreen() and view._stage.window() is not win and view._stage._hide_cursor
    key(view._stage, Qt.Key.Key_Right); assert wait_for(lambda: view.position() == 3)
    key(view._stage, Qt.Key.Key_Escape)
    assert not view.is_fullscreen() and view._stage.window() is win and view._stage.parentWidget() is holder

    # the other sources: the Workbench's selection, and the open folder
    view._source.setCurrentIndex(view._source.findData("selected")); pump(0.5)
    assert view.item_count() == 0 and "Select photos" in view._stage._message
    view._source.setCurrentIndex(view._source.findData("folder")); pump(0.5)
    assert view.item_count() == 4
    view._source.setCurrentIndex(view._source.findData("shown")); pump(0.5)
    assert S.load()["slideshow_source"] == "shown" and S.load()["slideshow_shuffle"] is False

    # a photo that cannot be read is said so and skipped over
    os.remove(paths[1])
    view._cache.clear(); view._failed.clear(); view.reload_items(); view.go_to(1)
    assert wait_for(lambda: "Could not open" in view._stage._message), view._stage._message
    view.go_to(2); assert wait_for(lambda: view._stage._message == "" and view.position() == 2)

    # leaving the page stops it; the app's own keys still work in the editor afterwards
    view.play(); win._view_buttons["editor"].click(); pump(0.3)
    assert not view.is_playing() and win.view_name() == "editor"
    win.close()
    print("OK")
""")


def test_the_slideshow_page_plays_steps_and_goes_full_screen():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=600, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-3000:]


def test_the_stage_fades_between_slides_and_keeps_the_last_one():
    from PyQt6.QtGui import QImage
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from photoeditor.desktop.view.slideshow_view import SlideshowStage

    stage = SlideshowStage()
    stage.resize(400, 300)
    red, blue = QImage(40, 30, QImage.Format.Format_RGB888), QImage(40, 30, QImage.Format.Format_RGB888)
    red.fill(0xFF0000)
    blue.fill(0x0000FF)
    stage.show_slide(red, "red", "1 / 2", 0)
    assert stage.image() is red and not stage.fading()
    stage.show_slide(blue, "blue", "2 / 2", 500)
    assert stage.image() is blue and stage.fading() and stage._previous is red
    frame = stage.grab().toImage()
    assert frame.width() == 400
    stage.clear()
    assert stage.image() is None and not stage.fading()
    del app


def test_the_slide_worker_makes_the_picture_with_its_edits(tmp_path, monkeypatch):
    import cv2
    import numpy as np

    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    from photoeditor.desktop.export_worker import render_slide
    from photoeditor.features.persistence import edit_store

    path = str(tmp_path / "a.png")
    img = np.zeros((600, 900, 3), np.uint8)
    img[:] = (90, 120, 150)
    cv2.imwrite(path, img[..., ::-1])
    conn = edit_store.connect(str(tmp_path / "edits.db"))
    plain = render_slide(path, conn, 400, edited=False)
    assert plain.dtype == np.uint8 and max(plain.shape[:2]) == 400 and abs(int(plain[100, 100, 0]) - 90) <= 2, "the scan as it is"
    small = render_slide(path, conn, 300, edited=True)
    assert max(small.shape[:2]) == 300 and small.dtype == np.uint8
    big = render_slide(path, conn, 1280, edited=True)
    assert max(big.shape[:2]) == 900, "never made bigger than the scan itself"
    conn.close()
    pytest.importorskip("PyQt6")
