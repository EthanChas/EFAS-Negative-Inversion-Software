"""The tether window and its menu entry, driven with the practice camera: connecting, the live picture, the view controls, the lens drive and the sharpness meter, sampling the clear
film, the corner check, capturing into a roll folder, and opening a capture in the editor. A Canon camera without Canon's SDK must fail clearly and leave the window usable."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent, QShortcut
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    app = QApplication([])
    from photoeditor.desktop.view import tether_window as tw
    from photoeditor.features.tether import practice_camera as pc
    from photoeditor.features.tether.backend import TetherError

    roll = os.path.join(tempfile.mkdtemp(), "roll")
    def pump(seconds):
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents(); time.sleep(0.01)
    def until(check, seconds=15.0, what="the window"):
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            if check():
                return
            time.sleep(0.01)
        raise AssertionError("timed out waiting for " + what)
    def idle(w):
        until(lambda: not any(j is not None and j.isRunning() for j in (w._job, w._focus_job, w._exposure_job, w._auto_job)), what="the camera jobs")

    w = tw.TetherWindow(None, start_folder=roll)
    w.show()
    assert w._state == "off" and w.connect_button.text() == "Connect" and not w.capture_button.isEnabled()
    assert w.camera_combo.currentData() == "practice" and not w.sdk_widget.isVisible() and w.windowTitle() == "Canon Tether and Live View"
    assert w.next_label.text() == "next: scan_0001" and w.image._message.startswith("Connect a camera")

    # --- a Canon camera without Canon's SDK fails clearly and leaves the window usable
    w.camera_combo.setCurrentIndex(w.camera_combo.findData("canon"))
    assert w.sdk_widget.isVisible() and "Choose the folder" in w.sdk_status.text()
    w.connect_camera()
    assert w._state == "off" and "Choose the folder of Canon" in w.status.text()
    sdk = tempfile.mkdtemp()
    w.sdk_edit.setText(sdk)
    assert "not found" in w.sdk_status.text()
    w.connect_camera(); assert w._state == "off" and "Choose the folder of Canon" in w.status.text()
    open(os.path.join(sdk, "EDSDK.dll"), "wb").write(b"not a library")
    w._sdk_changed()   # the status follows the folder as it is typed; here the file appeared afterwards
    assert w.sdk_status.text().startswith("Found ")
    w.connect_camera()
    until(lambda: w._state == "off" and "could not be loaded" in w.status.text(), what="the failed load")
    assert w.session is None and w.connect_button.isEnabled() and "could not be loaded" in w.image._message
    w.camera_combo.setCurrentIndex(w.camera_combo.findData("practice"))
    assert not w.sdk_widget.isVisible()

    # --- the practice camera
    w.connect_camera()
    assert w._state == "connecting" and not w.connect_button.isEnabled()
    until(lambda: w._frame is not None, what="the first live picture")
    assert w._state == "live" and w.connect_button.text() == "Disconnect" and w.capture_button.isEnabled()
    assert "Practice camera" in w.camera_info.text() and "960 x 640" in w.image._info and w.image._image is not None
    session, camera = w.session, w.session.backend
    assert w.positive_check.isChecked() and session.view.positive and not session.view.peaking

    # --- the view controls reach the picture
    w.positive_check.setChecked(False); assert not session.view.positive
    w.peaking_check.setChecked(True); assert session.view.peaking
    w.peaking_slider.setValue(100); assert session.view.peaking_sensitivity == 1.0 and w.peaking_value.text() == "100%"
    w.peaking_slider.setValue(20); assert session.view.peaking_sensitivity == 0.2
    w.peaking_check.setChecked(False); w.positive_check.setChecked(True)
    # N held shows the other view, and letting go puts it back
    w.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_N, Qt.KeyboardModifier.NoModifier))
    assert not session.view.positive and not w.positive_check.isChecked()
    w.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_N, Qt.KeyboardModifier.NoModifier))   # (a repeat does not undo it)
    w.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_N, Qt.KeyboardModifier.NoModifier))
    assert session.view.positive and w.positive_check.isChecked()
    w.positive_check.setChecked(False)   # already a negative: N shows the positive for a moment
    w.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_N, Qt.KeyboardModifier.NoModifier)); assert session.view.positive
    w.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_N, Qt.KeyboardModifier.NoModifier)); assert not session.view.positive
    w.positive_check.setChecked(True)
    w.loupe_check.setChecked(True)
    w._image_hovered(0.5, 0.5)
    assert w.image._loupe is not None and w.image._loupe.width() == 384
    w._image_hovered(-1.0, -1.0); assert w.image._loupe is None
    w.loupe_check.setChecked(False)
    shortcuts = {sc.key().toString(): sc for sc in w.findChildren(QShortcut)}
    assert {"Space", "0", "I", "P", "L", "Left", "Right", "Shift+Left", "Shift+Right", "Alt+Left", "Alt+Right"} <= set(shortcuts), sorted(shortcuts)
    shortcuts["I"].activated.emit(); assert not w.positive_check.isChecked() and not session.view.positive
    shortcuts["I"].activated.emit(); assert w.positive_check.isChecked()
    shortcuts["P"].activated.emit(); assert session.view.peaking
    shortcuts["P"].activated.emit(); assert not session.view.peaking

    # --- the lens and the sharpness meter: out of focus to start, in focus at the sharpest spot
    start = camera.position
    w.reset_best(); pump(0.3)
    blurred = session.latest
    for _ in range(3):
        w.focus("far", "medium"); idle(w); pump(0.15)
    assert camera.position > start
    until(lambda: session.latest > 5 * max(blurred, 0.05), what="a sharper picture")
    assert session.best >= session.latest > 0 and "Sharpness" in w.sharp_label.text() and w.sharp_bar.value() > 50 and w.grade_label.text().split("  ")[0] in ("Sharpest", "Sharp", "Nearly there", "Soft", "Blurred")
    before = camera.position
    shortcuts["Right"].activated.emit(); idle(w)
    assert camera.position > before, "the Right key drives the lens farther"
    shortcuts["Left"].activated.emit(); idle(w); shortcuts["Shift+Left"].activated.emit(); idle(w); shortcuts["Alt+Left"].activated.emit(); idle(w)
    assert camera.position < before
    w.focus("far", "fine"); idle(w)
    # a click on the picture measures sharpness there; Centre goes back
    w._image_clicked(0.25, 0.4)
    assert session.view.region[:2] == (0.25, 0.4) and session.best == 0.0
    w.measure_centre(); assert session.view.region[:2] == (0.5, 0.5)

    # --- the zoom: the slider and the picture agree; the wheel's zoom keeps the point under the pointer; a drag moves the picture and a click still measures
    from PyQt6.QtCore import QPoint, QPointF
    from PyQt6.QtTest import QTest
    img = w.image
    assert img.zoom == 1.0 and w.zoom_slider.value() == 100 and w.zoom_label.text() == "100%" and img.width() >= 700, (img.width(), img.height())
    w.zoom_slider.setValue(400); assert img.zoom == 4.0 and w.zoom_label.text() == "400%"
    img.set_zoom(2.0); assert w.zoom_slider.value() == 200 and w.zoom_label.text() == "200%"
    w.zoom_slider.setValue(100); assert img.zoom == 1.0 and img._centre == (0.5, 0.5)
    t0 = img._target(); x_on_screen = t0.left() + 0.8 * t0.width()
    img.set_zoom(3.0, about=(0.8, 0.5)); t1 = img._target()
    assert abs((t1.left() + 0.8 * t1.width()) - x_on_screen) < 1.5, "the point under the pointer stays under it"
    assert img._target().width() > img.width() and img._centre[0] > 0.5
    before = img._centre
    QTest.mousePress(img, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(300, 200))
    QTest.mouseMove(img, QPoint(220, 200))
    QTest.mouseRelease(img, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(220, 200))
    assert img._centre[0] > before[0], "dragging the picture left shows more of its right"
    region = session.view.region
    assert session.view.region == region, "a drag does not measure"
    QTest.mouseClick(img, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(400, 250))
    assert session.view.region[:2] != region[:2], "a click measures where it lands"
    img.set_zoom(8.0); img.set_zoom(1.0); assert img._centre == (0.5, 0.5), "back to the whole picture"
    w.measure_centre(); w.zoom_slider.setValue(100)
    shortcuts["0"].activated.emit(); assert img.zoom == 1.0

    # --- the camera's own zoom: Fit / 5x / 10x ask the camera to show the middle of the sensor
    assert all(b.isEnabled() for b in w.camera_zoom_buttons.values()) and w.camera_zoom_buttons[1].isChecked()
    w.camera_zoom(5)
    until(lambda: camera._zoom == 5, what="the camera to zoom")
    assert w.camera_zoom_buttons[5].isChecked() and not w.camera_zoom_buttons[1].isChecked()
    until(lambda: not any(j.isRunning() for j in list(w._alive)), what="the zoom job")
    assert all(m.isEnabled() for m in w.camera_zoom_moves.values()), "zoomed: the arrows are on"
    w.camera_zoom_move(1, 0)
    until(lambda: camera._zoom_center[0] > 0.55, what="the camera to move its zoom frame")
    until(lambda: not any(j.isRunning() for j in list(w._alive)), what="the move")
    w.camera_zoom(1)
    until(lambda: camera._zoom == 1, what="the camera to show the whole picture again")
    assert not any(m.isEnabled() for m in w.camera_zoom_moves.values()), "whole picture: nothing to move"
    until(lambda: not any(j.isRunning() for j in list(w._alive)), what="the zoom job")
    # --- the camera's exposure: shown, set from the window, and found automatically
    until(lambda: w.exposure_combos["tv"].count() > 0, what="the exposure settings")
    assert "M mode" in w.mode_label.text() and w.exposure_combos["tv"].currentText() == "1/60 s" and w.exposure_combos["iso"].currentText() == "100" and w.exposure_combos["av"].currentText() == "f/8"
    assert w.exposure_combos["tv"].isEnabled() and not w.exposure_combos["comp"].isEnabled() and w.auto_button.isEnabled()
    combo = w.exposure_combos["tv"]
    combo.setCurrentIndex(combo.findText("1/30 s")); w.set_exposure_from_box("tv")
    until(lambda: camera.exposure().values["tv"] == 0x60, what="the shutter speed to reach the camera")
    until(lambda: not (w._exposure_job and w._exposure_job.isRunning()), what="the exposure job")
    camera.set_exposure("tv", 0x48)                      # 1/4 s: far too bright
    w.auto_button.click(); assert not w.auto_button.isEnabled() and w.exposure_note.text() == "Measuring..."
    until(lambda: w.auto_button.isEnabled(), 30.0, "auto exposure to finish")
    assert "Exposure is right" in w.exposure_note.text() or "As close as" in w.exposure_note.text(), w.exposure_note.text()
    until(lambda: w.exposure_combos["tv"].currentData() == camera.exposure().values["tv"], what="the box to show the new shutter speed")
    assert camera.exposure().values["tv"] != 0x48
    w.exposure_combos["tv"].setCurrentIndex(0); w.set_exposure_from_box("tv"); idle(w); pump(0.3)   # (a stand-in refusal is shown, not raised)
    session.set_exposure = lambda key, code: (_ for _ in ()).throw(TetherError("refused: test"))
    w.set_exposure_from_box("tv"); until(lambda: "refused: test" in w.exposure_note.text(), what="the refusal to be shown")
    del session.set_exposure
    # a slow reading still running when a setting is chosen must not be dropped mid-run (a QThread let go while it runs aborts the whole program)
    real_read = session.exposure
    session.exposure = lambda: (time.sleep(0.6), real_read())[1]
    w._exposure_timer.stop(); idle(w); w.refresh_exposure()
    first = w._exposure_job
    assert first is not None and first.isRunning()
    combo.setCurrentIndex(combo.findText("1/60 s")); w.set_exposure_from_box("tv")
    assert first in w._alive or not first.isRunning(), "the slow reading is kept until it finishes"
    until(lambda: not w._alive, 15.0, "the exposure jobs to finish")
    del session.exposure
    w._exposure_timer.start()
    camera.set_exposure("tv", 0x68); camera.set_exposure("iso", 0x48); pump(0.3)   # back to the picture the rest of this test was written for

    # --- sampling the clear film
    w.base_button.setChecked(True); w.arm_base_pick()
    assert "Click a patch" in w.status.text()
    w._image_clicked(0.03, 0.5)
    r, g, b = session.view.base_rgb
    assert r > g > b and not w.base_button.isChecked() and w.base_label.text().startswith("Film base: sampled"), (r, g, b)
    w.forget_base(); assert session.view.base_rgb is None and "worked out" in w.base_label.text()

    # --- the corner check
    camera._pos = pc.BEST; camera._frame = None
    until(lambda: w._frame is not None and session.latest > 1, what="the lens back in focus")
    w.check_corners()
    assert "centre" in w.corner_label.text() and "top left" in w.corner_label.text() and ("sharp as the middle" in w.corner_label.text())

    # --- capturing
    taken, opened = [], []
    w.captured.connect(taken.append); w.open_requested.connect(opened.append)
    w.prefix_edit.setText("roll_"); w.settle_spin.setValue(0.0)
    assert w.next_label.text() == "next: roll_0001"
    w.capture()
    assert w._state == "busy" and not w.capture_button.isEnabled() and not w.connect_button.isEnabled()
    until(lambda: w._state == "live" and taken, what="the capture")
    assert sorted(os.path.basename(p) for p in taken[0]) == ["roll_0001.JPG", "roll_0001.TIF"] and all(os.path.isfile(p) for p in taken[0])
    assert w.status.text().startswith("Saved roll_0001") and w.recent.count() == 2 and w.next_label.text() == "next: roll_0002"
    assert opened == [os.path.join(roll, "roll_0001.JPG")] and tw.primary_file(taken[0]) == opened[0]
    w.show_check.setChecked(False)
    w.capture(); until(lambda: w._state == "live" and len(taken) == 2, what="the second capture")
    assert sorted(os.path.basename(p) for p in taken[1]) == ["roll_0002.JPG", "roll_0002.TIF"] and len(opened) == 1, "nothing is opened when that box is off"
    w.recent.itemDoubleClicked.emit(w.recent.item(0))
    assert len(opened) == 2 and opened[1].lower().endswith((".tif", ".jpg"))
    assert tw.primary_file(["a.TIF", "b.CR3", "c.JPG"]) == "b.CR3" and tw.primary_file(["a.xyz", "b.JPG"]) == "b.JPG" and tw.primary_file(["a.xyz"]) == ""
    w.folder_edit.setText("")
    w.capture()
    assert w._state == "live" and "Choose a folder" in w.status.text() and len(taken) == 2
    w.folder_edit.setText(roll)

    # --- the settings are kept, and a second window starts from them
    w._save_settings()
    assert S.get("tether_prefix") == "roll_" and S.get("tether_folder") == roll and S.get("tether_camera") == "practice" and S.get("tether_show") is False

    # --- disconnecting, and a lost camera
    w.disconnect_camera()
    assert w._state == "closing"
    until(lambda: w._state == "off", what="the disconnect")
    assert w.session is None and w.image._image is None and not w.capture_button.isEnabled() and w.connect_button.text() == "Connect"
    w.connect_camera(); until(lambda: w._frame is not None, what="live again")
    w.session.backend.live_frame = lambda: (_ for _ in ()).throw(TetherError("The camera connection ended: test"))
    until(lambda: w._state == "off" and "connection ended" in w.status.text(), what="the lost camera")
    w.close()
    w2 = tw.TetherWindow(None)
    assert w2.folder_edit.text() == roll and w2.prefix_edit.text() == "roll_" and not w2.show_check.isChecked()
    w2.close()

    # --- in the main window: the menu entry, one window, and a capture opens in the editor
    from photoeditor.desktop.view import app_window as aw
    from PyQt6.QtWidgets import QMenu
    win = aw.AppWindow()
    menus = [o.title().replace("&", "") for o in win._tether_action.associatedObjects() if isinstance(o, QMenu)]
    assert menus == ["Extra"] and win._tether_action.text() == "Canon Tether and Live View...", menus
    win.show_tether()
    t = win._tether
    assert isinstance(t, tw.TetherWindow) and t.isVisible()
    win.show_tether(); assert win._tether is t
    t.folder_edit.setText(roll); t.settle_spin.setValue(0.0); t.show_check.setChecked(True); t.prefix_edit.setText("main_")
    t.connect_camera(); until(lambda: t._frame is not None, what="the live picture in the main window")
    t.capture()
    until(lambda: t._state == "live" and t.recent.count() == 2, what="the capture in the main window")
    want = os.path.join(roll, "main_0001.JPG")
    until(lambda: win.controller.state.image_path and os.path.normcase(win.controller.state.image_path) == os.path.normcase(want), 30.0, "the capture to open in the editor")
    win._on_tether_open(os.path.join(roll, "missing.jpg"))   # a file that is gone is ignored
    backend = t.session.backend
    assert backend._opened
    win.close()   # closing the main window gives the camera back first
    assert not backend._opened
    print("OK")
''')


def test_tether_window_with_the_practice_camera():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""), PHOTOEDITOR_GPU="off")
    done = subprocess.run([sys.executable, "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0 and "OK" in done.stdout, (done.stdout[-1500:], done.stderr[-3500:])
