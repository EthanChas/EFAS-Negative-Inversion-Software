"""Diffuse or Sharpen, Tone Equalizer and Color Balance RGB in the window: their panels change the picture, are one history step each, undo, reset, come back after a save, have their copies
and Mask boxes and on/off lights, carry darktable's presets in the Presets menu, and the Tone Equalizer's mask can be shown."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp(); folder = os.path.join(work, "r"); os.makedirs(folder)
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.features.persistence import edit_store
    S.save({"scan_quality": False})
    h, w = 300, 420
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.stack([40 + 170 * xx / w, 60 + 120 * yy / h, 200 - 150 * xx / w], axis=2)
    img[100:200, 150:300] = (210, 90, 60)
    img = np.clip(img + np.random.default_rng(0).normal(0, 4, img.shape), 0, 255).astype(np.uint8)
    path = os.path.join(folder, "a.png"); cv2.imwrite(path, img[:, :, ::-1])
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=path)
    def pump(secs):
        end = time.time() + secs
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(3)
    s = c.state
    base = s.image_rgb.astype(int)
    def change(): return float(np.abs(s.image_rgb.astype(int) - base).mean())
    def settle(panel, values):
        panel.set_values({**panel.values(), **values}); panel.changed.emit(panel.values())      # as the person does: the controls show it, then it is applied

    panels = {"diffuse": win._diffuse_tool, "toneequalizer": win._tone_eq_tool, "colorbalancergb": win._color_balance_tool}
    for key, panel in panels.items():
        assert key in win._module_menus._panels and panel._title == {"diffuse": "Diffuse or Sharpen", "toneequalizer": "Tone Equalizer", "colorbalancergb": "Color Balance RGB"}[key]
        assert not panel.instances_button.isHidden() and key in win._blend_boxes, (key, "copies and the Mask box")
        assert panel._header._title_label.text().endswith("(darktable)"), panel._header._title_label.text()

    # --- Tone Equalizer: the panel says a change, the picture follows, it is one history step
    n0 = len(s.history)
    values = {"teq_band2": 1.0, "teq_band3": 1.0, "teq_band4": 1.0}
    settle(win._tone_eq_tool, values); pump(3)
    assert s.teq_band3 == 1.0 and change() > 1.0 and len(s.history) == n0 + 1 and "Tone equalizer" in s.history[-1].description, (change(), s.history[-1].description)
    lifted = change()
    c.undo(); pump(3)
    assert s.teq_band3 == 0.0 and change() < 0.5 and win._tone_eq_tool.values()["teq_band3"] == 0.0, "undo puts the picture and the panel back"
    settle(win._tone_eq_tool, values); pump(3)
    assert abs(change() - lifted) < 0.5
    # the wands read the mask of the open photo
    boost = c.auto_tone_eq("teq_exposure_boost"); contrast = c.auto_tone_eq("teq_contrast_boost")
    assert boost is not None and np.isfinite(boost) and np.isfinite(contrast)
    win._on_tone_eq_wand("teq_exposure_boost"); pump(3)
    assert abs(s.teq_exposure_boost - boost) < 0.3 or abs(win._tone_eq_tool.values()["teq_exposure_boost"] - boost) < 0.3
    # the mask can be shown: a grey picture, not an edit
    hist_len = len(s.history)
    win._tone_eq_tool._show_mask.setChecked(True); pump(3)
    assert s.teq_show_mask and np.array_equal(s.image_rgb[..., 0], s.image_rgb[..., 1]) and len(s.history) == hist_len
    win._tone_eq_tool._show_mask.setChecked(False); pump(3)
    assert not s.teq_show_mask and not np.array_equal(s.image_rgb[..., 0], s.image_rgb[..., 1])
    # the module's own light, and Reset
    c.set_module_enabled("toneequalizer", False); pump(3)
    assert change() < 0.5
    c.set_module_enabled("toneequalizer", True); pump(3)
    assert change() > 1.0
    assert c.reset_module("toneequalizer"); pump(3)
    assert s.teq_band3 == 0.0 and change() < 0.5 and all(abs(v) < 1e-9 for k, v in win._tone_eq_tool.values().items() if k.startswith("teq_band"))

    # --- Color Balance RGB
    settle(win._color_balance_tool, {"cbr_saturation_global": 0.6, "cbr_shadows_C": 0.2, "cbr_shadows_H": 220.0}); pump(4)
    assert s.cbr_saturation_global == 0.6 and change() > 1.0 and "Color balance rgb" in s.history[-1].description, (change(), s.history[-1].description)
    assert win._color_balance_tool.values()["cbr_saturation_global"] == 0.6
    graded = s.image_rgb.copy()
    # darktable's presets are in the module's menu list and apply as one step
    assert "basic colorfulness | standard" in c.module_darktable_presets("colorbalancergb") and len(c.module_darktable_presets("diffuse")) == 15
    assert c.apply_darktable_module_preset("colorbalancergb", "basic colorfulness | legacy"); pump(4)
    assert s.cbr_formula == 0.0 and s.cbr_saturation_global == 0.0 and s.cbr_chroma_global == 0.2 and not np.array_equal(s.image_rgb, graded), "the preset sets what it names and the module's defaults for the rest"
    c.undo(); pump(3)
    assert s.cbr_saturation_global == 0.6

    # --- Diffuse or Sharpen waits for the sliders to be let go, then sharpens
    before_diffuse = s.image_rgb.astype(int)
    settle(win._diffuse_tool, {"dif_iterations": 2.0, "dif_radius": 4.0, "dif_first": -0.25, "dif_second": -0.25, "dif_third": -0.25, "dif_fourth": -0.25,
                               "dif_aniso_first": 1.0, "dif_aniso_second": 1.0, "dif_aniso_third": 1.0, "dif_aniso_fourth": 1.0, "dif_regularization": 1.0}); pump(6)
    assert s.dif_first == -0.25 and float(np.abs(s.image_rgb.astype(int) - before_diffuse).mean()) > 0.2 and "Diffuse or sharpen" in s.history[-1].description
    win._diffuse_tool.preview_requested.emit({**win._diffuse_tool.values(), "dif_first": -0.9}); pump(2)    # a drag in progress: the preview does not wait for it

    # --- saved with the photo and read back
    c._save_edit_state()
    saved = edit_store.load_edit_state(c._db, path)
    assert saved["cbr_saturation_global"] == 0.6 and saved["dif_third"] == -0.25 and saved["teq_details"] == 4.0 and saved["cbr_formula"] == 1.0, "the new fields are kept with the photo"
    assert not edit_store.is_untouched(saved, c.state.tone_curve_points)

    # --- copies of each: their own panel, settings and Mask box, and a picture that follows
    for key in ("toneequalizer", "colorbalancergb", "diffuse"):
        win._new_instance(key, None); pump(1.0)
        panel = win._instance_panels[key + "#1"]
        assert key + "#1" in win._blend_boxes and len(panel._rows) + len(panel._boxes) == len(__import__("photoeditor.features.instances.logic", fromlist=["x"]).fields_of(key)), key
    c.undo(); c.undo(); c.undo(); pump(1.0)
    assert not win._instance_panels
    win._new_instance("colorbalancergb", None); pump(1.0)
    now = s.image_rgb.copy()
    win._instance_panels["colorbalancergb#1"].values_changed.emit({"cbr_saturation_global": 0.8}, False); pump(4)
    assert s.instances["colorbalancergb"][0]["values"]["cbr_saturation_global"] == 0.8 and s.cbr_saturation_global == 0.6 and not np.array_equal(s.image_rgb, now), "the copy's own setting, on top of the module's"
    print("OK")
""")


def test_the_three_darktable_modules_in_the_window():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=900, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-3500:]
