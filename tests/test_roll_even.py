"""Evening out a roll: differing frames with a sure border are converted against their own film base; nothing else is touched, and it can be undone."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import cv2
import numpy as np
import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_rebate as T  # noqa: E402
import test_rollcheck as R  # noqa: E402
from photoeditor.desktop import roll_even  # noqa: E402
from photoeditor.features.densitometry import rollcheck  # noqa: E402
from photoeditor.features.persistence import edit_store, roll_undo  # noqa: E402


def png(path, linear):
    cv2.imwrite(str(path), np.round(np.clip(linear, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)[..., ::-1])
    return str(path)


def report_for(frames, paths):
    return rollcheck.compare([rollcheck.frame_stats(os.path.basename(p), f, R.INFO, p) for f, p in zip(frames, paths)])


def test_only_differing_frames_with_a_sure_border_are_candidates():
    paths = [f"/x/f{i}.png" for i in range(5)]
    frames = [R.frame(i) for i in range(5)]
    frames[2] = R.frame(2, light=1.7)
    rep = report_for(frames, paths)
    cands = roll_even.candidates(rep)
    assert [c.path for c in cands] == ["/x/f2.png"] and cands[0].stops > 0.5
    x1, y1, x2, y2 = cands[0].rect_frac
    assert 0.0 <= x1 < x2 <= 0.2 and 0.0 <= y1 < y2 <= 1.0, "the left border strip"
    frames[1] = R.frame(1, light=1.15)
    slight = report_for(frames, paths)
    assert [c.path for c in roll_even.candidates(slight)] == ["/x/f2.png"]
    assert {c.path for c in roll_even.candidates(slight, include_notes=True)} == {"/x/f1.png", "/x/f2.png"}


def test_a_frame_whose_border_is_only_a_medium_guess_is_never_a_candidate():
    paths = [f"/x/f{i}.png" for i in range(4)]
    frames = [R.frame(i) for i in range(3)] + [np.clip(T.film(bare_left=0, rebate_left=30, seed=9) * 1.8, 1e-5, 1.0)]
    rep = report_for(frames, paths)
    assert rep.frames[3].confidence in ("medium", "low") and rep.frames[3].level == "warning"
    assert roll_even.candidates(rep) == []


def test_the_border_is_read_as_the_picture_shows_it_and_a_non_uniform_patch_is_refused(tmp_path):
    lin = R.frame(3, light=1.5)
    path = png(tmp_path / "a.png", lin)
    others = [R.frame(1), R.frame(2)]
    rep = report_for([lin, *others], [path, str(tmp_path / 'b.png'), str(tmp_path / 'c.png')])
    frac = rep.frames[0].rect_frac
    rgb, spread = roll_even.measure_display_base(path, frac)
    expect = np.round(np.clip(T.BASE * 1.5, 0, 1) ** (1 / 2.2) * 255)
    assert np.allclose(rgb, expect, atol=3) and spread < 4
    _bad, wide = roll_even.measure_display_base(path, (0.3, 0.2, 0.9, 0.8))
    assert wide > roll_even.MAX_SPREAD


def test_each_frame_gets_its_own_base_once_and_it_is_journalled(tmp_path):
    lin = [R.frame(i) for i in range(4)]
    lin[1] = R.frame(1, light=1.6)
    paths = [png(tmp_path / f"f{i}.png", f) for i, f in enumerate(lin)]
    db = str(tmp_path / "e.db")
    conn = edit_store.connect(db)
    edit_store.set_folder_base(conn, edit_store.folder_key(paths[0]), (120, 100, 80))
    cands = roll_even.candidates(report_for(lin, paths))
    assert [c.path for c in cands] == [paths[1]]
    s = roll_even.run(cands, db)
    assert s["done"] == [paths[1]] and not s["skipped"] and len(s["ops"]) == 1
    own = edit_store.get_photo_film_base(conn, paths[1])
    assert own is not None and own != (120, 100, 80) and edit_store.effective_film_base(conn, paths[1]) == own
    assert edit_store.effective_film_base(conn, paths[0]) == (120, 100, 80), "the roll's film base is untouched"
    again = roll_even.run(cands, db)
    assert not again["done"] and "already uses" in again["skipped"][0][1]
    from photoeditor.desktop.export_worker import _edits_for

    preview = np.zeros((10, 10, 3), np.uint8)
    params, _ff = _edits_for(paths[1], conn, preview, {**__import__("photoeditor.desktop.export_worker", fromlist=["x"]).default_edit_state(True)})
    assert params.film_base == own, "the conversion uses it"
    roll_undo.record(conn, str(tmp_path), "Even Out Roll", s["ops"])
    res = roll_undo.undo(conn, roll_undo.latest(conn, str(tmp_path)), skip_paths={paths[1]})
    assert res.restored == [paths[1]] and edit_store.get_photo_film_base(conn, paths[1]) is None, "a film-base change is undone even for the open photo"


def test_clear_own_bases_puts_frames_back_on_the_roll(tmp_path):
    db = str(tmp_path / "e.db")
    conn = edit_store.connect(db)
    a, b = str(tmp_path / "a.png"), str(tmp_path / "b.png")
    edit_store.set_photo_film_base(conn, a, (1, 2, 3))
    s = roll_even.clear_own_bases([a, b], db)
    assert s["done"] == [a] and edit_store.get_photo_film_base(conn, a) is None and len(s["ops"]) == 1


_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    sys.path.insert(0, TESTS)
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from photoeditor.features.settings import logic as S
    from photoeditor.features.persistence import edit_store
    from photoeditor.features.densitometry import roll_job
    from photoeditor.features.densitometry.linear import LinearScan
    S.save({"scan_quality": False})
    import test_rollcheck as R
    import test_rebate as T
    folder = os.path.join(work, "roll"); os.makedirs(folder)
    lin = {}
    for i in range(5):
        f = R.frame(i, light=1.7 if i == 2 else 1.0)
        p = os.path.join(folder, f"IMG_{i}.cr2.png")
        cv2.imwrite(p, np.round(np.clip(f, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)[..., ::-1]); lin[os.path.basename(p)] = f
    paths = sorted(os.path.join(folder, n) for n in lin)
    roll_job.decode_linear_raw = lambda p, half_size=False: LinearScan(lin[os.path.basename(p)], R.INFO)
    roll_job.is_measurable = lambda p: p.endswith(".cr2.png")
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view.roll_check_dialog import RollCheckDialog
    shown = []
    QMessageBox.information = staticmethod(lambda *a, **k: shown.append(a[2]))
    win = aw.AppWindow(); c = win.controller
    win.open_folder(folder, prefer=paths[2])
    c.set_film_base((140, 120, 100))
    assert c.state.film_base == (140, 120, 100)
    before_image = c.state.image_rgb.copy()

    changed = []
    dlg = RollCheckDialog(paths, None, win, controller=c, on_changed=lambda ps: (changed.extend(ps), win._after_film_base_change(ps)))
    dlg._worker.wait(60000); app.processEvents()
    assert dlg.report is not None and dlg.even_button.isEnabled() and "sure about" in dlg.status.text(), dlg.status.text()
    assert not dlg.clear_button.isEnabled()
    asked = []
    dlg._ask = lambda *a: (asked.append(a[0]), False)[1]
    dlg.even_out(); assert asked == ["Even Out Roll"] and dlg._even_worker is None and edit_store.get_photo_film_base(c._db, paths[2]) is None
    dlg._ask = lambda *a: True
    dlg.even_out(); dlg._even_worker.wait(60000); app.processEvents()
    own = edit_store.get_photo_film_base(c._db, paths[2])
    assert own is not None and changed == [paths[2]] and "Evened out 1 frame" in dlg.status.text(), dlg.status.text()
    assert all(edit_store.get_photo_film_base(c._db, p) is None for p in paths if p != paths[2])
    assert c.state.film_base == own and not np.array_equal(c.state.image_rgb, before_image), "the open photo is redrawn with its own film base"
    assert win._filmstrip._undo_roll_btn.text() == "Undo Even Out Roll" and dlg.clear_button.isEnabled()

    # undo: the button above the filmstrip puts the roll's film base back, including on the open photo
    win._ask_undo_roll = lambda label, n: True
    win.undo_roll_action()
    assert edit_store.get_photo_film_base(c._db, paths[2]) is None and c.state.film_base == (140, 120, 100)

    # setting the roll's film base on a photo that had its own drops the own one
    edit_store.set_photo_film_base(c._db, paths[2], own)
    c.set_film_base((130, 110, 90))
    assert edit_store.get_photo_film_base(c._db, paths[2]) is None and c.state.film_base == (130, 110, 90)

    # use the roll's film base again
    edit_store.set_photo_film_base(c._db, paths[2], own); c.refresh_film_base()
    dlg2 = RollCheckDialog(paths, None, win, controller=c, on_changed=lambda ps: None)
    dlg2._worker.wait(60000); app.processEvents()
    assert dlg2.clear_button.isEnabled()
    dlg2._ask = lambda *a: True; dlg2.use_roll_base_again()
    assert edit_store.get_photo_film_base(c._db, paths[2]) is None and c.state.film_base == (130, 110, 90)
    win.close()
    print("EVEN OUT OK")
    sys.stdout.flush(); os._exit(0)
'''.replace("TESTS", repr(str(Path(__file__).resolve().parent))))


def test_even_out_from_the_roll_check_dialog():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert "EVEN OUT OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3500:]
