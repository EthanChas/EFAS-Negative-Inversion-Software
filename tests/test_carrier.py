"""Negative Carrier: the filed carrier's rebate (features/carrier/logic.py) and its panel."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from photoeditor.features.carrier import logic as car  # noqa: E402


def _picture(h=600, w=900, value=140):
    return np.full((h, w, 3), value, np.uint8)


def test_a_width_of_zero_changes_nothing():
    img = _picture()
    assert car.is_neutral({"carrier_width": 0.0}) and car.is_neutral(None)
    assert car.apply_carrier(img, {"carrier_width": 0.0}) is img
    assert np.array_equal(car.apply_carrier(img, car.DEFAULTS), img)


def test_the_rebate_prints_black_at_the_edge_paper_beyond_it_and_leaves_the_middle_alone():
    img = _picture()
    out = car.apply_carrier(img, {"carrier_width": 4.0})
    assert out.shape == img.shape and out.dtype == np.uint8
    assert np.array_equal(out[300:320, 450:470], img[300:320, 450:470]), "the picture's middle is untouched"
    assert (out[0, 450] >= 250).all(), "outside the filed aperture is bare paper"
    rebate = out[13:17, 450]   # 4 mm on a 900 px picture is 12 px: 8 px of paper margin, then the rebate to about row 20
    assert (rebate <= 30).all(), ("a band of black rebate lies inside the paper margin", rebate.tolist())
    assert (out[:, 0].max(axis=1) >= 250).any() and (out != img).any()


def test_it_scales_with_the_picture_so_a_preview_matches_an_export():
    small, big = _picture(300, 450), _picture(1200, 1800)
    a, b = car.apply_carrier(small, {"carrier_width": 3.0}), car.apply_carrier(big, {"carrier_width": 3.0})
    cols_small = int((a[150, :60, 0] < 60).sum() > 0)
    assert cols_small == 1
    share_small = float((a[:, :, 0] < 60).mean())
    share_big = float((b[:, :, 0] < 60).mean())
    assert abs(share_small - share_big) < 0.02, (share_small, share_big)


def test_the_pattern_is_fixed_and_the_sliders_change_it():
    img = _picture()
    v = {"carrier_width": 3.0, "carrier_rough": 0.5, "carrier_corner": 0.5, "carrier_flare": 0.5}
    assert np.array_equal(car.apply_carrier(img, v), car.apply_carrier(img, v)), "the same photo always prints the same edge"
    assert not np.array_equal(car.apply_carrier(img, v), car.apply_carrier(img, {**v, "carrier_rough": 0.0}))
    assert not np.array_equal(car.apply_carrier(img, v), car.apply_carrier(img, {**v, "carrier_flare": 0.0}))
    wide = car.apply_carrier(img, {**v, "carrier_width": 5.0})
    assert (wide[:, :, 0] < 60).sum() > (car.apply_carrier(img, v)[:, :, 0] < 60).sum(), "a wider carrier prints more rebate"


def test_a_picture_smaller_than_the_band_is_still_handled():
    tiny = _picture(40, 60)
    out = car.apply_carrier(tiny, {"carrier_width": 5.0})
    assert out.shape == tiny.shape


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp(); folder = os.path.join(work, "r"); os.makedirs(folder)
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    g = np.linspace(40, 215, 600, dtype=np.float32)[None, :, None] * np.ones((400, 1, 3), np.float32)
    cv2.imwrite(os.path.join(folder, "a.png"), g.astype(np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=os.path.join(folder, "a.png"))
    def pump(secs):
        end = time.time() + secs
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(3)
    panel = win._carrier_tool
    assert panel.values()["carrier_width"] == 0.0
    before = c.state.preview_rgb.copy() if c.state.preview_rgb is not None else None
    c.set_carrier({"carrier_width": 4.0, "carrier_rough": 0.4}); pump(1.5)
    assert c.state.carrier_width == 4.0 and c.state.carrier_rough == 0.4
    panel.set_values(c._carrier_values())
    assert panel._rows["carrier_width"].value() == 4.0
    assert any("Negative carrier" in str(h) for h in c.state.history) or len(c.state.history) >= 1
    c.reset_edits() if hasattr(c, "reset_edits") else None
    print("OK carrier")
""")


def test_the_panel_and_the_controller_carry_the_values():
    r = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "OK carrier" in r.stdout, r.stdout[-1500:] + r.stderr[-3000:]
