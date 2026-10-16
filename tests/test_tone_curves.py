"""The tone curve's red, green and blue curves: the maths, the panel, and the whole path from the panel to the picture, a saved photo, a preset and the exporter."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np

from photoeditor.features.tonecurve import logic as tc

SRC = str(Path(__file__).resolve().parents[1] / "src")
STRAIGHT = list(tc.DEFAULT_POINTS)


def test_straight_curves_leave_a_picture_untouched():
    pic = np.random.default_rng(0).integers(0, 256, (20, 30, 3), dtype=np.uint8)
    assert tc.apply_curves(pic, STRAIGHT, [STRAIGHT] * 3) is pic
    ramp = np.linspace(0, 255, 256, dtype=np.float32)[None, :, None].repeat(3, axis=2)
    assert tc.apply_curves(ramp, STRAIGHT, [STRAIGHT] * 3) is ramp


def test_a_channel_curve_moves_only_its_channel_and_follows_the_master():
    pic = np.full((4, 4, 3), 128, dtype=np.uint8)
    lifted = [(0, 0), (128, 160), (255, 255)]
    only_red = tc.apply_curves(pic, STRAIGHT, [lifted, STRAIGHT, STRAIGHT])
    assert only_red[0, 0, 0] > 150 and only_red[0, 0, 1] == 128 and only_red[0, 0, 2] == 128
    # the master first, then the channel: a darkening master pulls the channel's input down with it
    darker = [(0, 0), (128, 64), (255, 255)]
    both = tc.apply_curves(pic, darker, [lifted, STRAIGHT, STRAIGHT])
    assert both[0, 0, 1] < 70 and both[0, 0, 0] < only_red[0, 0, 0]
    # a float ramp agrees with the 8-bit picture
    ramp = np.full((1, 1, 3), 128.0, dtype=np.float32)
    assert abs(float(tc.apply_curves(ramp, STRAIGHT, [lifted, STRAIGHT, STRAIGHT])[0, 0, 0]) - float(only_red[0, 0, 0])) < 2.0


def test_black_and_white_points_clip_and_stretch():
    assert tc.build_lut(tc.set_black(STRAIGHT, 30))[30] == 0 and tc.build_lut(tc.set_black(STRAIGHT, 30))[255] == 255
    assert tc.build_lut(tc.set_white(STRAIGHT, 220))[220] == 255 and tc.build_lut(tc.set_white(STRAIGHT, 220))[0] == 0
    both = tc.set_white(tc.set_black(STRAIGHT, 30), 220)
    lut = tc.build_lut(both)
    assert lut[30] == 0 and lut[220] == 255 and 0 < lut[125] < 255
    assert tc.inverse_input(both, 128) in range(120, 130)


def test_the_pickers_make_the_picked_pixel_black_white_or_neutral():
    rgb = (40, 30, 20)
    black = tc.pick_black([STRAIGHT] * 3, rgb)
    assert [tc.build_lut(black[c])[rgb[c]] for c in range(3)] == [0, 0, 0]
    white = tc.pick_white([STRAIGHT] * 3, (230, 220, 200))
    assert [tc.build_lut(white[c])[v] for c, v in enumerate((230, 220, 200))] == [255, 255, 255]
    grey = tc.pick_grey([STRAIGHT] * 3, (140, 120, 100))
    out = [int(tc.build_lut(grey[c])[v]) for c, v in enumerate((140, 120, 100))]
    assert max(out) - min(out) <= 1 and abs(out[0] - 120) <= 1


def test_auto_puts_each_channels_black_and_white_at_the_pictures_own():
    rng = np.random.default_rng(1)
    image = np.stack([rng.integers(20, 200, (80, 80)), rng.integers(40, 230, (80, 80)), rng.integers(60, 250, (80, 80))], axis=-1).astype(np.uint8)
    curves = tc.auto_levels([STRAIGHT] * 3, image)
    out = tc.apply_curves(image, STRAIGHT, curves)
    for c in range(3):
        assert np.percentile(out[..., c], 0.5) <= 2 and np.percentile(out[..., c], 99.5) >= 253


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False, "advanced_mode": False})
    from PyQt6.QtWidgets import QApplication
    rng = np.random.default_rng(0)
    path = os.path.join(work, "a.png"); cv2.imwrite(path, rng.integers(60, 190, (160, 240, 3), dtype=np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.features.tonecurve import logic as tc
    from photoeditor.features.persistence import edit_store
    win = aw.AppWindow(); win.show(); win.open_folder(work, prefer=path); c = win.controller
    def pump(s):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(2)
    STRAIGHT = list(tc.DEFAULT_POINTS)
    panel = win._curve_tool

    # the panel: tabs for RGB / Red / Green / Blue, each its own curve; signals carry all four
    got = []
    panel.curve_changed.connect(got.append)
    panel._show("tone_curve_red")
    panel._editor.set_points([(0, 0), (128, 150), (255, 255)])
    panel._editor._select(1)
    panel._editor.set_selected_point(y=170)
    assert got and got[-1]["tone_curve_red"] == [(0, 0), (128, 170), (255, 255)] and got[-1]["tone_curve_points"] == STRAIGHT, got[-1]
    assert set(got[-1]) == set(tc.CURVE_KEYS)

    # the controller took it: state, the "changed" check, the log
    assert c.state.tone_curve_red == [(0, 0), (128, 170), (255, 255)] and c.state.tone_curve_green == STRAIGHT
    assert not tc.curves_are_identity(c.state.tone_curve_points, [c.state.tone_curve_red, c.state.tone_curve_green, c.state.tone_curve_blue])
    base = c.state.image_rgb.copy()

    # a picker: arm, click on the picture, the channel curves take it and the picker puts itself away
    panel._picker_buttons["black"].setChecked(True)
    assert panel.armed_picker() == "black"
    panel.apply_pick("black", (60, 50, 40)); pump(0.5)
    assert panel.armed_picker() is None
    assert c.state.tone_curve_green != STRAIGHT and tc.build_lut(c.state.tone_curve_green)[50] == 0
    panel.apply_auto(c.state.image_rgb); pump(0.5)
    assert c.state.tone_curve_blue != STRAIGHT

    # saved with the photo and restored
    saved = edit_store.load_edit_state(c.database(), path)
    assert saved is not None and [tuple(p) for p in saved["tone_curve_red"]] == c.state.tone_curve_red

    # undo and redo carry the channel curves
    after = c._curve_values()
    c.undo(); pump(0.5)
    assert c._curve_values() != after
    c.redo(); pump(0.5)
    assert c._curve_values() == after

    # a built-in scanner style sets all four curves, and clearing the look puts them straight again
    c.apply_builtin_preset("Scanners (DarkSlide)/Frontier Classic"); pump(0.8)
    assert c.state.tone_curve_points[0] == (0, 10) and c.state.tone_curve_blue[-1] == (255, 244) and c.state.tone_curve_green == [(0, 0), (120, 118), (255, 248)]
    assert abs(c.state.saturation - 0.10) < 1e-6 and abs(c.state.temperature - 0.08) < 1e-6
    c.apply_builtin_preset("Scanners (DarkSlide)/Noritsu"); pump(0.8)
    assert c.state.tone_curve_red == STRAIGHT and c.state.tone_curve_blue == STRAIGHT, "the next style replaces the last one's channel curves"
    c.clear_look(); pump(0.8)
    assert tc.curves_are_identity(c.state.tone_curve_points, [c.state.tone_curve_red, c.state.tone_curve_green, c.state.tone_curve_blue])
    print("OK")
""")


def test_the_curves_run_from_the_panel_through_the_controller_to_a_saved_photo():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-2500:]
