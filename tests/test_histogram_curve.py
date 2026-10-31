"""The histogram's Curve view: the conversion's paper curve over the negative's density histogram (features/negative/curveview.py and the panel that draws it)."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from photoeditor.features.negative import curveview as cv  # noqa: E402
from photoeditor.features.negative import printengine as pe  # noqa: E402


def _ramp_lut(n=65536):
    x = np.linspace(0.0, 1.0, n, dtype=np.float32)
    return np.stack([x * 255.0] * 3)


def test_a_density_image_gives_the_curve_at_each_density_and_the_density_histogram():
    codes = np.zeros((40, 40, 3), np.uint16)
    codes[..., :] = int(1.0 * pe.DENSITY_SCALE)
    lut = np.zeros((3, 65536), np.float32)
    lut[:, : int(1.5 * pe.DENSITY_SCALE)] = 100.0
    lut[:, int(1.5 * pe.DENSITY_SCALE):] = 200.0
    data = cv.build(codes, lut, True, pe.DENSITY_SCALE)
    d = data["density"]
    assert d[0] == 0.0 and d[-1] == cv.D_MAX and data["curve"].shape == (3, cv.POINTS) and data["hist"].shape == (4, cv.BINS)
    assert data["curve"][0][np.searchsorted(d, 1.0)] == 100.0 and data["curve"][0][np.searchsorted(d, 2.0)] == 200.0, "the table's level at each density"
    peak = int(np.argmax(data["hist"][3]))
    assert abs((peak + 0.5) / cv.BINS * cv.D_MAX - 1.0) < 0.03, "every pixel is at density 1"
    assert abs(data["range"][0] - 1.0) < 0.01 and abs(data["range"][1] - 1.0) < 0.01


def test_a_scan_codes_table_is_read_by_the_density_of_the_light():
    codes = np.full((20, 20, 3), 6553, np.uint16)     # a tenth of the light: density 1
    data = cv.build(codes, _ramp_lut(), False, pe.DENSITY_SCALE)
    d = data["density"]
    i1 = int(np.searchsorted(d, 1.0))
    assert abs(float(data["curve"][1][i1]) - 25.5) < 1.5, "at density 1 the light is a tenth: level 25.5 on this straight table"
    assert float(data["curve"][1][0]) > 250 and float(data["curve"][1][-1]) < 1.0, "clear film is the most light, the densest the least"
    assert abs((int(np.argmax(data["hist"][3])) + 0.5) / cv.BINS * cv.D_MAX - 1.0) < 0.03


def test_nothing_to_draw_gives_none():
    assert cv.build(None, _ramp_lut(), True, 13000.0) is None
    assert cv.build(np.zeros((4, 4), np.uint16), _ramp_lut(), True, 13000.0) is None


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp(); folder = os.path.join(work, "r"); os.makedirs(folder)
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.features.negative.metering import Metering
    S.save({"scan_quality": False})
    assert S.DEFAULTS["histogram_curve"] is False
    g = np.linspace(40, 215, 600, dtype=np.float32)[None, :, None] * np.ones((400, 1, 3), np.float32)
    cv2.imwrite(os.path.join(folder, "a.png"), np.clip(g + np.random.default_rng(0).normal(0, 3, g.shape), 0, 255).astype(np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=os.path.join(folder, "a.png"))
    def pump(secs):
        end = time.time() + secs
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(3)
    panel = win._histogram_panel
    assert not hasattr(win, "_hist_density_btn") and not hasattr(panel, "set_density"), "the separate Density graph is gone"
    c.set_negative_inverted(True); pump(1.5)
    assert c.state.curve_view is not None and c.state.curve_view["curve"].shape[0] == 3
    for engine in ("print", "standard", "negpy056", "noritsu"):
        c.set_metering(Metering(engine=engine, transfer="srgb")); pump(1.0)
        data = c.state.curve_view
        assert data is not None and data["hist"].shape[0] == 4, engine
        assert panel._curve_data is data, "the panel is given the curve"
        assert float(data["curve"].max()) > float(data["curve"].min()), ("a curve that is not flat", engine)
    # the density curve shows the tone the picture really gets: Exposure and Contrast move it, not only the conversion's own table
    before = np.asarray(c.state.curve_view["curve"]).copy()
    c.set_exposure_ev(1.0); pump(2.0)
    after = np.asarray(c.state.curve_view["curve"])
    assert not np.allclose(before, after), "the density curve follows the Exposure module"
    c.set_exposure_ev(0.0); pump(1.5)
    win._hist_curve_btn.setChecked(True); pump(0.5)
    assert panel.curve_view() and S.load()["histogram_curve"] is True
    panel.resize(600, 260); pump(0.3)
    assert panel.grab() is not None
    plot = panel._plot_rect()
    assert panel.rect().right() - plot.right() >= 20, "room on the right for the density scale while the curve is on"
    panel.set_mode("color"); pump(0.2); panel.grab()
    panel.set_mode("exposure"); pump(0.2); panel.grab()
    panel._cursor_value = 128; panel.grab(); panel._cursor_value = None
    win._hist_curve_btn.setChecked(False); pump(0.3)
    assert not panel.curve_view()
    assert panel.rect().right() - panel._plot_rect().right() <= 14, "no gap on the right while it is off"
    panel.set_curve_view(True); panel.set_curve_data(None); panel.grab()      # no conversion: nothing is drawn, and nothing breaks
    print("OK histogram curve")
""")


def test_the_panel_draws_the_curve_view_for_every_conversion():
    r = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "OK histogram curve" in r.stdout, r.stdout[-1500:] + r.stderr[-3000:]
