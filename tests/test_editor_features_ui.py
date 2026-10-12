"""In the running editor: the history comes back after closing the app, a wrong auto-detection can be deleted on its own (and reset), the quick tag bar
and pre-made tags work, and the date boxes have a calendar."""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_COMMON = textwrap.dedent(r'''
    import os, sys, time, json, faulthandler
    faulthandler.enable()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    DATA = os.environ["PHOTOEDITOR_DATA_DIR"]
    PHOTO = os.path.join(DATA, "photos", "a.png")
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw

    def pump(cond=lambda: False, secs=20.0):
        end = time.time() + secs
        while time.time() < end:
            app.processEvents()
            if cond():
                return True
            time.sleep(0.01)
        return cond()

    def start():
        win = aw.AppWindow()
        win.resize(1400, 900)
        win.show()
        app.processEvents()
        win.open_folder(os.path.dirname(PHOTO), prefer=PHOTO)
        assert pump(lambda: win.controller.state.image_rgb is not None)
        pump(secs=0.5)
        return win, win.controller

    def descs(c):
        return [e.description for e in c.state.history]
''')

_HISTORY = _COMMON + textwrap.dedent(r'''
    PHASE = os.environ["PHASE"]
    LOG = os.path.join(DATA, "phase.json")
    win, c = start()
    s = c.state
    if PHASE == "1":
        rng = np.random.default_rng(1)
        assert len(s.history) >= 1
        c.set_exposure_ev(0.5)
        c.set_shadows_highlights(0.3, -0.2)
        c.rotate(1)
        c.set_crop_rect((10, 10, 150, 100))
        assert len(s.history) >= 5, descs(c)
        json.dump({"descs": descs(c), "exposure": s.exposure_ev}, open(LOG, "w"))
    elif PHASE == "2":
        saved = json.load(open(LOG))
        assert descs(c) == saved["descs"], (descs(c), saved["descs"])
        assert s.exposure_ev == saved["exposure"] and s.rotation_quarter_turns == 1 and s.crop_rect == (10, 10, 150, 100)
        assert c.can_undo() and not c.can_redo()
        panel = [win._history_panel._list.item(i).text() for i in range(win._history_panel._list.count())] if hasattr(win._history_panel, "_list") else None
        # undo walks back through the steps of the earlier session, one by one
        c.undo(); assert s.crop_rect is None
        c.undo(); assert s.rotation_quarter_turns == 0
        c.undo(); assert s.shadows == 0.0 and s.exposure_ev == 0.5
        c.undo(); assert s.exposure_ev == 0.0
        assert not c.can_undo() or len(s.history) >= 1
        c.redo(); assert s.exposure_ev == 0.5
        c.redo(); c.redo(); c.redo()
        assert s.crop_rect == (10, 10, 150, 100)
        # undo twice, then edit: the undone steps are gone for good and the new one is saved
        c.undo(); c.undo()
        c.set_exposure_ev(-0.4)
        json.dump({"descs": descs(c), "exposure": s.exposure_ev}, open(LOG, "w"))
    elif PHASE == "3":
        saved = json.load(open(LOG))
        assert descs(c) == saved["descs"], (descs(c), saved["descs"])
        assert s.exposure_ev == -0.4 and s.crop_rect is None
        assert not any("Cropped" in d for d in descs(c)), "the undone crop did not come back"
        # something outside the editor changes the saved edit (a paste from the Workbench): the history says so
        from photoeditor.features.persistence import edit_store
        st = edit_store.load_edit_state(c._db, PHOTO)
        st["exposure_ev"] = 1.25
        edit_store.save_edit_state(c._db, PHOTO, st)
        json.dump({"descs": descs(c)}, open(LOG, "w"))
    elif PHASE == "4":
        saved = json.load(open(LOG))
        assert descs(c) == saved["descs"] + ["Changed outside the editor"], descs(c)
        assert s.exposure_ev == 1.25
        # reopening again does not add it twice
        c.open_file(PHOTO); pump(secs=0.3)
        assert descs(c) == saved["descs"] + ["Changed outside the editor"], descs(c)
        # a different photo has its own history
        other = os.path.join(DATA, "photos", "b.png")
        c.open_file(other); pump(secs=0.3)
        assert descs(c)[0].startswith("Opened b.png"), descs(c)
        c.open_file(PHOTO); pump(secs=0.3)
        assert descs(c)[-1] == "Changed outside the editor" and len(descs(c)) == len(saved["descs"]) + 1
        # resetting is one more step, and it comes back too
        c.reset_edits()
        json.dump({"descs": descs(c)}, open(LOG, "w"))
    elif PHASE == "5":
        saved = json.load(open(LOG))
        assert descs(c) == saved["descs"] and descs(c)[-1] == "Reset all edits", descs(c)
        assert s.exposure_ev == 0.0
        c.undo()
        assert s.exposure_ev == 1.25, "undo goes back through the reset to the pasted look"
    print("HISTORY PHASE", PHASE, "OK"); sys.stdout.flush()
    os._exit(0)
''')

_FEATURES = _COMMON + textwrap.dedent(r'''
    from PyQt6.QtCore import Qt, QDate
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtWidgets import QApplication
    win, c = start()
    s = c.state

    # ---- delete one auto detection, leave the rest, reset brings it back
    c.open_file(os.path.join(DATA, "photos", "dust.png"))
    pump(secs=0.5)
    c.set_dust(True, 0.5, 4, 0.5)
    c.set_show_detections(True)
    def blobs():
        ov = s.overlay_rgba
        if ov is None:
            return []
        n, labels, stats, cent = cv2.connectedComponentsWithStats((ov[:, :, 3] > 0).astype(np.uint8), connectivity=8)
        return [tuple(cent[i]) for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= 4]
    assert pump(lambda: len(blobs()) == 3), blobs()
    ov_h, ov_w = s.overlay_rgba.shape[:2]
    ih, iw = s.image_rgb.shape[:2]
    first = blobs()[0]
    dx, dy = first[0] / ov_w * iw, first[1] / ov_h * ih
    deleted = []
    c.detections_deleted_changed.connect(deleted.append)
    c.delete_manual_repair_at(dx + 1, dy - 1)
    assert s.dust_excluded and len(s.dust_excluded) == 1 and deleted[-1] == 1
    assert pump(lambda: len(blobs()) == 2), "only that one is gone from the overlay: " + str(blobs())
    assert win._dust_tool._restore_btn.isEnabled() and win._dust_tool._restore_btn.text() == "Reset Deleted (1)"
    assert "Deleted an automatic detection" in c.state.history[-1].description
    # the others are still repaired: undo of the delete brings it back, and so does Reset
    c.undo()
    assert pump(lambda: len(blobs()) == 3) and not s.dust_excluded and win._dust_tool._restore_btn.text() == "Reset Deleted (0)"
    c.redo()
    assert pump(lambda: len(blobs()) == 2) and len(s.dust_excluded) == 1
    # a click on nothing deletes nothing
    notes = []
    c.notice.connect(notes.append)
    c.delete_manual_repair_at(2, 2)
    assert len(s.dust_excluded) == 1 and any("Nothing to delete" in n for n in notes)
    # saved with the photo
    c._save_edit_state()
    from photoeditor.features.persistence import edit_store
    assert len(edit_store.load_edit_state(c._db, os.path.join(DATA, "photos", "dust.png"))["dust_excluded"]) == 1
    win._dust_tool._restore_btn.click()
    assert not s.dust_excluded and pump(lambda: len(blobs()) == 3)
    assert win._dust_tool._restore_btn.text() == "Reset Deleted (0)" and not win._dust_tool._restore_btn.isEnabled()
    c.reset_deleted_detections()  # nothing to do, no error

    # ---- quick tag bar
    from photoeditor.desktop.view.quick_tag_dialog import QuickTagDialog
    from photoeditor.features.keybinds import logic as key_logic
    assert key_logic.DEFAULT_BINDINGS["quick_tag"] == "T"
    ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_T, Qt.KeyboardModifier.NoModifier, "t")
    assert win.keys().action_for(ev) == "quick_tag"
    c.open_file(PHOTO); pump(secs=0.3)
    c.set_tags_for([PHOTO], add=["People/Family", "Places/Paris"])
    c.set_tags_for([os.path.join(DATA, "photos", "b.png")], add=["People/Family"])
    usage = c.tag_usage()
    assert usage["People/Family"] == 2 and usage["People"] == 2 and usage["Places"] == 1
    dlg = QuickTagDialog(usage, 1)
    dlg._entry.setText("famly")
    assert dlg.results()[0] == "People/Family" and dlg.selected() == "People/Family", dlg.results()
    got = []
    dlg.chosen.connect(got.append)
    from PyQt6.QtTest import QTest
    QTest.keyClick(dlg._entry, Qt.Key.Key_Return)
    assert got == ["People/Family"], "Enter picked the top result"
    dlg2 = QuickTagDialog(usage, 3)
    dlg2._entry.setText("par")
    assert dlg2.results()[0] == "Places/Paris"
    dlg2._entry.setText("par"); QTest.keyClick(dlg2._entry, Qt.Key.Key_Down)
    dlg3 = QuickTagDialog(usage, 1)
    dlg3._entry.setText("zzqx brand new")
    assert dlg3.results() == ["zzqx brand new"] and "New tag" in dlg3._list.item(0).text()
    got3 = []; dlg3.chosen.connect(got3.append); QTest.keyClick(dlg3._entry, Qt.Key.Key_Return)
    assert got3 == ["zzqx brand new"], "nothing fits: what was typed becomes a new tag"
    dlg4 = QuickTagDialog(usage, 1)
    assert dlg4.results()[0] == "People/Family" or dlg4.results()[0] == "People", "with nothing typed the most used come first"
    # through the window: the hotkey's path adds the chosen tag to the open photo
    QuickTagDialog.exec = lambda self: (self._entry.setText("natur"), self._pick(self.selected()))
    win.quick_tag()
    assert "Places/Nature" in c.photo_tags(PHOTO), c.photo_tags(PHOTO)
    # and onto several photos selected in the Workbench
    win.set_view("lighttable"); pump(secs=0.3)
    win._lighttable.selected_paths = lambda: [PHOTO, os.path.join(DATA, "photos", "b.png")]
    QuickTagDialog.exec = lambda self: (self._entry.setText("night"), self._pick(self.selected()))
    win.quick_tag()
    assert "Subject/Night" in c.photo_tags(PHOTO) and "Subject/Night" in c.photo_tags(os.path.join(DATA, "photos", "b.png"))
    win.set_view("editor")

    # ---- pre-made tags drop-down in the Tags section
    editor = win._tags_panel.editor
    asked = []
    editor.add_requested.connect(asked.append)
    combo = editor._premade
    assert combo.count() > 20 and combo.itemText(0).startswith("Add a pre-made tag")
    idx = combo.findData("People/Portrait")
    assert idx > 0 and combo.itemText(idx) == "People › Portrait"
    combo.activated.emit(idx)
    assert asked == [["People/Portrait"]] and combo.currentIndex() == 0, "picking one adds it and the list goes back to its heading"
    combo.activated.emit(0)
    assert asked == [["People/Portrait"]], "the heading is not a tag"
    c.open_file(PHOTO); pump(secs=0.3)
    win._on_tags_changed([PHOTO])
    shown = [editor._list.item(i).text() for i in range(editor._list.count())]
    assert "People › Family" in shown, shown

    # ---- calendar buttons on the date boxes
    from photoeditor.desktop.view.roll_card_panel import RollCardTab
    tab = win.findChild(RollCardTab)
    assert tab is not None
    from PyQt6.QtWidgets import QToolButton
    buttons = [b for b in tab.findChildren(QToolButton) if hasattr(b, "calendar_menu")]
    assert len(buttons) == 3, len(buttons)
    for button, edit in zip(buttons, (tab._from, tab._to, tab._date)):
        edit.setText("2024-03-09")
        button.calendar_menu._sync()
        cal = button.calendar_menu.calendar
        assert (cal.selectedDate().year(), cal.selectedDate().month(), cal.selectedDate().day()) == (2024, 3, 9)
        button.calendar_menu._picked(QDate(2025, 12, 24))
        assert edit.text() == "2025-12-24"
    tab._date.setText("2024-03-09 14:30")
    buttons[2].calendar_menu._picked(QDate(2020, 1, 2))
    assert tab._date.text() == "2020-01-02 14:30"
    buttons[2].calendar_menu._clear()
    assert tab._date.text() == ""
    print("FEATURES OK"); sys.stdout.flush()
    os._exit(0)
''')


def _make_photos(data: str) -> None:
    import cv2
    import numpy as np

    folder = os.path.join(data, "photos")
    os.makedirs(folder, exist_ok=True)
    rng = np.random.default_rng(1)
    for name in ("a.png", "b.png"):
        img = cv2.GaussianBlur(rng.random((300, 400, 3)).astype(np.float32), (0, 0), 20)
        cv2.imwrite(os.path.join(folder, name), (60 + 140 * (img - img.min()) / np.ptp(img)).astype(np.uint8))
    rng = np.random.default_rng(5)
    base = cv2.GaussianBlur(rng.random((600, 900, 3)).astype(np.float32), (0, 0), 25)
    dust = (110 + 60 * (base - base.min()) / np.ptp(base)).astype(np.uint8)
    dust = np.clip(dust.astype(int) + rng.normal(0, 2, dust.shape), 0, 255).astype(np.uint8)
    for x, y in ((200, 150), (600, 400), (450, 520)):
        cv2.circle(dust, (x, y), 3, (30, 30, 30), -1)
    cv2.imwrite(os.path.join(folder, "dust.png"), dust)


def _run(script: str, data: str, ok: str, **extra) -> None:
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""), PHOTOEDITOR_DATA_DIR=data, **extra)
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", script], env=env, capture_output=True, text=True, timeout=600)
    assert ok in done.stdout, done.stdout[-1500:] + done.stderr[-4000:]


def test_the_history_comes_back_in_order_after_closing_the_app():
    data = tempfile.mkdtemp()
    _make_photos(data)
    for phase in "12345":
        _run(_HISTORY, data, f"HISTORY PHASE {phase} OK", PHASE=phase)


def test_delete_one_detection_quick_tags_premade_tags_and_calendars():
    data = tempfile.mkdtemp()
    _make_photos(data)
    _run(_FEATURES, data, "FEATURES OK")
