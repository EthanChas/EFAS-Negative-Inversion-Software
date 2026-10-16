"""Lab Look: Fade, Glow and the colour balance by tone - the maths, the saved state, the preset fields and the window."""
import dataclasses
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np

from photoeditor.features.lablook import logic as ll

SRC = str(Path(__file__).resolve().parents[1] / "src")
ZERO = (0.0, 0.0, 0.0)


def ramp():
    return np.repeat(np.arange(256, dtype=np.uint8)[None, :, None], 3, axis=2)


def curve(fade=0.0, glow=0.0, by=ZERO, gm=ZERO):
    return ll.apply_lab_tone(ramp(), fade, by, gm, glow).astype(int)[0, :, 0] - np.arange(256)


def test_neutral_values_change_nothing():
    r = ramp()
    assert ll.apply_lab_tone(r, 0.0, ZERO, ZERO, 0.0) is r and ll.is_neutral(ll.DEFAULTS) and ll.is_neutral((0,) * 8)


def test_a_positive_fade_lifts_the_black_into_a_matte_grey_and_leaves_the_rest():
    d = curve(fade=1.0)
    assert 45 <= d[0] <= 55, "the black rises to about a fifth of the range at +1 (the original's +50)"
    assert d[255] == 0 and abs(d[128]) <= 2 and d[10] > d[60] > d[110] >= 0, "the lift dies away with brightness; the middle and the top stay"
    assert np.all(np.diff(np.arange(256) + d) >= 0), "tones never reverse"
    assert curve(fade=0.5)[0] < d[0] and abs(curve(fade=0.5)[0] - d[0] / 2) < 6, "half the slider, about half the lift"
    out = ll.apply_lab_tone(ramp(), 1.0, ZERO, ZERO)
    assert out[0, 0, 0] == out[0, 0, 1] == out[0, 0, 2], "fade is neutral"


def test_a_negative_fade_deepens_the_darkest_tones_and_brightens_the_lower_midtones():
    d = curve(fade=-1.0)
    assert d[0] == 0 and d[18] < -4, "the darkest tones sink (the black stays pure black)"
    assert 24 <= d[86] <= 40 and 28 <= d[118] <= 42, "the lower midtones rise by about an eighth of the range at -1 (the original's -50)"
    assert 18 <= d[200] <= 32 and d[100] > d[220] >= 0, "the lift eases off toward the top"
    assert np.all(np.diff(np.arange(256) + d) >= -1), "tones never reverse (to within a level)"
    assert abs(curve(fade=-0.5)[118]) < abs(d[118]) and abs(curve(fade=-0.5)[118]) > 10


def test_glow_lifts_or_drops_the_midtones_with_the_black_and_the_top_held():
    up, down = curve(glow=1.0), curve(glow=-1.0)
    assert up[0] == 0 and abs(up[255]) <= 1 and abs(down[255]) <= 1 and down[0] == 0, "the black and the top stay"
    assert 20 <= up[100] <= 30 and -30 <= down[100] <= -20, "about a tenth of the range at +/-1 (the original's +/-50)"
    assert abs(up[20]) < 6 and abs(up[230]) < 5, "the shadows and the highlights are left alone"
    assert np.all(np.abs(down + up) <= 1), "minus is the mirror of plus"
    assert np.all(np.diff(np.arange(256) + up) >= 0) and np.all(np.diff(np.arange(256) + down) >= 0), "tones never reverse"
    assert abs(curve(glow=0.5)[100]) < up[100] and abs(curve(glow=0.5)[100] - up[100] / 2) < 4


def test_both_sliders_run_from_minus_to_plus():
    assert ll.FADE_RANGE == (-1.0, 1.0) and ll.GLOW_RANGE == (-1.0, 1.0)
    from photoeditor.features.lookpresets import lookconvert
    from photoeditor.features.lookpresets import modules as M

    spec = {f.key: f for f in M.panel_fields("lablook")}
    assert (spec["lab_fade"].low, spec["lab_fade"].high) == (-1.0, 1.0) and (spec["lab_glow"].low, spec["lab_glow"].high) == (-1.0, 1.0)
    out = lookconvert.convert({"LabGlow": -50, "LabFade": 50})
    assert out["lab_glow"] == -1.0 and out["lab_fade"] == 1.0, "the original's -50 to +50 is -1 to +1 here"


def test_balance_by_tone_warms_only_the_range_asked_for():
    base = ramp()[0].astype(int)
    r = ll.apply_lab_tone(ramp(), 0.0, (0.5, 0.0, 0.0), ZERO).astype(int)[0] - base
    assert r[20, 0] > 5 and r[20, 2] < -5 and abs(r[240, 0]) <= 1 and abs(r[240, 2]) <= 1, "warm shadows, highlights untouched"
    cool = ll.apply_lab_tone(ramp(), 0.0, (0.0, 0.0, -0.5), ZERO).astype(int)[0] - base
    assert cool[240, 2] > 5 and abs(cool[15, 0]) <= 1, "cool highlights only"
    mids = ll.apply_lab_tone(ramp(), 0.0, (0.0, 0.5, 0.0), ZERO).astype(int)[0] - base
    assert mids[128, 0] > 5 and abs(mids[5, 0]) <= 2 and abs(mids[250, 0]) <= 2
    green = ll.apply_lab_tone(ramp(), 0.0, ZERO, (-0.5, 0.0, 0.0)).astype(int)[0] - base
    assert green[20, 1] > 5, "toward green in the shadows"
    s, m, h = ll.tone_weights(np.linspace(0, 1, 101))
    assert np.all(s >= 0) and np.all(m >= 0) and np.all(h >= 0) and np.all(s + m + h <= 1.0001) and s[0] == 1 and h[-1] == 1 and m[50] > 0.5


def test_float_ramps_stay_float_and_in_range():
    wide = np.repeat(np.linspace(0, 255, 65536, dtype=np.float32)[None, :, None], 3, axis=2)
    out = ll.apply_lab_tone(wide, 0.3, (0.4, 0.0, -0.4), (0.0, 0.2, 0.0), -0.6)
    assert out.dtype == np.float32 and out.min() >= 0 and out.max() <= 255


def test_the_module_is_in_the_presets_and_can_be_switched_off():
    from photoeditor.features.lookpresets import modules as M

    assert "lablook" in M.PANEL_MODULES and "lablook" in M.SWITCHABLE
    keys = {f.key for f in M.panel_fields("lablook")}
    assert keys == set(ll.ALL_KEYS) and set(M.panel_defaults("lablook")) == set(ll.ALL_KEYS)
    assert M.off_overrides(["lablook"]) == ll.ALL_DEFAULTS, "switched off, the scanner colour is none and its amount is back at full for the next time"


def test_the_renderer_applies_it_in_every_path_and_keeps_the_16_bit_chain():
    from photoeditor.desktop.render import EditParams, Renderer
    from photoeditor.desktop.session import AppState

    rng = np.random.default_rng(2)
    base = dataclasses.replace(EditParams.from_state(AppState()), negative_inverted=False)
    scan16 = (rng.random((40, 60, 3)) * 50000 + 5000).astype(np.uint16)
    scan8 = (scan16 // 257).astype(np.uint8)

    def render(scan, **kw):
        return Renderer().render(scan, dataclasses.replace(base, **kw), "t", scan.shape[1])[0].astype(int)

    for scan in (scan16, scan8):
        plain = render(scan)
        assert render(scan, lab_fade=0.6).min() > plain.min() + 15, "fade lifts the darkest pixels"
        assert render(scan, lab_fade=-0.8).mean() > plain.mean() + 5, "a negative fade brightens the lower midtones"
        warm = render(scan, lab_by_mids=0.6, lab_by_shadows=0.6)
        assert warm[..., 0].mean() > plain[..., 0].mean() + 3 and warm[..., 2].mean() < plain[..., 2].mean() - 3
        assert render(scan, lab_glow=1.0).mean() > plain.mean() + 5 and render(scan, lab_glow=-1.0).mean() < plain.mean() - 5
    deep = Renderer().render(scan16, dataclasses.replace(base, lab_fade=0.4, lab_glow=0.5), "t", 60, deep=True)[0]
    assert deep.dtype == np.uint16 and deep.min() > 3000, "fade and glow keep the 16-bit chain"


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    from PyQt6.QtWidgets import QApplication
    p = os.path.join(work, "a.png"); cv2.imwrite(p, np.random.default_rng(0).integers(30, 220, (200, 300, 3), dtype=np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.show(); win.open_folder(work, prefer=p); c = win.controller
    def pump(s):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(2)
    tool = win._lab_look_tool
    steps = len(c.state.history)
    tool._rows["lab_fade"].set_value(0.4); tool._rows["lab_by_shadows"].set_value(0.3)
    tool._on_value_changed(0); pump(1.2)
    assert abs(c.state.lab_fade - 0.4) < 1e-6 and abs(c.state.lab_by_shadows - 0.3) < 1e-6, "the sliders reach the state"
    assert len(c.state.history) == steps + 1 and "Lab look" in c.state.history[-1].description, c.state.history[-1].description
    assert c.state.image_rgb.min() > 20, "the faded black shows on the picture"
    tool._rows["lab_glow"].set_value(-0.5); tool._on_value_changed(0); pump(1.0)
    assert abs(c.state.lab_glow + 0.5) < 1e-6, "a negative value reaches the state"
    c._save_edit_state()
    c.undo(); c.undo(); pump(0.6)
    assert c.state.lab_fade == 0.0 and tool._rows["lab_fade"].value() == 0.0, "undo takes it back, panel included"
    c.redo(); pump(0.6)
    assert abs(c.state.lab_fade - 0.4) < 1e-6 and abs(tool._rows["lab_fade"].value() - 0.4) < 1e-6
    c.apply_look({"lab_fade": 0.2, "lab_glow": 0.3}, "test look"); pump(1.0)
    assert abs(c.state.lab_fade - 0.2) < 1e-6 and abs(c.state.lab_glow - 0.3) < 1e-6
    c.clear_look(); pump(1.0)
    assert c.state.lab_fade == 0.0 and c.state.lab_glow == 0.0, "Clear resets it with the other modules"
    print("OK")
""")


def test_the_panel_the_controller_history_and_presets_work_together():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=240, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-2500:]
