"""The yellow of a shown mask (the eye in a module's Mask box) belongs to the photo it was shown on: opening another photo takes it away."""
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
    from photoeditor.features.masks import blend as B
    S.save({"scan_quality": False})
    rng = np.random.default_rng(0)
    paths = []
    for name in ("a.png", "b.png"):
        img = np.clip(110 + rng.normal(0, 5, (300, 450, 3)), 0, 255).astype(np.uint8)
        paths.append(os.path.join(folder, name)); cv2.imwrite(paths[-1], img)
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=paths[0])
    def pump(secs):
        end = time.time() + secs
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(3)
    box = win._blend_boxes["exposure"]; editor = win._mask_editor; label = win._image_view._label
    i = box._mode.findData(B.UNIFORM); box._mode.setCurrentIndex(i); box._mode.activated.emit(i); pump(0.5)
    editor.show_module("exposure", True); pump(1.5)
    assert label._mask_show is not None, "the mask is shown in yellow on the first photo"
    c.open_file(paths[1]); pump(3)
    assert label._mask_show is None and editor._show_key is None, "another photo: the yellow is gone"
    assert not box._show.isChecked(), "and the eye is up"
    print("OK")
""")


def test_a_shown_mask_does_not_follow_you_to_the_next_photo():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-3000:]
