"""Before & After: the Before side can be the picture right after inversion or the picture as it was after any step of the History, and both sides are HQ (made from the full-resolution picture) -
the split switches HQ on while it is up and puts it back when it closes."""
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
    yy, xx = np.mgrid[0:300, 0:450]
    img = np.clip(np.stack([60 + 120 * xx / 450, 80 + 90 * yy / 300, 150 - 60 * xx / 450], axis=2) + rng.normal(0, 4, (300, 450, 3)), 0, 255).astype(np.uint8)
    path = os.path.join(folder, "a.png"); cv2.imwrite(path, img[:, :, ::-1])
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=path)
    def pump(secs):
        end = time.time() + secs
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(3)
    s = c.state
    c.set_exposure_ev(0.8); pump(1.5)
    c.set_color(0.5, 0.0, 0.0) if hasattr(c, "set_color") else None
    pump(1.0)
    n = len(s.history)
    assert n >= 3, [h.description for h in s.history]
    label = win._image_view._label
    box = win._split_box
    assert box.isHidden(), "the picker only shows while Before & After is up"

    # --- opening it: the picker lists the default and every step, and HQ is on for both sides
    assert not s.hq_enabled
    win.set_split(True); pump(4)
    assert not box.isHidden() and box.count() == 1 + n and box.itemText(0) == "Right after inversion" and box.itemText(1).startswith("1. ")
    assert s.hq_enabled and win._split_forced_hq and win._hq_btn.isChecked(), "HQ is on while the split is up"
    default_before = label._split_buf.copy()
    assert label._split_buf.shape[:2] == s.image_rgb.shape[:2], "the two sides are the same size"

    # --- choose a step as the Before: the first step is the picture as it opened; the last is the edit as it is
    box.setCurrentIndex(1); box.activated.emit(1); pump(2)
    first = label._split_buf.copy()
    assert win._split_source == 0
    last = n
    box.setCurrentIndex(last); box.activated.emit(last); pump(2)
    final = label._split_buf.copy()
    assert win._split_source == n - 1
    assert np.abs(final.astype(int) - s.image_rgb.astype(int)).mean() < 1.5, "the last step is the edit as it is now"
    assert np.abs(first.astype(int) - final.astype(int)).mean() > 3, "an early step is not"
    c.set_exposure_ev(-0.5); pump(3)
    assert np.abs(label._split_buf.astype(int) - final.astype(int)).mean() < 0.5, "the chosen step stays as it was when the edit moves on"
    assert box.count() == 1 + len(s.history), "the picker follows the History"

    # --- back to the default, and closing puts HQ back
    box.setCurrentIndex(0); box.activated.emit(0); pump(2)
    assert win._split_source is None and np.abs(label._split_buf.astype(int) - default_before.astype(int)).mean() < 0.5
    win.set_split(False); pump(3)
    assert box.isHidden() and not s.hq_enabled and not win._split_forced_hq, "HQ is back as it was"
    # with HQ already on, closing leaves it on
    win._hq_btn.setChecked(True); pump(3)
    win.set_split(True); pump(2); win.set_split(False); pump(2)
    assert s.hq_enabled
    print("OK")
""")


def test_before_and_after_can_show_any_history_step_in_hq():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=600, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-3500:]
