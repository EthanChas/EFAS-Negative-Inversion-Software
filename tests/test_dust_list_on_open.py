"""The Dust Detection folder of the Masks panel says what is on the picture as soon as a photo is opened (no edit needed first), and a folder clicked shows the same count it lists."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp(); folder = os.path.join(work, "r"); os.makedirs(folder)
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    rng = np.random.default_rng(0)
    base = np.linspace(60, 190, 900, dtype=np.float32)[None, :, None] * np.ones((600, 1, 3), np.float32)
    img = np.clip(base + rng.normal(0, 3, (600, 900, 3)), 0, 255).astype(np.uint8)
    for x, y in ((150, 120), (700, 480), (420, 300)):
        cv2.circle(img, (x, y), 4, (20, 20, 20), -1)
    a, b = os.path.join(folder, "a.png"), os.path.join(folder, "b.png")
    cv2.imwrite(a, img); cv2.imwrite(b, img)
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=a)
    def pump(cond=lambda: False, secs=20.0):
        end = time.time() + secs
        while time.time() < end:
            app.processEvents()
            if cond(): return True
            time.sleep(0.01)
        return cond()
    assert pump(lambda: c.state.image_rgb is not None); pump(secs=1.5)
    tree = win._mask_manager._tree
    label = lambda i: tree.topLevelItem(0).child(i).text(0)
    c.set_dust(True, 0.5, 10, 0.8); assert pump(lambda: label(0) == "Dust (3)", 20.0), label(0)
    c._save_edit_state()
    c.open_file(b); pump(secs=2.5)
    assert label(0) == "Dust (0)", "a photo with no dust removal on lists none"
    c.open_file(a)
    assert pump(lambda: label(0) == "Dust (3)", 20.0), ("the photo opened with dust removal on lists its specks by itself", label(0))
    tree.clearSelection(); tree.topLevelItem(0).child(0).setSelected(True); app.processEvents()
    assert len(win._image_view._label._focus_marks) == 3, "the folder shows as many as it lists"
    print("OK listed")
""")


def test_the_dust_folder_is_filled_when_a_photo_is_opened():
    r = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "OK listed" in r.stdout, r.stdout[-1500:] + r.stderr[-3000:]
