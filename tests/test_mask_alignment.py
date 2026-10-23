"""A shape lies exactly where the pointer put it and where its effect is: the half-pixel between the screen's coordinates and the picture's pixels is accounted for, and the mapping between the scan
and the picture shown (used to draw outlines) stays within a fraction of a pixel even with a lens correction."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np

from photoeditor.features.masks.frame import FrameMap

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_the_outline_mapping_is_within_a_fraction_of_a_pixel_with_a_lens_correction_and_keystone():
    size = (1067, 1600)
    pts = np.array([[x, y] for x in np.linspace(0.05, 0.95, 7) for y in np.linspace(0.05, 0.95, 7)])
    for kw in (dict(distortion=0.3), dict(keystone_v=0.3, keystone_h=0.2), dict(fine=3.0, distortion=0.2, keystone_v=0.2)):
        fm = FrameMap((100, 60, 1500, 1000), size, 0, False, False, kw.get("fine", 0.0), kw.get("distortion", 0.0), kw.get("keystone_v", 0.0), kw.get("keystone_h", 0.0))
        uv = fm.to_display_array(pts)
        back = np.array([fm.to_raw(u, v) for u, v in uv])
        err = np.hypot((back[:, 0] - pts[:, 0]) * size[1], (back[:, 1] - pts[:, 1]) * size[0])
        assert err.mean() < 0.15 and err.max() < 0.6, (kw, err.max(), err.mean())


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp(); folder = os.path.join(work, "r"); os.makedirs(folder)
    import numpy as np, cv2
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.features.masks import model as M
    S.save({"scan_quality": False})
    rng = np.random.default_rng(0)
    img = np.clip(120 + rng.normal(0, 3, (600, 900, 3)), 0, 255).astype(np.uint8)
    path = os.path.join(folder, "a.png"); cv2.imwrite(path, img)
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=path)
    def pump(secs):
        end = time.time() + secs
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(3)
    s = c.state; panel = win._retouch_tool; lab = win._image_view._label
    panel._algo["fill"].click()
    c.set_retouch({"fill_mode": "color", "fill_color": [1.0, 0.0, 0.0]}); pump(0.5)
    for turn in (0, 1):
        if turn:
            c.set_fine_rotation(4.0); pump(2)
        ids = [f.id for f in c.mask_set().forms.values()]
        if ids: c.delete_masks(ids); pump(1)
        panel._draw[M.CIRCLE].click(); app.processEvents()
        k = lab._scale
        pos = QPoint(int(lab.width() * 0.4), int(lab.height() * 0.4))
        QTest.mouseClick(lab, Qt.MouseButton.LeftButton, pos=pos)
        pump(2)
        red = (s.image_rgb[..., 0].astype(int) - s.image_rgb[..., 2].astype(int)) > 80
        ys, xs = np.nonzero(red)
        cx, cy = xs.mean() + 0.5, ys.mean() + 0.5                   # the effect's centre, continuous picture coordinates
        form = [f for f in c.mask_set().forms.values() if f.type == M.CIRCLE][0]
        ox, oy = c.raw_to_display(np.array([form.points[0]["center"]], float))[0] + 0.5     # where the outline is painted
        px, py = pos.x() / k, pos.y() / k
        assert abs(px - ox) < 0.1 and abs(py - oy) < 0.1, ("outline", (px, py), (ox, oy))
        assert abs(px - cx) < 0.25 and abs(py - cy) < 0.25, ("effect", (px, py), (cx, cy))
    print("OK aligned")
""")


def test_a_shape_is_where_the_pointer_put_it_and_where_its_effect_is():
    r = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "OK aligned" in r.stdout, r.stdout[-1500:] + r.stderr[-3000:]
