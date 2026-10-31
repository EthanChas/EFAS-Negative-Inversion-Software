"""Edge Bleed: the four tools (holder and sprocket fill, bleed repair with an automatic strength, edge gradient dodge, border mask), through the renderer and the window."""
import dataclasses
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

from photoeditor.features.edgebleed import logic as E

SRC = str(Path(__file__).resolve().parents[1] / "src")
H, W, B = 600, 900, 70
BASE = np.array([0.80, 0.55, 0.30], dtype=np.float32)   # the clear film base, linear
SCENE = np.array([0.25, 0.20, 0.15], dtype=np.float32)


def _encode(lin: np.ndarray) -> np.ndarray:
    return np.clip(np.power(np.clip(lin, 0, 1), 1 / 2.2) * 255 + 0.5, 0, 255).astype(np.uint8)


def _frame_with_bleed(share: float, reach: float = 0.08, noise: float = 0.01) -> np.ndarray:
    """A scan: a flat grey picture inside clear film, with `share` of the border's light spread into the picture's edges."""
    lin = np.zeros((H, W, 3), dtype=np.float32)
    lin[:] = BASE
    rng = np.random.default_rng(0)
    lin[B:H - B, B:W - B] = SCENE + noise * rng.standard_normal((H - 2 * B, W - 2 * B, 3)).astype(np.float32)
    outside = np.ones((H, W), dtype=bool)
    outside[B:H - B, B:W - B] = False
    field = E._bleed_field(lin * outside[..., None], E._sigma(reach, H, W))
    lin[B:H - B, B:W - B] += share * field[B:H - B, B:W - B]
    return _encode(lin)


def _edge_ratio(img: np.ndarray) -> float:
    """How much brighter the picture's left edge is than its middle (linear)."""
    lin = np.power(img.astype(np.float32) / 255, 2.2)[B + 4:H - B - 4, B + 4:W - B - 4].mean(axis=2)
    return float(lin[:, :10].mean() / lin[200:400, 300:600].mean())


def test_nothing_is_done_until_a_tool_is_on():
    scan = _frame_with_bleed(0.1)
    assert E.is_neutral(E.DEFAULTS) and not E.scan_active(E.DEFAULTS) and not E.mask_active(E.DEFAULTS)
    assert E.correct_scan(scan, E.DEFAULTS) is scan
    img = np.full((50, 80, 3), 90, np.uint8)
    assert E.apply_edge_mask(img, 0.0, 0.5, "black") is img
    assert E.meter_inset(E.DEFAULTS) == 0.0 and E.meter_inset({"edge_mask": 0.05, "edge_mask_meter": True}) == 0.05 and E.meter_inset({"edge_mask": 0.05, "edge_mask_meter": False}) == 0.0


def test_the_estimate_finds_the_share_that_was_added_and_the_repair_takes_it_out():
    scan = _frame_with_bleed(0.12)
    assert E.find_frame(scan) is not None
    before = _edge_ratio(scan)
    assert before > 1.08, before
    strength = E.estimate_bleed(scan, 0.08)
    assert strength * E.BLEED_MAX == pytest.approx(0.12, abs=0.015), strength
    fixed = E.correct_scan(scan, {"edge_bleed": strength, "edge_reach": 0.08})
    assert fixed.dtype == np.uint8 and fixed.shape == scan.shape
    assert abs(_edge_ratio(fixed) - 1.0) < 0.02, (before, _edge_ratio(fixed))
    assert np.array_equal(fixed[:B - 5], scan[:B - 5]), "the clear border itself is left alone"
    assert E.estimate_bleed(_frame_with_bleed(0.0), 0.08) < 0.05, "a scan with no bleed is left alone"
    # 16 bits in, 16 bits out
    wide = E.correct_scan(scan.astype(np.uint16) * 257, {"edge_bleed": strength, "edge_reach": 0.08})
    assert wide.dtype == np.uint16 and abs(_edge_ratio((wide // 257).astype(np.uint8)) - 1.0) < 0.02


def test_no_clear_border_means_no_repair_but_the_dodge_still_works():
    plain = np.full((300, 400, 3), 120, np.uint8)
    assert E.find_frame(plain) is None and E.estimate_bleed(plain, 0.08) == 0.0
    assert E.correct_scan(plain, {"edge_bleed": 1.0, "edge_holder": 1.0}) is plain
    lift = plain.astype(np.float32)
    ramp = np.clip(np.linspace(1.35, 1.0, 40), 1.0, None)   # a bright edge on the left
    lift[:, :40] *= ramp[None, :, None]
    lifted = np.clip(lift, 0, 255).astype(np.uint8)
    dodged = E.correct_scan(lifted, {"edge_dodge": 1.0, "edge_reach": 0.1})
    assert abs(float(dodged[:, :5].mean()) - 120) < abs(float(lifted[:, :5].mean()) - 120) * 0.5, (lifted[:, :5].mean(), dodged[:, :5].mean())
    assert abs(float(dodged[:, 100:300].mean()) - 120) < 1.5, "the middle is left as it was"


def test_a_crop_is_the_picture_s_edge_and_a_dark_holder_gives_off_no_light():
    """Like a camera scan on a light table: a dark holder all round, the clear film base only beside the picture on one side (the sprocket strip)."""
    lin = np.full((H, W, 3), 0.02, dtype=np.float32)
    x1, y1, x2, y2 = 100, 80, 640, 520
    lin[y1:y2, x1:x2] = SCENE
    lin[y1:y2, x2 + 5:x2 + 60] = BASE                        # the clear strip with the sprocket holes' light
    outside = np.ones((H, W), dtype=bool)
    outside[y1:y2, x1:x2] = False
    sigma = E._sigma(0.08, H, W)
    lin[y1:y2, x1:x2] += 0.12 * E._bleed_field(E._light_source(lin, outside), sigma)[y1:y2, x1:x2]
    scan = _encode(lin)
    crop = (x1, y1, x2, y2)
    share = E.estimate_bleed(scan, 0.08, crop) * E.BLEED_MAX
    assert share == pytest.approx(0.12, abs=0.03), share
    fixed = E.correct_scan(scan, {"edge_bleed": share / E.BLEED_MAX, "edge_reach": 0.08}, crop)
    def right_edge(img):
        l = np.power(img.astype(np.float32) / 255, 2.2)[y1 + 30:y2 - 30, x1:x2].mean(axis=2)
        return float(l[:, -8:].mean() / l[:, 150:300].mean())
    assert right_edge(scan) > 1.1 and abs(right_edge(fixed) - 1.0) < 0.04, (right_edge(scan), right_edge(fixed))
    assert np.array_equal(fixed[:, :x1], scan[:, :x1]), "outside the crop is left alone"


def test_the_dodge_with_a_clear_border_flattens_the_edge_too():
    scan = _frame_with_bleed(0.12)
    assert abs(_edge_ratio(E.correct_scan(scan, {"edge_dodge": 1.0, "edge_reach": 0.08})) - 1.0) < 0.03


def test_the_holder_and_the_sprocket_hole_are_painted_with_the_film_base():
    base8 = tuple(int(v) for v in _encode(BASE[None, None, :])[0, 0])
    scan = np.zeros((H, W, 3), np.uint8)
    scan[:] = base8
    scan[B:H - B, B:W - B] = (120, 100, 80)
    scan[:10] = 10
    scan[:, :10] = 10                      # the holder's dark edge
    scan[20:50, 300:340] = 255             # a sprocket hole
    fixed = E.correct_scan(scan, {"edge_holder": 1.0})
    assert tuple(fixed[4, 300]) == base8 and tuple(fixed[30, 320]) == base8
    assert np.array_equal(fixed[B:H - B, B:W - B], scan[B:H - B, B:W - B]), "the picture is not touched"
    half = E.correct_scan(scan, {"edge_holder": 0.5})
    assert 10 < int(half[4, 300, 0]) < base8[0]


def test_the_border_mask_is_a_soft_band_in_the_chosen_colour():
    img = np.full((200, 300, 3), 100, np.uint8)
    out = E.apply_edge_mask(img, 0.10, 0.5, "black")      # 20 px
    assert tuple(out[0, 0]) == (0, 0, 0) and tuple(out[100, 150]) == (100, 100, 100)
    assert 0 < int(out[100, 15, 0]) < 100 or int(out[100, 15, 0]) == 0
    assert int(out[100, 19, 0]) > int(out[100, 12, 0]) or int(out[100, 12, 0]) == 0, "the band fades toward the picture"
    hard = E.apply_edge_mask(img, 0.10, 0.0, "white")
    assert tuple(hard[100, 5]) == (255, 255, 255) and tuple(hard[100, 25]) == (100, 100, 100)
    wide = E.apply_edge_mask(img.astype(np.uint16) * 257, 0.10, 0.0, "grey")
    assert wide.dtype == np.uint16 and abs(int(wide[100, 5, 0]) - 128 * 257) <= 1


def test_the_renderer_applies_the_scan_tools_before_conversion_and_the_mask_after():
    from photoeditor.desktop.render import EditParams, Renderer
    from photoeditor.desktop.session import AppState

    scan = _frame_with_bleed(0.12)
    base = dataclasses.replace(EditParams.from_state(AppState()), negative_inverted=False)

    def render(**kw):
        return Renderer().render(scan, dataclasses.replace(base, **kw), "edge-test", scan.shape[1])[0]

    plain = render()
    assert np.array_equal(render(edge_bleed=0.0), plain)
    repaired = render(edge_bleed=E.estimate_bleed(scan, 0.08), edge_reach=0.08)
    assert abs(_edge_ratio(repaired) - 1.0) < abs(_edge_ratio(plain) - 1.0) * 0.4
    masked = render(edge_mask=0.05, edge_feather=0.0, edge_mask_color="black")
    assert tuple(masked[0, 0]) == (0, 0, 0) and tuple(masked[H // 2, W // 2]) == tuple(plain[H // 2, W // 2])
    assert render(edge_mask=0.05, edge_feather=0.0, edge_mask_color="white")[0, 0].min() == 255


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False, "advanced_mode": False})
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.edgebleed import logic as E
    from photoeditor.features.persistence import edit_store
    H, W, B = 600, 900, 70
    base = np.array([0.80, 0.55, 0.30], np.float32)
    lin = np.zeros((H, W, 3), np.float32); lin[:] = base
    lin[B:H-B, B:W-B] = np.array([0.25, 0.2, 0.15], np.float32)
    outside = np.ones((H, W), bool); outside[B:H-B, B:W-B] = False
    lin[B:H-B, B:W-B] += 0.12 * E._bleed_field(lin * outside[..., None], E._sigma(0.08, H, W))[B:H-B, B:W-B]
    scan = np.clip(np.power(np.clip(lin, 0, 1), 1 / 2.2) * 255 + 0.5, 0, 255).astype(np.uint8)
    p = os.path.join(work, "a.png"); cv2.imwrite(p, scan[..., ::-1])
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.show(); win.open_folder(work, prefer=p); c = win.controller
    def pump(s):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(2)
    tool = win._edge_tool
    assert tool._title == "Edge Bleed" and set(tool._rows) == {"edge_holder", "edge_bleed", "edge_dodge", "edge_reach", "edge_mask", "edge_feather"}
    assert "film border found" in tool._status.text(), tool._status.text()

    # Auto strength reads the picture's own edge
    steps = len(c.state.history)
    tool.estimate_requested.emit(); pump(1.5)
    assert 0.15 < c.state.edge_bleed < 0.25, c.state.edge_bleed
    assert any("Edge bleed" in h.description for h in c.state.history[steps:]), [h.description for h in c.state.history[steps:]]

    # the sliders, the colour and the checkbox reach the state
    tool._rows["edge_mask"].set_value(0.04); tool._on_value_changed(); pump(1.0)
    tool._colour.setCurrentIndex(tool._colour.findData("white")); tool._meter.setChecked(False)
    end = time.time() + 20
    while time.time() < end and c.state.image_rgb[0, 0].min() <= 240:   # the settle is debounced and the render takes a moment: wait for the picture, not for a fixed time
        app.processEvents(); time.sleep(0.02)
    assert abs(c.state.edge_mask - 0.04) < 1e-6 and c.state.edge_mask_color == "white" and c.state.edge_mask_meter is False
    image = c.state.image_rgb
    assert image[0, 0].min() > 240, "the white mask is on the picture"

    # saved with the photo, undo and redo bring the panel back
    c._save_edit_state()
    saved = edit_store.load_edit_state(c._db, p)
    assert saved["edge_mask_color"] == "white" and saved["edge_mask_meter"] is False and abs(saved["edge_mask"] - 0.04) < 1e-6 and saved["edge_bleed"] > 0.15
    c.undo(); pump(0.6)
    assert c.state.edge_mask_meter is True or c.state.edge_mask_color == "black" or c.state.edge_mask == 0.0
    c.redo(); pump(0.6)
    assert abs(tool._rows["edge_mask"].value() - c.state.edge_mask) < 1e-6 and tool._colour.currentData() == c.state.edge_mask_color

    # the module's power light: off makes the picture without it, the settings kept
    on = c.state.image_rgb.copy()
    def until(cond, secs=20):      # (the settle is debounced and the render takes a moment: wait for the picture, not for a fixed time)
        end = time.time() + secs
        while time.time() < end and not cond():
            app.processEvents(); time.sleep(0.02)
    c.set_module_enabled("edgebleed", False); until(lambda: not np.array_equal(on, c.state.image_rgb)); pump(0.3)
    assert c.state.edge_mask_color == "white" and not np.array_equal(on, c.state.image_rgb)
    c.set_module_enabled("edgebleed", True); until(lambda: np.array_equal(on, c.state.image_rgb)); pump(0.3)
    assert np.array_equal(on, c.state.image_rgb)

    # a look carries it, and Clear resets it
    c.apply_look({"edge_dodge": 0.7, "edge_mask_color": "grey", "edge_mask": 0.02}, "a look"); pump(0.8)
    assert c.state.edge_dodge == 0.7 and c.state.edge_mask_color == "grey" and tool._colour.currentData() == "grey"
    c.clear_look(); pump(1.0)
    assert c._edge_values() == E.DEFAULTS and tool.values() == E.DEFAULTS, (c._edge_values(), tool.values())
    print("OK")
""")


def test_the_panel_controller_history_saving_and_looks_work_together():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-2500:]


def test_the_module_is_a_presets_module_with_an_icon_and_switches_off_cleanly():
    from photoeditor.desktop.view import panel_icons
    from photoeditor.features.lookpresets import modules as M
    from photoeditor.features.persistence import edit_store

    assert "edgebleed" in M.PANEL_MODULES and "edgebleed" in M.SWITCHABLE
    assert {f.key for f in M.panel_fields("edgebleed")} == set(E.KEYS)
    assert M.off_overrides(["edgebleed"]) == dict(E.DEFAULTS)
    assert panel_icons.BY_TITLE["Edge Bleed"] == "scan" and (panel_icons.ICON_DIR / "scan.svg").is_file()
    assert set(E.KEYS) <= {name for name, _kind in edit_store._FIELDS}
