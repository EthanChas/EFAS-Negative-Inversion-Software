"""Color Toning: a hue and a strength for the shadows, the midtones and the highlights, added in OKLab after the mixer."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np

from photoeditor.features.colormix import logic as cm

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _ramp():
    grey = np.repeat(np.linspace(8, 247, 240, dtype=np.uint8)[None, :], 20, axis=0)
    return np.repeat(grey[..., None], 3, axis=2)


def _lab(img):
    return cm.srgb8_to_oklab(img)


def test_nothing_is_done_until_a_region_has_a_strength():
    px = _ramp()
    assert cm.apply_color(px, cm.DEFAULTS, "none", 1.0) is px
    assert cm.apply_color(px, {"tone_hue_shadows": 200.0}, "none", 1.0) is px, "a hue alone changes nothing"
    assert cm.is_neutral({"tone_hue_mids": 90.0}) and not cm.is_neutral({"tone_amt_mids": 0.2})
    assert cm.toning_active({"tone_amt_highs": 0.1}) and not cm.toning_active({})


def test_each_region_tints_its_own_tones_toward_its_hue_and_keeps_the_lightness():
    px = _ramp()
    before = _lab(px)
    for region, columns in (("shadows", slice(0, 40)), ("mids", slice(100, 140)), ("highs", slice(200, 240))):
        others = [r for r in cm.REGIONS if r != region]
        out = cm.apply_color(px, {f"tone_hue_{region}": 90.0, f"tone_amt_{region}": 1.0}, "none", 1.0)   # 90 degrees is toward yellow (+b)
        after = _lab(out)
        assert after[:, columns, 2].mean() > 0.04, (region, after[:, columns, 2].mean())
        assert abs(after[:, columns, 0] - before[:, columns, 0]).max() < 0.03, "the tint keeps the lightness"
        far = slice(0, 40) if region == "highs" else slice(200, 240)
        assert abs(after[:, far, 2]).mean() < 0.015, f"{region} does not reach the {others} tones"


def test_the_hue_sets_the_direction_and_the_strength_the_size():
    px = _ramp()
    cyan = _lab(cm.apply_color(px, {"tone_hue_mids": 190.0, "tone_amt_mids": 1.0}, "none", 1.0))[:, 100:140]
    red = _lab(cm.apply_color(px, {"tone_hue_mids": 0.0, "tone_amt_mids": 1.0}, "none", 1.0))[:, 100:140]
    assert cyan[..., 1].mean() < -0.03 and red[..., 1].mean() > 0.03
    half = _lab(cm.apply_color(px, {"tone_hue_mids": 0.0, "tone_amt_mids": 0.5}, "none", 1.0))[:, 100:140]
    assert 0.3 * red[..., 1].mean() < half[..., 1].mean() < 0.7 * red[..., 1].mean()
    r, g, b = cm.tint_swatch(0.0)
    assert r > b and r > g, "the swatch for 0 degrees is a red-magenta"


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    from PyQt6.QtWidgets import QApplication
    rng = np.random.default_rng(0)
    p = os.path.join(work, "a.png"); cv2.imwrite(p, rng.integers(60, 190, (200, 300, 3), dtype=np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.features.persistence import edit_store
    win = aw.AppWindow(); win.show(); win.open_folder(work, prefer=p); c = win.controller
    def pump(s):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(2)
    tool, mixer = win._color_toning_tool, win._color_mixer_tool
    steps = len(c.state.history)
    before = c.state.image_rgb.copy()

    # the panel's sliders reach the state, per region, and the mixer does not undo them
    for key, value in (("tone_hue_shadows", 220.0), ("tone_amt_shadows", 0.6), ("tone_hue_highs", 60.0), ("tone_amt_highs", 0.4)):
        tool._on_value(key, value)
    pump(1.2)
    assert c.state.tone_hue_shadows == 220.0 and abs(c.state.tone_amt_shadows - 0.6) < 1e-6 and c.state.tone_amt_mids == 0.0, c._toning_values()
    assert any("Color toning" in h.description for h in c.state.history[steps:]), [h.description for h in c.state.history[steps:]]
    assert not np.array_equal(before, c.state.image_rgb), "the picture changed"
    mixer._vibrance.set_value(0.3); mixer._on_vibrance(0.3); pump(1.0)
    assert abs(c.state.vibrance - 0.3) < 1e-6 and abs(c.state.tone_amt_shadows - 0.6) < 1e-6, "the mixer leaves the toning alone"
    tool._on_value("tone_amt_mids", 0.2); pump(1.0)
    assert abs(c.state.vibrance - 0.3) < 1e-6 and abs(c.state.tone_amt_mids - 0.2) < 1e-6, "and the toning leaves the mixer alone"

    # saved with the photo, undo and redo bring the panel back
    c._save_edit_state()
    saved = edit_store.load_edit_state(c._db, p)
    assert saved["tone_hue_shadows"] == 220.0 and abs(saved["tone_amt_highs"] - 0.4) < 1e-6
    c.undo(); pump(0.6)
    assert c.state.tone_amt_mids == 0.0 and tool._amount["mids"].value() == 0.0, "undo takes the panel back"
    c.redo(); pump(0.6)
    assert abs(tool._amount["mids"].value() - 0.2) < 1e-6

    # switching the module off makes the picture as if it were untouched, the settings kept
    toned = c.state.image_rgb.copy()
    c.set_module_enabled("colortoning", False); pump(1.0)
    assert not np.array_equal(toned, c.state.image_rgb) and abs(c.state.tone_amt_shadows - 0.6) < 1e-6, "off: a different picture, the settings kept"
    c.set_module_enabled("colortoning", True); pump(1.0)
    assert np.array_equal(toned, c.state.image_rgb), "on again: the same picture"

    # a look carries it, and Clear resets it
    c.apply_look({"tone_hue_mids": 300.0, "tone_amt_mids": 0.5}, "a look"); pump(0.8)
    assert c.state.tone_hue_mids == 300.0 and abs(tool._amount["mids"].value() - 0.5) < 1e-6
    c.clear_look(); pump(1.0)
    assert all(v == 0.0 for v in c._toning_values().values()) and all(v == 0.0 for v in tool.values().values())
    print("OK")
""")


def test_the_toning_panel_controller_history_saving_and_looks_work_together():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-2500:]


def test_the_module_is_a_presets_module_with_an_icon_and_switches_off_cleanly():
    from photoeditor.desktop.view import panel_icons
    from photoeditor.features.lookpresets import modules as M
    from photoeditor.features.persistence import edit_store

    assert "colortoning" in M.PANEL_MODULES and "colortoning" in M.SWITCHABLE
    assert {f.key for f in M.panel_fields("colortoning")} == set(cm.TONING_KEYS) and len(cm.TONING_KEYS) == 6
    assert M.off_overrides(["colortoning"]) == {k: 0.0 for k in cm.TONING_KEYS}
    assert panel_icons.BY_TITLE["Color Toning"] == "droplets" and (panel_icons.ICON_DIR / "droplets.svg").is_file()
    assert set(cm.TONING_KEYS) <= {name for name, _kind in edit_store._FIELDS}
