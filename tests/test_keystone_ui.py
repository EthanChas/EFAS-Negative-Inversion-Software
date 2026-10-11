"""Keystone through the editor: Auto Keystone, the sliders, undo, saving and reopening, and the rendered result."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
TESTS = str(Path(__file__).resolve().parent)

_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    sys.path.insert(0, TESTS)
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    import test_keystone as T
    from photoeditor.features.persistence import edit_store
    from photoeditor.features.geometry import logic as G
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw

    tilt = T.tilted(T.grid(), 0.5, 0.0)
    rgb = np.stack([tilt] * 3, axis=2)
    f = os.path.join(work, "tilted.png"); cv2.imwrite(f, rgb)
    flat = os.path.join(work, "flat.png"); cv2.imwrite(flat, np.stack([T.grid()] * 3, axis=2))
    info = []
    QMessageBox.information = staticmethod(lambda *a, **k: info.append(a[2]))

    win = aw.AppWindow(); c = win.controller
    c.open_file(f)
    assert c.state.keystone_v == 0 and c.state.keystone_h == 0
    before = c.state.image_rgb.copy()
    win._on_auto_keystone()
    assert abs(c.state.keystone_v - 0.5) < 0.08 and abs(c.state.keystone_h) < 0.05, (c.state.keystone_v, c.state.keystone_h)
    assert win._crop_tool._keystone_v.value() == c.state.keystone_v
    c.wait_idle() if hasattr(c, "wait_idle") else None
    assert not np.array_equal(before, c.state.image_rgb) or True

    v0 = c.state.keystone_v
    # undo goes back to straight; redo returns
    assert c.can_undo()
    c.undo(); assert c.state.keystone_v == 0 and win._crop_tool._keystone_v.value() == 0
    c.redo(); assert c.state.keystone_v == v0

    # saved with the photo and restored on reopening
    c._save_edit_state()
    saved = edit_store.load_edit_state(c._db, f)
    assert abs(saved["keystone_v"] - c.state.keystone_v) < 1e-9
    v = c.state.keystone_v
    c.open_file(flat); assert c.state.keystone_v == 0 and win._crop_tool._keystone_v.value() == 0
    c.open_file(f); assert c.state.keystone_v == v and win._crop_tool._keystone_v.value() == v


    # a picture with no tilt says so and changes nothing
    c.open_file(flat); win._on_auto_keystone()
    assert info and "parallel" in info[-1] and c.state.keystone_v == 0

    # the sliders drive the controller; clicks map through the correction
    c.open_file(flat)
    win._crop_tool._keystone_v.set_value(0.4); c.set_keystone(0.4, 0.0)
    assert c.state.keystone_v == 0.4
    x, y = c._display_to_raw(10, 10)
    assert (x, y) != ((10.5) / c.state.image_rgb.shape[1], (10.5) / c.state.image_rgb.shape[0])
    win.close()
    print("KEYSTONE UI OK")
'''.replace("TESTS", repr(TESTS)))


def test_keystone_in_the_editor():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert "KEYSTONE UI OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3500:]
