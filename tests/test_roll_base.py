"""Find Film Base for the Whole Roll: one film base read from the clear border of several frames."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np

from photoeditor.features.negative import rollbase

SRC = str(Path(__file__).resolve().parents[1] / "src")


def frame(border=(190, 120, 70), seed=0, size=(300, 450), picture=True):
    rng = np.random.default_rng(seed)
    h, w = size
    out = np.empty((h, w, 3), np.uint8)
    out[...] = border
    out = np.clip(out.astype(int) + rng.integers(-2, 3, out.shape), 0, 255).astype(np.uint8)
    if picture:
        y, x = int(h * 0.15), int(w * 0.12)
        content = rng.integers(20, 120, (h - 2 * y, w - 2 * x, 3))
        out[y:h - y, x:w - x] = content.astype(np.uint8)
    return out


def test_the_roll_gets_the_median_of_its_frames_borders():
    frames = [frame((190, 120, 70), 1), frame((192, 119, 71), 2), frame((188, 122, 69), 3)]
    base = rollbase.estimate(frames)
    assert base is not None and base.frames == 3 and base.checked == 3
    assert all(abs(a - b) <= 3 for a, b in zip(base.rgb, (190, 120, 70)))


def test_frames_without_a_border_do_not_count_and_one_frame_is_not_enough():
    assert rollbase.estimate([frame(seed=1), frame(seed=2, picture=False), frame(seed=3, picture=False)]) is None, "a blank scan has no frame to find"
    full = np.random.default_rng(5).integers(0, 255, (300, 450, 3)).astype(np.uint8)
    assert rollbase.estimate([full, full]) is None, "pictures running to the edges have no border"


def test_a_roll_whose_borders_disagree_is_not_given_a_base():
    assert rollbase.estimate([frame((190, 120, 70), 1), frame((90, 150, 200), 2)]) is None
    mostly = rollbase.estimate([frame((190, 120, 70), 1), frame((191, 121, 70), 2), frame((60, 200, 90), 3)])
    assert mostly is not None and mostly.frames == 2 and mostly.checked == 3, "an odd frame out is ignored when most agree"


def test_an_uneven_border_is_not_trusted():
    rng = np.random.default_rng(9)
    f = frame(seed=4)
    f[:12] = rng.integers(40, 250, f[:12].shape).astype(np.uint8)
    f[-12:] = rng.integers(40, 250, f[-12:].shape).astype(np.uint8)
    assert rollbase.frame_border(f) is None or rollbase.frame_border(f)[1] > rollbase.MAX_SPREAD


_SCRIPT = textwrap.dedent(r'''
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    rng = np.random.default_rng(0)
    paths = []
    for i in range(4):
        img = np.empty((300, 450, 3), np.uint8); img[...] = (70, 120, 190)  # BGR on disk: an orange base
        img[45:255, 54:396] = rng.integers(20, 120, (210, 342, 3))
        p = os.path.join(work, f"f{i}.png"); cv2.imwrite(p, img); paths.append(p)
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.show(); win.open_folder(work, prefer=paths[0])
    end = time.time() + 30
    while time.time() < end and win.controller.state.image_path is None: app.processEvents(); time.sleep(0.01)
    assert win.controller.state.image_path, "the photo opened"
    found = win.controller.suggest_roll_base()
    assert found["found"] and found["frames"] == 4, found
    assert all(abs(a - b) <= 3 for a, b in zip(found["rgb"], (190, 120, 70))), found
    from PyQt6.QtWidgets import QMessageBox
    asked = []
    QMessageBox.question = staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.Yes)
    win._negative_tool._roll_base_btn.click()
    assert asked and "4 of the 4" in asked[0], asked
    end = time.time() + 5
    while time.time() < end: app.processEvents(); time.sleep(0.01)
    assert win.controller.state.film_base == tuple(found["rgb"])
    print("OK")
''')


def test_the_controller_reads_a_roll_from_its_folder_and_the_button_is_there():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-1500:]
