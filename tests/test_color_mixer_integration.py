"""The Color Mixer and the Lab Look scanner colour in the app: renderer, saved state, history, presets and the two panels."""
import dataclasses
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np

from photoeditor.features.colormix import logic as cm

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_the_renderer_applies_vibrance_the_mixer_and_the_response_in_every_path():
    from photoeditor.desktop.render import EditParams, Renderer
    from photoeditor.desktop.session import AppState

    rng = np.random.default_rng(3)
    base = dataclasses.replace(EditParams.from_state(AppState()), negative_inverted=False)
    yy, xx = np.mgrid[0:40, 0:60]
    scan16 = np.stack([20000 + xx * 400, 22000 + yy * 300, 26000 + (xx + yy) * 200], axis=-1).astype(np.uint16)   # a muted gradient
    scan8 = (scan16 // 257).astype(np.uint8)

    def chroma(img):
        return np.hypot(*(cm.srgb8_to_oklab(img.astype(np.uint8))[..., 1:].transpose(2, 0, 1))).mean()

    def render(scan, **kw):
        return Renderer().render(scan, dataclasses.replace(base, **kw), "t", scan.shape[1])[0]

    for scan in (scan16, scan8):
        plain = render(scan)
        assert chroma(render(scan, vibrance=1.0)) > chroma(plain) * 1.2, "vibrance raises the colour of a muted picture"
        assert chroma(render(scan, mix_sat_blue=-1.0, mix_sat_aqua=-1.0, mix_sat_purple=-1.0, mix_sat_magenta=-1.0)) < chroma(plain), "the mixer lowers its ranges"
        frontier = render(scan, lab_response="frontier", lab_response_amount=1.0)
        assert not np.array_equal(frontier, plain) and np.array_equal(render(scan, lab_response="frontier", lab_response_amount=0.0), plain), "amount 0 is no response"
        assert np.array_equal(render(scan, lab_response="none"), plain)
        assert render(scan).dtype == np.uint8
    off = render(scan16, lab_response="frontier", lab_response_amount=1.0, mix_hue_red=0.5)
    again = render(scan16, lab_response="frontier", lab_response_amount=1.0, mix_hue_red=0.5)
    assert np.array_equal(off, again), "the same settings give the same picture"


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
    win = aw.AppWindow(); win.show(); win.open_folder(work, prefer=p); c = win.controller
    def pump(s):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(2)
    mixer, lab = win._color_mixer_tool, win._lab_look_tool

    # --- the mixer panel: a range is picked, its three sliders show and change only that range
    steps = len(c.state.history)
    assert mixer._band == "red" and set(mixer._swatches) == {"red", "orange", "yellow", "green", "aqua", "blue", "purple", "magenta"}
    mixer._select("blue"); mixer._rows["sat"].set_value(0.6); mixer._on_band_value("sat", 0.6)
    mixer._select("green"); mixer._rows["hue"].set_value(-0.4); mixer._on_band_value("hue", -0.4)
    pump(1.2)
    assert abs(c.state.mix_sat_blue - 0.6) < 1e-6 and abs(c.state.mix_hue_green + 0.4) < 1e-6 and c.state.mix_sat_green == 0.0, "values reach the state, per range"
    assert any("Color mixer" in h.description for h in c.state.history[steps:]), [h.description for h in c.state.history[steps:]]
    mixer._select("blue")
    assert abs(mixer._rows["sat"].value() - 0.6) < 1e-6 and mixer._rows["hue"].value() == 0.0, "switching range shows that range's values"
    mixer._vibrance.set_value(0.5); mixer._on_vibrance(0.5); pump(1.0)
    assert abs(c.state.vibrance - 0.5) < 1e-6
    c._save_edit_state()
    # undo / redo bring the panel back too
    c.undo(); pump(0.6)
    assert c.state.vibrance == 0.0 and mixer._vibrance.value() == 0.0, "undo takes vibrance back, panel included"
    c.redo(); pump(0.6)
    assert abs(c.state.vibrance - 0.5) < 1e-6 and abs(mixer._vibrance.value() - 0.5) < 1e-6

    # --- saved and loaded again with the photo
    saved = c._save_edit_state
    from photoeditor.features.persistence import edit_store
    state = edit_store.load_edit_state(c._db, p)
    assert abs(state["mix_sat_blue"] - 0.6) < 1e-6 and abs(state["vibrance"] - 0.5) < 1e-6 and state["lab_response"] == "none" and state["lab_response_amount"] == 1.0

    # --- the Lab Look scanner colour: the combo, its amount, the state, a preset
    lab._response.setCurrentIndex(lab._response.findData("noritsu")); pump(1.0)
    assert c.state.lab_response == "noritsu" and abs(c.state.lab_response_amount - 1.0) < 1e-6 and lab._rows["lab_response_amount"].isEnabled()
    lab._rows["lab_response_amount"].set_value(0.4); lab._on_value_changed(); pump(1.0)
    assert abs(c.state.lab_response_amount - 0.4) < 1e-6
    lab._response.setCurrentIndex(lab._response.findData("none")); pump(1.0)
    assert not lab._rows["lab_response_amount"].isEnabled(), "no scanner, no amount"
    c.apply_builtin_preset("Lab Scanners/Frontier 100"); pump(1.0)
    assert c.state.lab_response == "frontier" and lab._response.currentData() == "frontier", "the Frontier preset brings the Frontier colour response"
    assert abs(c.state.lab_fade - 0.22) < 1e-6, "and its fade"
    c.apply_look({"vibrance": 0.3, "mix_lum_orange": 0.2}, "a look"); pump(0.8)
    assert abs(c.state.vibrance - 0.3) < 1e-6 and abs(mixer._vibrance.value() - 0.3) < 1e-6 and abs(c.state.mix_lum_orange - 0.2) < 1e-6
    c.clear_look(); pump(1.0)
    assert c.state.vibrance == 0.0 and c.state.mix_sat_blue == 0.0 and c.state.mix_lum_orange == 0.0 and c.state.lab_response == "none", "Clear resets the new modules too"
    assert mixer._values["mix_sat_blue"] == 0.0 and lab._response.currentData() == "none"
    # a new file starts neutral
    print("OK")
""")


def test_the_panels_controller_history_saving_and_presets_work_together():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-2500:]


def test_the_new_modules_are_presets_modules_with_icons_and_switch_off_cleanly():
    from photoeditor.desktop.view import panel_icons
    from photoeditor.features.lookpresets import modules as M

    assert "colormixer" in M.PANEL_MODULES and "colormixer" in M.SWITCHABLE and "lablook" in M.SWITCHABLE
    fields = {f.key for f in M.panel_fields("colormixer")}
    assert fields == set(cm.KEYS) and len(fields) == 25
    off = M.off_overrides(["colormixer"])
    assert off == {k: 0.0 for k in cm.KEYS}
    assert panel_icons.BY_TITLE["Color Mixer"] == "swatch-book" and panel_icons.BY_TITLE["Lab Look"] == "printer"
    for name in ("swatch-book", "printer"):
        assert (panel_icons.ICON_DIR / f"{name}.svg").is_file(), name
    choice = next(f for f in M.panel_fields("lablook") if f.key == "lab_response")
    assert [k for k, _label in choice.choices] == list(cm.RESPONSES)
    # the saved-state columns exist for every new key
    from photoeditor.features.persistence import edit_store

    columns = {name for name, _kind, _default in edit_store._COLUMNS} if hasattr(edit_store, "_COLUMNS") else set()
    names = {name for name, _kind in edit_store._FIELDS}
    assert set(cm.KEYS) <= names and {"lab_response", "lab_response_amount"} <= names
    del columns
