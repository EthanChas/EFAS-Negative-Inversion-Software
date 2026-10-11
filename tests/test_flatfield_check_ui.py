"""Check Flat Field in the editor: the open photo, a reference file before it is saved, and the roll's gain after it is built."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
TESTS = str(Path(__file__).resolve().parent)

_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    sys.path.insert(0, TESTS)
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.features.persistence import edit_store
    S.save({"scan_quality": False})
    import test_flatfield_check as T
    folder = os.path.join(work, "roll"); os.makedirs(folder)
    paths = []
    for i in range(6):
        p = os.path.join(folder, f"f{i}.png"); cv2.imwrite(p, T.field(seed=i)[..., ::-1]); paths.append(p)
    good = os.path.join(work, "light_good.png"); cv2.imwrite(good, T.field(falloff=0.5, seed=11)[..., ::-1])
    clipped = os.path.join(work, "light_clipped.png"); cv2.imwrite(clipped, T.field(level=330, falloff=0.5, seed=12)[..., ::-1])
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); c = win.controller
    win.open_folder(folder, prefer=paths[0])
    shown = []
    def fake_show(result, what, ask=False):
        shown.append((result.level, what, ask)); return answer["use"]
    answer = {"use": False}
    win._show_flat_check = fake_show
    def stored(): return edit_store.get_folder_flatfield(c._db, edit_store.folder_key(paths[0]))

    # the open photo, before any flat field
    win._on_flatfield_check("")
    assert shown[-1][0] == "good" and shown[-1][1] == "f0.png" and not shown[-1][2]

    # a good reference is saved without a question
    win._on_flatfield_reference_picked(good)
    assert stored() is not None and len(shown) == 1 and c.flatfield_info()["enabled"]
    # now the open photo is checked after the correction
    win._on_flatfield_check("")
    assert "flat field applied" in shown[-1][1]

    # a clipped reference asks first; declining keeps what was there
    before = stored()["source"]
    win._on_flatfield_reference_picked(clipped)
    assert shown[-1][0] == "poor" and shown[-1][2] is True and stored()["source"] == before
    assert "Not used" in win._flatfield_tool._status.text()
    answer["use"] = True
    win._on_flatfield_reference_picked(clipped)
    assert stored()["source"] == "light_clipped.png"

    # any file can be checked as a reference
    win._on_flatfield_check(good); assert shown[-1][0] == "good" and shown[-1][1] == "light_good.png"

    # the roll's own gain is checked when it is built
    c.clear_folder_flatfield()
    c.start_roll_flatfield()
    t = time.time()
    while c._ff_worker is not None and time.time() - t < 60:
        app.processEvents(); time.sleep(0.02)
    for _ in range(20): app.processEvents()
    assert stored() is not None and "range" in win._flatfield_tool._status.text() or "correction" in win._flatfield_tool._status.text()
    assert win._flatfield_tool._check_btn.menu() is not None
    win.close()
    print("FLAT CHECK UI OK")
'''.replace("TESTS", repr(TESTS)))


def test_check_flat_field_in_the_editor():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert "FLAT CHECK UI OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3500:]
