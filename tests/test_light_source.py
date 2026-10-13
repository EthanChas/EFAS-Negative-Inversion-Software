"""Scanning-light presets (Negative > Color trim) and the flat-field map ignoring dust on the reference."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

from photoeditor.features.flatfield import logic as ff
from photoeditor.features.negative import lightsource as ls

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_a_warmer_black_body_has_more_red_and_less_blue():
    cold, mid, warm = ls.blackbody_rgb(8000), ls.blackbody_rgb(5500), ls.blackbody_rgb(3000)
    assert warm[0] > mid[0] > cold[0] and warm[2] < mid[2] < cold[2]
    assert all(c[1] == 1.0 for c in (cold, mid, warm))
    # the daylight point is close to neutral on sRGB primaries, and 3000 K is clearly orange
    assert 0.9 < mid[0] < 1.3 and 0.7 < mid[2] < 1.15 and warm[0] / warm[2] > 1.8


def test_trim_for_daylight_is_zero_and_goes_the_right_way():
    assert ls.trim_for(5500) == (0.0, 0.0, 0.0)
    warm, cool = ls.trim_for(3000), ls.trim_for(7500)
    assert warm[0] > 0 > warm[2] and cool[0] < 0 < cool[2], "a warm light is corrected by adding red and taking away blue"
    assert warm[1] == 0.0 and cool[1] == 0.0
    assert all(-1.0 <= v <= 1.0 for v in warm + cool)
    assert ls.trim_for(2000)[0] >= warm[0] and ls.trim_for(100) == ls.trim_for(2000) and ls.trim_for(99999) == ls.trim_for(12000), "outside the range it is held at the ends"
    # the further from the reference, the bigger the trim
    assert ls.trim_for(4000)[0] < ls.trim_for(3200)[0] < ls.trim_for(2600)[0]


def test_every_preset_has_a_name_a_temperature_and_a_note_and_resolves():
    names = [p[0] for p in ls.PRESETS]
    assert len(names) == len(set(names)) >= 4
    for name, kelvin, note in ls.PRESETS:
        assert ls.MIN_KELVIN <= kelvin <= ls.MAX_KELVIN and note
        assert ls.preset_trim(name) == ls.trim_for(kelvin)
    assert ls.preset_trim("nothing") is None
    assert not any("CS-LITE" in n for n in names), "no invented numbers for a light that has no published temperature"


def test_dust_on_the_flat_field_reference_does_not_become_a_spot_in_the_gain_map():
    h, w = 512, 768
    yy, xx = np.mgrid[0:h, 0:w]
    falloff = 1.0 - 0.25 * (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    clean = np.clip(falloff[..., None] * np.array([200, 205, 195]) , 0, 255).astype(np.uint8)
    dusty = clean.copy()
    for cy, cx in ((100, 150), (300, 400), (420, 650)):
        dusty[cy:cy + 6, cx:cx + 6] = 20   # specks of dust: dark, a few pixels across
    gain_clean, gain_dusty = ff.compute_gain(clean), ff.compute_gain(dusty)
    assert gain_dusty.shape == gain_clean.shape
    assert np.abs(gain_dusty - gain_clean).max() < 0.02, "specks leave the map as it was"
    assert gain_clean[gain_clean.shape[0] // 2, gain_clean.shape[1] // 2].mean() < gain_clean[2, 2].mean(), "the real falloff is still corrected"


_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.features.negative import lightsource as ls
    S.save({"scan_quality": False})
    p = os.path.join(work, "a.png")
    cv2.imwrite(p, np.random.default_rng(0).integers(60, 200, (200, 300, 3), dtype=np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.show(); win.open_folder(work, prefer=p)
    c = win.controller
    def pump(s):
        end = time.time() + s
        while time.time() < end:
            app.processEvents(); time.sleep(0.01)
    pump(1.5)
    tool = win._negative_tool
    labels = [a.text() for a in tool._light_menu.actions() if a.text()]
    assert len(labels) == len(ls.PRESETS) + 2 and labels[-1].startswith("No correction"), labels
    steps = len(c.state.history)
    warm = [a for a in tool._light_menu.actions() if a.text().startswith("Warm white")][0]
    warm.trigger(); pump(0.8)
    r, g, b = ls.trim_for(3000)
    s = c.state
    assert (round(s.invert_r, 3), s.invert_g, round(s.invert_b, 3)) == (r, g, b) and r > 0 > b
    assert abs(tool._red.value() - r) < 0.006 and abs(tool._blue.value() - b) < 0.006, "the sliders show it"
    assert "Warm white LED" in win._coord_label.text() and len(c.state.history) > steps, "one ordinary, undoable edit"
    c.undo() if hasattr(c, "undo") else None
    pump(0.6)
    [a for a in tool._light_menu.actions() if a.text().startswith("No correction")][0].trigger(); pump(0.6)
    assert (c.state.invert_r, c.state.invert_g, c.state.invert_b) == (0.0, 0.0, 0.0) and tool._red.value() == 0.0
    print("ok")
''')


def test_the_scanning_light_menu_puts_the_trim_on_the_open_photo():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    r = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=240)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-3000:]
