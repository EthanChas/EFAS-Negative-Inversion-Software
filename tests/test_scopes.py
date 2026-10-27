"""Waveform, RGB parade and vectorscope (features/scopes) and the graph that draws them."""
import os

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from photoeditor.features.scopes import logic as S

_APP = None


def _app():
    global _APP
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])
    return _APP


def ramp(h=120, w=300):
    return np.tile(np.linspace(0, 255, w, dtype=np.uint8)[None, :, None], (h, 1, 3))


def test_a_ramp_makes_a_diagonal_waveform():
    wf = S.waveform(ramp())
    assert wf.shape == (S.SIZE, 300) and 0.0 <= wf.min() and wf.max() <= 1.0
    for x in (10, 150, 290):      # the brightness of the column is where its trace sits (row 0 is value 255)
        rows = np.where(wf[:, x] > 0.5)[0]
        value = 255 - rows.mean()
        assert abs(value - 255 * x / 299) < 4, (x, value)
    assert wf[:20, :20].max() == 0.0, "a dark left edge has nothing at the top"


def test_a_flat_picture_is_one_line_and_a_big_picture_is_thinned():
    flat = np.full((200, 200, 3), 100, np.uint8)
    wf = S.waveform(flat)
    assert (wf.sum(axis=1) > 0).sum() == 1 and wf[255 - 100].min() > 0.9
    big = np.zeros((2000, 4000, 3), np.uint8)
    assert S.prepare(big).shape[1] <= S.MAX_COLUMNS and S.prepare(big).shape[0] <= S.MAX_COLUMNS
    assert S.waveform(big).shape[1] <= S.MAX_COLUMNS
    assert S.prepare(np.zeros((10, 10, 3), np.uint16) + 65535).max() == 255 and S.prepare(np.ones((4, 4, 3), np.float32)).max() == 255 and S.prepare(np.zeros((4, 4), np.uint8)).shape == (4, 4, 3)


def test_the_parade_has_a_colour_cast_in_its_channels():
    cast = np.zeros((100, 120, 3), np.uint8)
    cast[..., 0], cast[..., 1], cast[..., 2] = 200, 120, 60       # a warm grey
    p = S.parade(cast)
    assert p.shape == (S.SIZE, 360, 3)
    for c, value in enumerate((200, 120, 60)):
        panel = p[:, c * 120:(c + 1) * 120]
        assert panel[..., c].max() > 0.9 and np.where(panel[..., c].max(axis=1) > 0.5)[0].tolist() == [255 - value]
        assert panel[..., [i for i in range(3) if i != c]].max() == 0.0, "each third is its own colour"


def test_the_vectorscope_puts_hue_at_the_angle_and_grey_in_the_middle():
    size = 128
    grey = S.vectorscope(np.full((50, 50, 3), 128, np.uint8), size)
    ys, xs = np.nonzero(grey > 0)
    assert abs(xs.mean() - (size - 1) / 2) < 1.5 and abs(ys.mean() - (size - 1) / 2) < 1.5, "no colour is the centre"
    red = np.zeros((50, 50, 3), np.uint8)
    red[..., 0] = 255
    ys, xs = np.nonzero(S.vectorscope(red, size) > 0)
    assert ys.mean() < size / 2 - 20 and abs(xs.mean() - size / 2) < 30, "red is up (Cr) and a little left"
    blue = np.zeros((50, 50, 3), np.uint8)
    blue[..., 2] = 255
    ys, xs = np.nonzero(S.vectorscope(blue, size) > 0)
    assert xs.mean() > size / 2 + 30, "blue is to the right (Cb)"
    fx, fy = S.vector_point(S.TARGETS["R"])
    assert fy > 0.6 and fx < 0.5, "the R target is up and left of centre"


def test_the_graph_draws_each_view():
    _app()
    from photoeditor.desktop.view.scope_view import MODES, ScopeView
    view = ScopeView()
    view.resize(400, 190)
    view.show()
    for mode, _label in MODES:
        view.set_mode(mode)
        assert view.mode() == mode
        view.set_picture(ramp())
        assert view.has_picture()
        image = view.grab().toImage()
        assert image.width() == 400 and image.height() == 190
        colours = {image.pixel(x, y) for x in range(30, 394, 2) for y in range(6, 184, 2)}
        assert len(colours) > 8, (mode, len(colours))
    view.set_picture(None)
    assert not view.has_picture()


def test_the_zone_map_colours_the_brightness_in_eleven_zones():
    r = ramp(10, 256)
    z = S.zones(r)
    assert z.shape == (10, 256) and z.min() == 0 and z.max() == S.ZONE_COUNT - 1
    assert [int(z[0, v]) for v in (0, 23, 24, 127, 128, 255)] == [0, 0, 1, 5, 5, 10]
    overlay = S.zone_overlay(r)
    assert overlay.shape == (10, 256, 4) and overlay.dtype == np.uint8 and (overlay[..., 3] == 255).all()
    assert tuple(overlay[0, 128, :3]) == S.ZONE_COLORS[5] and tuple(overlay[0, 255, :3]) == S.ZONE_COLORS[10]
    shares = S.zone_shares(r)
    assert len(shares) == 11 and abs(sum(shares) - 1.0) < 1e-9 and all(0.08 < s < 0.1 for s in shares[:10])


_WINDOW = r'''
import os, sys, tempfile, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
work = tempfile.mkdtemp()
import numpy as np, cv2
from PyQt6.QtWidgets import QApplication
from photoeditor.features.settings import logic as S
S.save({"scan_quality": False})
p1 = os.path.join(work, "a.png")
cv2.imwrite(p1, np.tile(np.linspace(0, 255, 300, dtype=np.uint8)[None, :, None], (200, 1, 3)))
app = QApplication([])
from photoeditor.desktop.view import app_window as aw
win = aw.AppWindow(); win.show(); win.resize(1500, 900); win.open_folder(work, prefer=p1)
def pump(s):
    end = time.time() + s
    while time.time() < end:
        app.processEvents(); time.sleep(0.01)
pump(1.5)
assert win._histogram_panel.isVisible() and win._scope_view.isHidden()
for index, mode in ((1, "waveform"), (2, "parade"), (3, "vector")):
    win._graph_choice.setCurrentIndex(index); pump(0.3)
    assert win._histogram_panel.isHidden() and win._scope_view.isVisible() and win._scope_view.mode() == mode and win._scope_view.has_picture(), mode
win._graph_choice.setCurrentIndex(0); pump(0.2)
assert win._histogram_panel.isVisible() and win._scope_view.isHidden()
win._graph_choice.setCurrentIndex(1); pump(0.2)
c = win.controller
c.set_exposure(0.8) if hasattr(c, "set_exposure") else None
pump(0.8)
assert win._scope_view.has_picture(), "it follows the picture"
win._zones_btn.setChecked(True); pump(0.5)
assert win._image_view._label._zone is not None and "VIII" in win._zones_btn.toolTip()
win._zones_btn.setChecked(False); pump(0.3)
assert win._image_view._label._zone is None
print("ok")
'''


def test_the_graph_choice_and_the_zone_map_in_the_window():
    import subprocess
    import sys
    from pathlib import Path
    src = str(Path(__file__).resolve().parents[1] / "src")
    env = dict(os.environ, PYTHONPATH=src + os.pathsep + os.environ.get("PYTHONPATH", ""))
    r = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _WINDOW], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "ok" in r.stdout, r.stdout[-2000:] + r.stderr[-3000:]
