"""Crop Roll and Reset Crops: every photo of the roll at once, with a confirmation, leaving existing crops alone unless asked."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

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

    def scan(seed, border=True):
        rng = np.random.default_rng(seed)
        img = np.full((240, 360, 3), 25, np.uint8)
        pic = cv2.GaussianBlur(rng.random((160, 240, 3)).astype(np.float32), (0, 0), 4)
        pic = 90 + 110 * (pic - pic.min()) / np.ptp(pic)
        if border:
            img[40:200, 60:300] = pic.astype(np.uint8)
        else:
            img = cv2.resize(pic.astype(np.uint8), (360, 240))
        return img
    paths = []
    for i, border in enumerate([True, True, True, False]):
        p = os.path.join(folder, f"f{i}.png"); cv2.imwrite(p, scan(i, border)); paths.append(p)
    bad = os.path.join(folder, "f4.png"); open(bad, "wb").write(b"not an image"); paths.append(bad)

    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); c = win.controller
    win.open_folder(folder, prefer=paths[0])
    assert win._filmstrip.paths() == paths and win._filmstrip._crop_roll_btn.text() == "Crop Roll"
    shown = []
    QMessageBox.information = staticmethod(lambda *a, **k: shown.append(a[2]))
    QMessageBox.warning = staticmethod(lambda *a, **k: shown.append(a[2]))
    asked = []
    answer = {"go": False, "replace": False}
    win._ask_bulk_crop = lambda mode, n, cropped: (asked.append((mode, n, cropped)), (answer["go"], answer["replace"]))[1]
    from photoeditor.features.browse.processor import load_edited_thumbnail
    from photoeditor.desktop.paths import thumbnail_cache_dir
    ticks = []
    real_progress = win._filmstrip.set_bulk_progress
    win._filmstrip.set_bulk_progress = lambda d, t, text="": (ticks.append((d, t)), real_progress(d, t, text))
    def saved(p): return edit_store.load_edited if False else edit_store.load_edit_state(c._db, p)
    def finish():
        win._bulk_worker.wait(120000); app.processEvents()

    # photo f2 already has a hand-made crop (saved in the database)
    c.open_file(paths[2]); c.set_crop_rect((10, 10, 100, 100)); c._save_edit_state(); c.open_file(paths[0])

    # declining changes nothing
    win.bulk_crop("auto"); assert asked == [("auto", 5, 1)] and win._bulk_worker is None
    assert saved(paths[1]) is None or not saved(paths[1])["crop_rect"]

    # Crop Roll: the open photo (f0) through the editor, the others to the database; f2 keeps its crop; f3 has no border; f4 is broken
    answer["go"] = True
    refreshed = []
    real_refresh = win._refresh_photo_tiles
    win._refresh_photo_tiles = lambda p: (refreshed.append(p), real_refresh(p))
    win.bulk_crop("auto"); finish()
    assert paths[1] in refreshed and paths[2] not in refreshed and paths[4] not in refreshed, "each tile updates as its own photo is cropped"
    r1 = saved(paths[1])["crop_rect"]
    assert r1 is not None and abs(r1[0] - 60) < 12 and abs(r1[1] - 40) < 12 and abs(r1[2] - 300) < 12 and abs(r1[3] - 200) < 12, r1
    assert saved(paths[2])["crop_rect"] == (10, 10, 100, 100)
    assert saved(paths[3]) is None or not saved(paths[3])["crop_rect"]
    assert c.state.crop_rect is not None and c.can_undo(), "the open photo was cropped in the editor and can be undone"
    assert ticks and ticks[1][1] == 5 and max(d for d, _t in ticks) >= 3, ticks
    assert win._filmstrip._bulk_progress.isHidden(), "the progress bar goes away when it is done"
    assert "Cropped 2 photos" in shown[-1] and "already had a crop" in shown[-1] and "no clear border" in shown[-1], shown[-1]
    assert load_edited_thumbnail(thumbnail_cache_dir(), paths[1]) is not None, "the roll's tiles show the crop"
    msg = win._coord_label.text()
    assert "Cropped 2 photos" in msg and "1 already had a crop" in msg and "1 had no clear border" in msg and "1 failed" in msg, msg
    assert shown and "f4.png" in shown[-1]
    assert not win._bulk_worker and win._filmstrip._crop_roll_btn.text() == "Crop Roll"
    assert os.path.exists(paths[1] + ".xmp")

    # replacing existing crops, when asked
    answer["replace"] = True
    win.bulk_crop("auto"); finish()
    assert saved(paths[2])["crop_rect"] != (10, 10, 100, 100) and saved(paths[2])["crop_rect"] is not None

    # Reset Crops: asks with the number that have crops, removes only crops, keeps other edits
    c.open_file(paths[1]); c.set_exposure_ev(0.5); c._save_edit_state()
    st = saved(paths[2]); st["exposure_ev"] = 0.25; st["fine_rotation"] = 1.5; edit_store.save_edit_state(c._db, paths[2], st)
    asked.clear(); answer["go"] = False
    win.bulk_crop("reset"); assert asked and asked[0][0] == "reset" and asked[0][2] == 3 and saved(paths[2])["crop_rect"] is not None
    answer["go"] = True
    win.bulk_crop("reset"); finish()
    assert saved(paths[2])["crop_rect"] is None and saved(paths[2])["exposure_ev"] == 0.25 and saved(paths[2])["fine_rotation"] == 1.5
    assert c.state.crop_rect is None and c.state.exposure_ev == 0.5, "the open photo lost its crop but kept its exposure"
    assert "Reset the crop on 3 photos" in win._coord_label.text(), win._coord_label.text()
    assert "Removed the crop from 3 photos" in shown[-1] and load_edited_thumbnail(thumbnail_cache_dir(), paths[2]) is None

    # nothing to reset
    asked.clear(); shown.clear()
    win.bulk_crop("reset"); assert not asked and "None of the photos" in shown[-1]
    win.close()
    print("BULK CROP OK")
''')


def test_crop_roll_and_reset_crops():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert "BULK CROP OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3500:]
