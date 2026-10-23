"""File > Grade Sharpness end to end: the dialog grades a folder in the background and lists it, the grades are kept and marked on the filmstrip's tiles (and filterable), the overlay opens, and the
menu entry grades the folder in the filmstrip."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r"""
    import os, sys, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    import cv2, numpy as np
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    work = tempfile.mkdtemp(); folder = os.path.join(work, "roll"); os.makedirs(folder)

    def scene(seed):
        h, w = 800, 1200
        img = np.clip(np.linspace(0.3, 0.7, w)[None, :].repeat(h, 0) + np.random.default_rng(seed).normal(0, 0.015, (h, w)), 0, 1).astype(np.float32)
        cv2.rectangle(img, (400, 250), (700, 550), 0.15, -1); cv2.rectangle(img, (900, 100), (950, 700), 0.9, -1); cv2.circle(img, (250, 600), 90, 0.1, -1)
        return img
    paths = []
    for name, blur in (("a_sharp.png", 0), ("b_blurred.png", 14), ("c_sharp.png", 0)):
        img = scene(len(paths))
        if blur:
            img = cv2.GaussianBlur(img, (0, 0), blur)
        p = os.path.join(folder, name); cv2.imwrite(p, (np.repeat(img[..., None], 3, 2) * 255).astype(np.uint8)); paths.append(p)

    app = QApplication([])
    def until(check, seconds=40.0, what="the window"):
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            if check():
                return
            time.sleep(0.01)
        raise AssertionError("timed out waiting for " + what)
    def idle(dlg):
        until(lambda: dlg._worker is None or not dlg._worker.isRunning(), what="the grading")
        app.processEvents()

    from photoeditor.features.persistence import edit_store
    from photoeditor.desktop.view import sharpness_dialog as sd
    from photoeditor.desktop.view.thumbnail_delegate import GRADE_ROLE
    db = edit_store.connect(os.path.join(work, "edits.db"))
    told = []
    dlg = sd.SharpnessDialog(paths, db, None, current=paths[0], on_graded=lambda *a: told.append(a))
    dlg.show()
    assert dlg.headline.text() == "3 frames, none graded yet." and dlg.table.rowCount() == 3
    assert dlg.roll_button.isEnabled() and not dlg.stop_button.isEnabled() and dlg.open_button.isEnabled() and not dlg.preview_button.isEnabled()

    # --- Grade Entire Roll: in the background, one at a time, kept as it goes
    dlg.grade_roll()
    assert dlg._worker is not None
    until(lambda: len(dlg.grades()) == 3, what="three grades"); idle(dlg)
    words = [dlg.table.item(r, 1).text() for r in range(3)]
    assert words[0] == "Sharp" and words[2] == "Sharp" and words[1] in ("Soft", "Blurred"), words
    scores = [float(dlg.table.item(r, 2).text()) for r in range(3)]
    assert scores[1] < scores[0] - 30 and scores[1] < scores[2] - 30, scores
    assert len(told) == 3 and {t[0] for t in told} == set(paths)
    assert set(edit_store.get_sharpness_grades(db, paths)) == set(paths), "kept between sessions"
    assert "3 graded" in dlg.headline.text() and "blurred" in dlg.headline.text() + " soft" and dlg.status.text() == "Finished grading."
    assert dlg.roll_button.isEnabled() and not dlg.progress.isVisible()
    dlg.grade_roll(); assert dlg.status.text() == "Every frame is already graded."

    # --- the open frame again; the overlay of a selected one
    told.clear(); dlg.grade_open_frame(); idle(dlg)
    assert [t[0] for t in told] == [paths[0]], told
    dlg.table.selectRow(1); app.processEvents(); assert dlg.preview_button.isEnabled()
    ov = sd.SharpnessOverlayDialog(paths[1])
    assert not ov.view.pixmap().isNull() and "b_blurred.png" in ov.windowTitle()
    tinted = ov.view.pixmap().toImage()
    ov.toggle.setChecked(True); assert ov.toggle.text() == "Show Overlay" and ov.view.pixmap().toImage() != tinted
    ov.toggle.setChecked(False); assert ov.toggle.text() == "Show Original"

    # --- the filmstrip marks the tiles, and can show only the soft ones
    from photoeditor.desktop.view.filmstrip import Filmstrip
    fs = Filmstrip()
    fs.load_folder(paths, grades=edit_store.get_sharpness_grades(db, paths))
    until(lambda: fs._list.count() == 3, what="the tiles")
    assert fs._find_item(paths[1]).data(GRADE_ROLE)[0] in ("warning", "critical") and fs._find_item(paths[0]).data(GRADE_ROLE)[0] == "good"
    fs.set_filter("soft")
    visible = [fs._list.item(i).data(0x100) for i in range(fs._list.count()) if not fs._list.item(i).isHidden()]
    assert visible == [paths[1]], visible
    fs.set_grade(paths[1], ""); assert fs._find_item(paths[1]).data(GRADE_ROLE) is None
    fs.set_grade(paths[1], "critical", 12.0); assert fs._find_item(paths[1]).data(GRADE_ROLE) == ("critical", 12.0)
    fs.set_filter("all")
    fs.show(); fs.grab()            # the chips draw

    # --- Grade All Again throws the grades away, tells the filmstrip, and grades afresh
    told.clear(); dlg.grade_roll(everything=True)
    assert any(t[1] == "" for t in told), "each tile is told to take its mark off"
    until(lambda: len(dlg.grades()) == 3, what="graded again"); idle(dlg)

    # --- closing while it grades stops the thread rather than dropping it
    dlg.grade_roll(everything=True)
    dlg.close(); assert dlg._worker is None or not dlg._worker.isRunning()

    # --- the menu entry grades the folder in the filmstrip, and the filmstrip loads kept grades
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); win.show(); app.processEvents()
    assert win._grade_sharpness_action.text() == "Grade Sharpness..."
    opened = []
    aw.SharpnessDialog.exec = lambda self: opened.append(self)
    win.open_folder(folder, prefer=paths[0])
    until(lambda: win._filmstrip._list.count() == 3, what="the window's filmstrip")
    win._on_grade_sharpness()
    assert opened and opened[0]._paths == win._filmstrip.paths() and opened[0]._current == paths[0]
    edit_store.set_sharpness_grade(win.controller._db, paths[2], "warning", 55.0)
    win._on_library_folder_selected(folder)
    until(lambda: win._filmstrip._list.count() == 3, what="the tiles again")
    assert win._filmstrip._find_item(paths[2]).data(GRADE_ROLE) == ("warning", 55.0), "a kept grade shows when the folder is loaded"
    print("OK")
""")


def test_grading_a_roll_marking_the_filmstrip_and_the_menu_entry():
    done = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0 and "OK" in done.stdout, (done.stdout[-1500:], done.stderr[-3500:])
