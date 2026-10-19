"""Show Detections marks clone strokes (in blue) as well as heals, so a clone can be seen - and deleted with the delete picker."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np

from photoeditor.features.retouch import logic
from photoeditor.features.retouch.clone import clone_footprint

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_the_footprint_of_a_clone_stroke_is_where_it_paints():
    stroke = ([[0.5, 0.5], [0.6, 0.5]], 10.0, -0.25, 0.0, 1.0, 0.0, False)   # (points, size, dx, dy, strength, feather, match tone)
    mask = clone_footprint((200, 300), [stroke])
    ys, xs = np.nonzero(mask)
    assert mask.shape == (200, 300) and abs(xs.mean() - 165) < 4 and abs(ys.mean() - 100) < 1, "centred on the stroke (x 150..180, y 100)"
    assert clone_footprint((200, 300), []) is None
    assert clone_footprint((200, 300), [([[0.5, 0.5]], 10.0, 0.0, 0.0, 1.0, 0.0, False)]) is None, "a stroke that copies from where it is painting changes nothing"
    assert clone_footprint((200, 300), [([[0.5, 0.5]], 10.0, 0.2, 0.0, 0.0, 0.0, False)]) is None, "nor does one with no strength"


def test_the_repair_result_carries_the_clone_footprint():
    rng = np.random.default_rng(0)
    pixels = (100 + 20 * rng.random((200, 300, 3))).astype(np.uint8)
    stroke = ([[0.7, 0.5], [0.75, 0.5]], 10.0, -0.3, 0.0, 1.0, 0.0, False)
    result = logic.remove_dust_and_scratches(pixels, auto=False, clone_strokes=[stroke])
    assert result.clone is not None and result.clone.any() and result.manual is None
    assert logic.remove_dust_and_scratches(pixels, auto=False).clone is None


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp(); folder = os.path.join(work, "r"); os.makedirs(folder)
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    img = (120 + 30 * cv2.GaussianBlur(np.random.default_rng(1).random((800, 1200, 3)).astype(np.float32), (0, 0), 6)).astype(np.uint8)
    img[290:310, 290:310] = 250
    path = os.path.join(folder, "a.png"); cv2.imwrite(path, img)
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=path)
    def pump(cond=lambda: False, secs=20.0):
        end = time.time() + secs
        while time.time() < end:
            app.processEvents()
            if cond(): return True
            time.sleep(0.01)
        return cond()
    assert pump(lambda: c.state.image_rgb is not None); pump(secs=1.0)
    s = c.state
    c.set_clone_source(300.0, 300.0)
    c.add_clone_stroke([(600.0, 300.0), (620.0, 300.0)], 14, 1.0, 0.0, False)
    assert len(s.clone_strokes) == 1
    c.set_show_detections(True)
    assert pump(lambda: s.overlay_rgba is not None and (s.overlay_rgba[..., 3] > 0).any()), "the clone is marked"
    ov = s.overlay_rgba
    blue = (ov[..., 3] > 0) & (ov[..., 2] > 200) & (ov[..., 0] < 100)
    ys, xs = np.nonzero(blue)
    assert len(xs) > 100 and abs(xs.mean() - 610) < 12 and abs(ys.mean() - 300) < 6, (len(xs), xs.mean() if len(xs) else None)
    assert not ((ov[..., 3] > 0) & (ov[..., 0] > 200)).any(), "nothing else is marked: the clone is not a heal or a speck"
    c.delete_manual_repair_at(610.0, 300.0)
    assert len(s.clone_strokes) == 0, "the delete picker takes it out"
    assert pump(lambda: s.overlay_rgba is None or not (s.overlay_rgba[..., 3] > 0).any())
    win.close()
    print("CLONE OVERLAY OK")
""")


def test_show_detections_marks_a_clone_and_the_delete_picker_removes_it():
    done = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC, "PHOTOEDITOR_AUDIO": "off"})
    assert "CLONE OVERLAY OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3000:]
