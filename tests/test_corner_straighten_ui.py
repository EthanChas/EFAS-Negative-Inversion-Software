"""Crop & Rotate > Four-Corner Straighten in the window: four clicks set the angle, the keystone and the crop as one step."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile, time, math
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    p = os.path.join(work, "a.png")
    cv2.imwrite(p, np.random.default_rng(0).integers(40, 200, (400, 600, 3), dtype=np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.show(); win.resize(1500, 900); win.open_folder(work, prefer=p)
    c = win.controller
    def pump(s):
        end = time.time() + s
        while time.time() < end:
            app.processEvents(); time.sleep(0.01)
    pump(1.5)
    panel, iv = win._crop_tool, win._image_view
    label = iv._label
    assert panel._corners_btn.text() == "Four-Corner Straighten" and not panel.corners_active()

    panel._corners_btn.click(); pump(0.2)
    assert panel.corners_active() and label._tool == "corners"
    iw, ih = c.state.image_rgb.shape[1], c.state.image_rgb.shape[0]
    # the corners of a photo that sits 3 degrees clockwise: a 440 x 280 rectangle turned about its centre
    cx, cy, a = iw / 2, ih / 2, math.radians(3.0)
    def rot(x, y):
        dx, dy = x - cx, y - cy
        return cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a)
    corners = [rot(cx - 220, cy - 140), rot(cx + 220, cy - 140), rot(cx + 220, cy + 140), rot(cx - 220, cy + 140)]
    history = len(c.state.history)
    k = label._scale
    for x, y in (corners[2], corners[0], corners[3], corners[1]):   # any order
        QTest.mouseClick(label, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(x * k), round(y * k)))
        pump(0.05)
    pump(0.8)
    s = c.state
    assert abs(abs(s.fine_rotation) - 3.0) < 0.3, s.fine_rotation
    assert abs(s.keystone_v) < 0.03 and abs(s.keystone_h) < 0.03, (s.keystone_v, s.keystone_h)
    assert s.crop_rect is not None
    x1, y1, x2, y2 = s.crop_rect
    scale = max((iw * math.cos(a) + ih * math.sin(a)) / iw, (iw * math.sin(a) + ih * math.cos(a)) / ih)   # a turned picture is enlarged to fill the frame
    assert abs((x2 - x1) - 440 * scale) < 15 and abs((y2 - y1) - 280 * scale) < 15, s.crop_rect
    assert len(s.history) == history + 1 and "four corners" in s.history[-1].description, "one step"
    assert not panel.corners_active() and label._tool is None, "the tool puts itself away"
    assert abs(panel._fine.value() - s.fine_rotation) < 0.06, "the Angle slider shows it"
    assert win._image_view._label._pixels.shape == s.image_rgb.shape, "the edited picture is back on screen"
    assert win._coord_label.text().startswith("Straightened from the four corners")
    c.undo()
    pump(0.5)
    assert c.state.fine_rotation == 0.0 and c.state.crop_rect is None, "undo takes it all back"

    # the tool can be cancelled by switching it off, and other tools switch it off
    panel._corners_btn.click(); pump(0.1)
    assert panel.corners_active()
    panel._straighten_btn.click(); pump(0.1)
    assert not panel.corners_active() and label._tool == "straighten"
    panel._straighten_btn.click(); pump(0.1)
    panel._corners_btn.click(); pump(0.1)
    panel._corners_btn.click(); pump(0.1)
    assert not panel.corners_active() and label._tool is None and label._pixels.shape == c.state.image_rgb.shape
    # three points are not enough and nothing changes
    panel._corners_btn.click(); pump(0.1)
    for x, y in corners[:3]:
        QTest.mouseClick(label, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(x * k), round(y * k)))
    pump(0.2)
    assert panel.corners_active() and c.state.crop_rect is None
    print("ok")
''')


def test_four_corner_straighten_in_the_window():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    r = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-3000:]
