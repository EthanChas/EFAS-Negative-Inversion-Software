"""Retouch in the window: a shape drawn for it heals a blemish, lives in the photo's masks and Retouch's group, can be put on a wavelet scale, is undoable and saved with the photo, and goes
when its shape is deleted."""
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
    from photoeditor.features.masks import model as M
    from photoeditor.features.retouchdt import logic as R
    S.save({"scan_quality": False})
    rng = np.random.default_rng(0)
    base = np.linspace(60, 190, 900, dtype=np.float32)[None, :, None] * np.ones((600, 1, 3), np.float32)
    img = np.clip(base + rng.normal(0, 2, (600, 900, 3)), 0, 255).astype(np.uint8)
    cv2.circle(img, (360, 180), 5, (250, 250, 250), -1)     # a bright blemish
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
    s = c.state; panel = win._retouch_tool; editor = win._mask_editor; tool = editor.tool
    assert s.retouch == {} and not c.retouch_settings().active()

    def at(fx, fy):
        return c.raw_to_display(np.array([[fx, fy]], float))[0]
    bx, by = at(360 / 900, 180 / 600)
    def spot(img_):
        # how far the blemish stands out from what is round it
        ys, xs = int(round(by)), int(round(bx))
        around = float(img_[ys - 22:ys - 16, xs - 3:xs + 4].mean())
        return abs(float(img_[ys - 2:ys + 3, xs - 2:xs + 3].mean()) - around)
    pump(secs=2.0)
    before = spot(s.image_rgb)
    assert before > 100, before

    # --- a wavelet scale can be looked at on the picture before there is a shape: the panel's bar and its display button
    still = s.image_rgb.copy()
    panel._bar.num_scales_changed.emit(4); panel._bar.scale_selected.emit(2); app.processEvents()
    assert c.retouch_settings().num_scales == 4 and c.retouch_settings().curr_scale == 2
    panel._view_scale.setChecked(True); app.processEvents()
    assert pump(lambda: not np.array_equal(s.image_rgb, still), 30.0), "the layer is shown instead of the picture"
    assert panel._levels_box.isVisibleTo(panel), "the levels slider appears with the layer"
    panel._view_scale.setChecked(False); app.processEvents()
    assert pump(lambda: np.array_equal(s.image_rgb, still), 30.0)
    panel._bar.scale_selected.emit(0); panel._bar.num_scales_changed.emit(0); app.processEvents()

    # --- heal a blemish: pick the heal algorithm, draw a circle on it
    panel._algo["heal"].click(); app.processEvents()
    assert c.retouch_settings().algorithm == "heal"
    panel._draw[M.CIRCLE].click(); app.processEvents()
    assert tool.creation is not None and tool.creation.key == "retouch" and tool.creation.source
    tool.press(bx, by, "left", set()); tool.release(bx, by, "left", set())
    assert pump(lambda: len(c.retouch_settings().forms) == 1), s.retouch
    cs = c.retouch_settings()
    assert cs.forms[0].algorithm == "heal" and cs.forms[0].scale == 0 and cs.group, cs.to_dict()
    ms = c.mask_set()
    assert ms.get(cs.group).name == "Retouch" and [p["formid"] for p in ms.members(cs.group)] == [cs.forms[0].formid]
    assert ms.get(cs.forms[0].formid).source != [0.0, 0.0], "a heal shape has a source"
    assert pump(lambda: spot(s.image_rgb) < before / 3, 30.0), (spot(s.image_rgb), before)
    after = spot(s.image_rgb)
    assert after < 25, "the blemish took on what is round it"
    assert tool.edit and tool.visible == {cs.forms[0].formid} and editor._retouch
    assert win._retouch_picked == cs.forms[0].formid and "shape selected: #" in panel._picked_label.text()

    # --- the picture shown without Retouch, and where the shapes act
    c.set_retouch_view("suppress"); assert pump(lambda: spot(s.image_rgb) > before * 0.8, 30.0), "suppress shows the picture as it was"
    c.set_retouch_view("mask"); assert pump(lambda: int(s.image_rgb[int(by), int(bx), 0]) - int(s.image_rgb[int(by), int(bx), 2]) > 60, 30.0), "yellow where the shape acts"
    c.set_retouch_view(""); assert pump(lambda: spot(s.image_rgb) < before / 3, 30.0)

    # --- the shape goes on another wavelet scale; the bar's choices are not edits but the number of scales is
    steps = len(s.history)
    panel._bar.scale_selected.emit(0)
    panel._bar.num_scales_changed.emit(3); app.processEvents()
    assert c.retouch_settings().num_scales == 3 and len(s.history) == steps + 1 and "wavelet scales" in s.history[-1].description
    c.set_retouch({"curr_scale": 2}); assert len(s.history) == steps + 1, "choosing a scale to look at is not an edit"
    assert tool.visible == set(), "the shapes shown are those of the scale being worked on"
    c.set_retouch({"curr_scale": 0}); app.processEvents()
    assert tool.visible == {cs.forms[0].formid}
    assert c.paste_retouch_scale(0, 2) == 1 and c.retouch_settings().forms[0].scale == 2
    assert pump(lambda: spot(s.image_rgb) > after + 20, 30.0), (spot(s.image_rgb), after)    # on scale 2 the shape only changes that layer: the blemish is mostly still there
    c.paste_retouch_scale(2, 0)

    # --- a blur shape takes its own settings; the picked shape's blur radius changes
    panel._algo["blur"].click(); app.processEvents()
    panel._draw[M.ELLIPSE].click(); app.processEvents()
    x2, y2 = at(0.7, 0.7)
    tool.press(x2, y2, "left", set()); tool.release(x2, y2, "left", set())
    assert pump(lambda: len(c.retouch_settings().forms) == 2)
    blur = c.retouch_settings().forms[1]
    assert blur.algorithm == "blur" and win._retouch_picked == blur.formid
    assert c.mask_set().get(blur.formid).source == [0.0, 0.0], "a blur shape has no source"
    assert tool.creation is None
    c.set_retouch({"blur_radius": 25.0}, "Retouch: blur radius", False, blur.formid)
    assert c.retouch_settings().form(blur.formid).blur_radius == 25.0 and c.retouch_settings().form(cs.forms[0].formid).algorithm == "heal"
    assert abs(panel._blur_radius.value() - 25.0) < 1e-6

    # --- undo, persistence, deleting a shape
    c.undo(); app.processEvents()
    assert c.retouch_settings().form(blur.formid).blur_radius == 10.0
    c._save_edit_state()
    saved = edit_store.load_edit_state(c._db, path)
    assert saved["retouch"]["forms"] and saved["retouch"]["group"] == cs.group, saved["retouch"]
    win._mask_manager.delete_requested.emit([cs.forms[0].formid]); app.processEvents()
    left = c.retouch_settings()
    assert cs.forms[0].formid not in [f.formid for f in left.forms], "Retouch lets go of a shape that was deleted"
    assert pump(lambda: spot(s.image_rgb) > before * 0.8, 30.0), "and the blemish is back"
    print("OK retouch")
""")


def test_retouch_in_the_window():
    r = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=400)
    assert r.returncode == 0 and "OK retouch" in r.stdout, r.stdout[-2000:] + r.stderr[-5000:]
