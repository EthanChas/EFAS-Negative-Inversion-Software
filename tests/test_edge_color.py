"""Edge Color: a tint, warmth and brightness correction that grows toward the picture's edges (a flash that lit the middle and left the edges to the room's light)."""
import dataclasses
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

from photoeditor.features.colormix import logic as cm
from photoeditor.features.edgecolor import logic as EC

SRC = str(Path(__file__).resolve().parents[1] / "src")
H, W = 600, 900


def _flash_falloff(tint=-0.045, warmth=0.01, light=-0.10, size=0.4, shape=0.3):
    """A grey picture whose edges have a green cast and are darker, as a flash that did not reach them leaves them."""
    lab = cm.srgb8_to_oklab(np.full((H, W, 3), 150, np.uint8))
    weight = EC.edge_weight(H, W, size, shape)
    lab[..., 0] += light * weight
    lab[..., 1] += tint * weight
    lab[..., 2] += warmth * weight
    return cm.oklab_to_srgb8(lab.astype(np.float32))


def _ring_vs_middle(img):
    ring, middle = EC._band_means(img)
    return ring - middle


def test_nothing_is_done_until_a_slider_moves():
    img = _flash_falloff()
    assert EC.is_neutral(EC.DEFAULTS) and not EC.is_neutral({"ec_tint": 0.2})
    assert EC.apply_edge_color(img, EC.DEFAULTS) is img
    assert EC.apply_edge_color(img, {"ec_size": 0.9, "ec_shape": 1.0}) is img, "size and shape alone change nothing"


def test_the_mask_is_zero_in_the_middle_one_at_the_edges_and_follows_the_shape():
    round_ = EC.edge_weight(H, W, 0.5, 0.0)
    assert round_.shape == (H, W) and round_.dtype == np.float32
    assert round_[H // 2, W // 2] == 0.0 and round_[H // 2, 5] > 0.99 and round_[3, W // 2] > 0.99 and round_[3, 3] > 0.99
    assert round_[H // 2, W // 4] < round_[H // 2, 5], "grows toward the edge"
    square = EC.edge_weight(H, W, 0.5, 1.0)
    assert square[3, W // 2] > 0.99 and square[3, W // 5] > 0.9, "an even band round the picture, corners and middles alike"
    assert round_[H // 8, W // 5] > square[H // 8, W // 5], "an ellipse reaches further into the corners than a rectangle's even band"
    big = EC.edge_weight(H, W, 0.9, 0.0)
    assert big[H // 2, W // 4] == 0.0 and big.mean() < round_.mean(), "a bigger Size leaves more of the middle alone"


def test_each_slider_moves_the_edges_the_way_it_says_and_leaves_the_middle_alone():
    img = np.full((H, W, 3), 140, np.uint8)
    middle = (slice(H // 3, 2 * H // 3), slice(W // 3, 2 * W // 3))

    def edge_lab(values):
        out = EC.apply_edge_color(img, values)
        assert np.array_equal(out[middle], img[middle]), "the middle is untouched"
        return cm.srgb8_to_oklab(out)[5:25, W // 3:2 * W // 3].mean(axis=(0, 1)) - cm.srgb8_to_oklab(img)[5:25, W // 3:2 * W // 3].mean(axis=(0, 1))

    magenta, green = edge_lab({"ec_tint": 1.0}), edge_lab({"ec_tint": -1.0})
    assert magenta[1] > 0.03 and green[1] < -0.03 and abs(magenta[2]) < 0.01
    yellow, blue = edge_lab({"ec_warmth": 1.0}), edge_lab({"ec_warmth": -1.0})
    assert yellow[2] > 0.03 and blue[2] < -0.03 and abs(yellow[1]) < 0.01
    brighter, darker = edge_lab({"ec_light": 1.0}), edge_lab({"ec_light": -1.0})
    assert brighter[0] > 0.08 and darker[0] < -0.08 and abs(brighter[1]) < 0.01


def test_auto_brings_a_green_edge_back_to_the_middle_and_leaves_the_brightness_to_you():
    img = _flash_falloff()
    before = _ring_vs_middle(img)
    assert before[1] < -0.02 and before[0] < -0.04, before
    values = {"ec_size": 0.4, "ec_shape": 0.3}
    first = EC.suggest(img, values)
    assert first["ec_tint"] > 0.5 and first["ec_light"] == 0.0, first
    fixed = EC.apply_edge_color(img, {**values, **first})
    after = _ring_vs_middle(fixed)
    assert abs(after[1]) < abs(before[1]) * 0.15 and abs(after[2]) < 0.01, (before, after)
    assert abs(after[0]) > abs(before[0]) * 0.8, "the edges are still as dark as they were: Light is not touched"
    second = EC.suggest(fixed, {**values, **first})
    refined = _ring_vs_middle(EC.apply_edge_color(img, {**values, **second}))
    assert abs(refined[1]) <= abs(after[1]) + 1e-3
    assert all(-1.0 <= v <= 1.0 for v in first.values())
    both = EC.suggest(img, values, light=True)
    matched = _ring_vs_middle(EC.apply_edge_color(img, {**values, **both}))
    assert both["ec_light"] > 0.4 and abs(matched[0]) < abs(before[0]) * 0.15 and abs(matched[1]) < abs(before[1]) * 0.15, "asking for the brightness too matches it as well"
    assert EC.band_difference(img)["tint"] < -0.5, "the difference is read in slider units"


def test_the_renderer_corrects_the_cropped_picture_s_edges():
    from photoeditor.desktop.render import EditParams, Renderer
    from photoeditor.desktop.session import AppState

    scan = np.full((800, 1200, 3), 150, np.uint8)
    crop = (150, 100, 1050, 700)   # 900 x 600
    lab = cm.srgb8_to_oklab(scan[100:700, 150:1050])
    weight = EC.edge_weight(600, 900, 0.4, 0.0)
    lab[..., 1] -= 0.05 * weight
    scan[100:700, 150:1050] = cm.oklab_to_srgb8(lab.astype(np.float32))
    base = dataclasses.replace(EditParams.from_state(AppState()), negative_inverted=False, crop_rect=crop)

    def render(**kw):
        return Renderer().render(scan, dataclasses.replace(base, **kw), "ec-test", scan.shape[1])[0]

    plain = render()
    assert plain.shape[:2] == (600, 900)
    values = {"ec_size": 0.4, "ec_shape": 0.0, **EC.suggest(plain, {"ec_size": 0.4})}
    fixed = render(**values)
    assert abs(_ring_vs_middle(fixed)[1]) < abs(_ring_vs_middle(plain)[1]) * 0.2
    assert np.array_equal(fixed[250:350, 400:500], plain[250:350, 400:500]), "the middle of the picture is as it was"
    assert np.array_equal(render(ec_size=0.9), plain), "no correction asked for, none made"


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False, "advanced_mode": False})
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.colormix import logic as cm
    from photoeditor.features.edgecolor import logic as EC
    from photoeditor.features.persistence import edit_store
    h, w = 400, 600
    lab = cm.srgb8_to_oklab(np.full((h, w, 3), 128, np.uint8))
    weight = EC.edge_weight(h, w, 0.4, 0.0)
    lab[..., 1] -= 0.05 * weight; lab[..., 0] -= 0.05 * weight
    scan = cm.oklab_to_srgb8(lab.astype(np.float32))
    p = os.path.join(work, "a.png"); cv2.imwrite(p, scan[..., ::-1])
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.show(); win.open_folder(work, prefer=p); c = win.controller
    def pump(s):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(2)
    c.set_film_type("c41"); c.set_negative_inverted(False); pump(1.2)   # colour, and shown as it is, so the test reads the colours it made
    tool = win._edge_color_tool
    assert tool._title == "Edge Color" and set(tool._rows) == set(EC.KEYS)
    assert [t._title for t in [win._color_tool, win._color_mixer_tool, win._color_toning_tool, win._lab_look_tool, win._edge_color_tool]][-1] == "Edge Color"

    # Auto: it reads the picture on screen and sets the three sliders
    image_before = c.state.image_rgb.copy()
    ring_before = EC._band_means(image_before)
    tool.auto_requested.emit(); pump(1.5)
    assert c.state.ec_tint != 0.0, c._ec_values()
    ring_after, middle_after = EC._band_means(c.state.image_rgb)
    assert not np.array_equal(image_before, c.state.image_rgb), "the picture changed"
    assert np.abs((ring_after - middle_after)[1:]).sum() < np.abs((ring_before[0] - ring_before[1])[1:]).sum() * 0.6, (ring_before, ring_after, middle_after)
    assert c.state.ec_light == 0.0, "Auto does not touch Light"
    assert tool._rows["ec_tint"].value() == c.state.ec_tint, "the panel shows what Auto set"
    assert any("Edge color" in h.description for h in c.state.history), [h.description for h in c.state.history[-3:]]

    # the sliders reach the state; saved with the photo; undo and redo bring the panel back
    tool._rows["ec_size"].set_value(0.6); tool._on_value_changed(); pump(1.0)
    assert abs(c.state.ec_size - 0.6) < 1e-6
    c._save_edit_state()
    saved = edit_store.load_edit_state(c._db, p)
    assert abs(saved["ec_size"] - 0.6) < 1e-6 and abs(saved["ec_tint"] - c.state.ec_tint) < 1e-6
    c.undo(); pump(0.6)
    assert abs(c.state.ec_size - 0.5) < 1e-6 and abs(tool._rows["ec_size"].value() - 0.5) < 1e-6, "undo takes the panel back"
    c.redo(); pump(0.6)
    assert abs(tool._rows["ec_size"].value() - 0.6) < 1e-6

    # the power light: off makes the picture without it, the settings kept
    on = c.state.image_rgb.copy()
    c.set_module_enabled("edgecolor", False); pump(1.0)
    assert not np.array_equal(on, c.state.image_rgb) and c.state.ec_tint != 0.0
    c.set_module_enabled("edgecolor", True); pump(1.0)
    assert np.array_equal(on, c.state.image_rgb)

    # a look carries it, Clear resets it
    c.apply_look({"ec_warmth": 0.4, "ec_shape": 1.0}, "a look"); pump(0.8)
    assert c.state.ec_warmth == 0.4 and tool._rows["ec_shape"].value() == 1.0
    c.clear_look(); pump(1.0)
    assert c._ec_values() == EC.DEFAULTS and tool.values() == EC.DEFAULTS, (c._ec_values(), tool.values())
    win.close()
    print("OK")
""")


def test_the_panel_auto_history_saving_and_looks_work_together():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-2500:]


def test_the_module_is_a_presets_module_with_an_icon_and_switches_off_cleanly():
    from photoeditor.desktop.view import panel_icons
    from photoeditor.features.lookpresets import modules as M
    from photoeditor.features.persistence import edit_store

    assert "edgecolor" in M.PANEL_MODULES and "edgecolor" in M.SWITCHABLE
    assert {f.key for f in M.panel_fields("edgecolor")} == set(EC.KEYS)
    assert M.off_overrides(["edgecolor"]) == dict(EC.DEFAULTS)
    assert panel_icons.BY_TITLE["Edge Color"] == "circle" and (panel_icons.ICON_DIR / "circle.svg").is_file()
    assert set(EC.KEYS) <= {name for name, _kind in edit_store._FIELDS}
    pytest.importorskip("PyQt6")
