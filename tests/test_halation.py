"""Halation: a simulated red-orange glow round the brightest parts - the logic, and the module in the window (saved with the photo, in presets, undoable, switchable)."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np

from photoeditor.features.halation import logic as H

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _picture():
    img = np.full((300, 400, 3), 60, np.uint8)
    img[130:170, 180:220] = 250   # a bright square in the middle of a dark picture
    return img


def test_amount_zero_leaves_the_picture_alone():
    img = _picture()
    assert H.apply_halation(img, {"hal_amount": 0.0}) is img and H.apply_halation(img, None) is img and H.is_neutral({}) and not H.is_neutral({"hal_amount": 0.2})


def test_the_glow_only_brightens_and_is_redder_than_the_light_that_made_it():
    img = _picture()
    out = H.apply_halation(img, {"hal_amount": 0.8, "hal_radius": 0.4, "hal_threshold": 0.7, "hal_warmth": 1.0}).astype(int)
    assert (out >= img.astype(int)).all(), "a glow is added light: nothing gets darker"
    ring = (slice(110, 190), slice(160, 240))
    gain = (out - img.astype(int))[ring]
    outside = np.ones((80, 80), bool); outside[20:60, 20:60] = False   # the ring round the square, not the square itself
    r, g, b = (gain[..., i][outside].mean() for i in range(3))
    assert r > 2 and r > g > b, (r, g, b)
    assert np.array_equal(out[:40, :40], img[:40, :40].astype(int)), "far from the highlight the picture is as it was"


def test_a_neutral_glow_is_the_same_colour_as_the_highlight_and_a_warm_one_is_not():
    img = _picture()
    neutral = H.apply_halation(img, {"hal_amount": 0.8, "hal_warmth": 0.0}).astype(int) - img.astype(int)
    assert abs(neutral[125, 200, 0] - neutral[125, 200, 2]) <= 1, "warmth 0: the same on every channel"
    warm = H.apply_halation(img, {"hal_amount": 0.8, "hal_warmth": 1.0}).astype(int) - img.astype(int)
    assert warm[125, 200, 0] > 2 * warm[125, 200, 2]


def test_amount_radius_and_threshold_do_what_they_say():
    img = _picture()
    def glow_at(values, y, x=200):
        return int((H.apply_halation(img, {"hal_warmth": 0.0, **values}).astype(int) - img.astype(int))[y, x, 1])
    base = {"hal_amount": 0.5, "hal_radius": 0.3, "hal_threshold": 0.7}
    assert glow_at({**base, "hal_amount": 0.9}, 120) > glow_at(base, 120) > 0, "more amount, more glow"
    assert glow_at({**base, "hal_radius": 0.9}, 105) > glow_at({**base, "hal_radius": 0.1}, 105), "a bigger radius reaches farther"
    assert glow_at({**base, "hal_threshold": 0.98}, 120) == 0, "nothing is bright enough to glow at a threshold above the picture's brightest"
    assert glow_at({**base, "hal_threshold": 0.3}, 120) > 0
    assert H.glow_sigma((1000, 2000), 1.0) > H.glow_sigma((1000, 2000), 0.0) >= 1.0
    assert H.glow_sigma((2000, 4000), 0.4) == 2 * H.glow_sigma((1000, 2000), 0.4), "the radius is a share of the picture: it scales with it"


def test_the_picture_keeps_its_shape_and_type_on_a_big_one():
    big = np.full((900, 1500, 3), 90, np.uint8); big[400:500, 700:800] = 255
    out = H.apply_halation(big, {"hal_amount": 0.5})
    assert out.shape == big.shape and out.dtype == np.uint8 and out[450, 750].min() >= 250


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp(); folder = os.path.join(work, "r"); os.makedirs(folder)
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.features.persistence import edit_store
    S.save({"scan_quality": False})
    img = np.full((600, 900, 3), 180, np.uint8); img[250:350, 400:500] = 5   # a negative: the dark square is the bright highlight once it is inverted
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
    s = c.state; tool = win._halation_tool
    before = s.image_rgb.copy()
    assert s.hal_amount == 0.0 and tool.values()["hal_amount"] == 0.0, "off until you turn it on"

    # the panel sets it, the picture changes, the history says so
    tool._rows["hal_amount"].set_value(0.7); tool._rows["hal_radius"].set_value(0.5); tool._rows["hal_threshold"].set_value(0.5); tool._on_value_changed(); tool._settle_timer.stop(); win.controller.set_halation(tool.values())
    assert pump(lambda: not np.array_equal(s.image_rgb, before)), "the glow is drawn"
    assert s.hal_amount == 0.7 and "Halation" in s.history[-1].description, s.history[-1].description
    glow = s.image_rgb.astype(int)[240, 450] - before.astype(int)[240, 450]
    assert glow[0] > glow[2] > 0, glow   # beside the square: redder than blue, both lifted (BGR order for a png read: index 0 is red after conversion)

    # saved with the photo, and in the look a preset holds
    c._save_edit_state()
    saved = edit_store.load_edit_state(c._db, path)
    assert saved["hal_amount"] == 0.7 and saved["hal_radius"] == 0.5
    look = c.current_look()
    assert look["hal_amount"] == 0.7 and "hal_warmth" in look
    assert c.save_look_preset("Glowy") and c.look_preset("Glowy")["hal_amount"] == 0.7

    # undo, redo-able reset, the module's on/off light, reset to defaults
    on = s.image_rgb.copy()
    c.undo(); app.processEvents()
    assert s.hal_amount == 0.0 and tool.values()["hal_amount"] == 0.0 and pump(lambda: np.array_equal(s.image_rgb, before)), "undo takes the glow off and the panel follows"
    assert c.apply_look_preset("Glowy") and pump(lambda: s.hal_amount == 0.7)
    assert pump(lambda: not np.array_equal(s.image_rgb, before))
    c.set_module_enabled("halation", False)
    assert pump(lambda: np.array_equal(s.image_rgb, before)), "switched off: the picture is made as if the module were untouched"
    c.set_module_enabled("halation", True)
    assert pump(lambda: not np.array_equal(s.image_rgb, before))
    assert c.reset_module("halation") and s.hal_amount == 0.0
    assert pump(lambda: np.array_equal(s.image_rgb, before))
    win.close()
    print("HALATION OK")
""")


def test_halation_in_the_window():
    done = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC, "PHOTOEDITOR_AUDIO": "off"})
    assert "HALATION OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3000:]
