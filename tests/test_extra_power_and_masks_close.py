"""Dust & Scratches, Retouch and Error marking have an on/off light (off: the picture is made without them, what they hold is put away, the choice is kept with the photo); closing the Masks panel puts
away everything picked in it."""
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
    from photoeditor.features.errormarks import logic as E
    S.save({"scan_quality": False})
    rng = np.random.default_rng(0)
    img = np.clip(120 + rng.normal(0, 3, (600, 900, 3)), 0, 255).astype(np.uint8)
    cv2.circle(img, (300, 200), 4, (20, 20, 20), -1)
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
    pump(secs=3)
    s = c.state
    for key in ("dust", "retouch", "errormarks"):
        panel = win._extra_panels[key]
        assert not panel._header.power_light.isHidden() and panel.power_on(), key

    # --- Dust & Scratches: off, its repair is not made and its tool is put away
    c.set_dust(True, 0.5, 10, 0.8); pump(secs=2.5)
    repaired = s.image_rgb.copy()
    d = win._dust_tool
    d._tool_buttons["delete"].setChecked(True); pump(secs=0.6)
    assert d.active_tool() == "delete"
    win._dust_tool.power_toggled.emit(False); pump(secs=2.5)
    assert not c.module_enabled("dust") and not d.power_on() and d.active_tool() is None and not c.state.show_detections
    assert not np.array_equal(repaired, s.image_rgb), "without the module the speck is back"
    win._dust_tool.power_toggled.emit(True); pump(lambda: np.array_equal(repaired, s.image_rgb), 20.0)
    assert np.array_equal(repaired, s.image_rgb), "on again: repaired as before (its settings were kept)"

    # --- Retouch: off, its shapes do nothing and are not shown for editing
    r = win._retouch_tool
    r._algo["fill"].click(); c.set_retouch({"fill_mode": "color", "fill_color": [1.0, 0.0, 0.0]}); pump(secs=0.4)
    r._draw[M.CIRCLE].click(); app.processEvents()
    x, y = c.raw_to_display(np.array([[0.6, 0.6]], float))[0]
    ed = win._mask_editor; ed.tool.press(x, y, "left", set()); ed.tool.release(x, y, "left", set()); pump(secs=2)
    red = lambda im: int(((im[..., 0].astype(int) - im[..., 2].astype(int)) > 80).sum())
    assert red(s.image_rgb) > 50 and ed._retouch
    win._retouch_tool.power_toggled.emit(False); pump(secs=2.5)
    assert red(s.image_rgb) == 0 and not ed._retouch and not ed.tool.active, "no shapes made, none on the picture to edit"
    win._retouch_tool.power_toggled.emit(True); pump(lambda: red(s.image_rgb) > 50, 20.0)
    assert red(s.image_rgb) > 50

    # --- Error marking: off, the marks are not shown and no more can be made; kept with the photo
    assert c.add_error_mark(E.KIND_IDS[0], 10, 10, 60, 60) and len(c.error_mark_shapes()) == 1
    win._error_marks_panel.power_toggled.emit(False); pump(secs=0.6)
    assert c.error_mark_shapes() == [] and not c.add_error_mark(E.KIND_IDS[0], 10, 10, 60, 60) and len(s.error_marks) == 1
    c._save_edit_state()
    assert "errormarks" in edit_store.load_edit_state(c._db, path)["modules_off"], "kept with the photo"
    win._error_marks_panel.power_toggled.emit(True); pump(secs=0.4)
    assert len(c.error_mark_shapes()) == 1

    # --- closing the Masks panel puts away what was picked in it
    ms = win._mask_manager; tree = ms._tree
    a = c.add_mask_form(M.CIRCLE, M.circle(0.3, 0.5, 0.1, 0.03)); pump(secs=0.8)
    shapes_item = tree.topLevelItem(2)
    tree.clearSelection(); shapes_item.child(0).setSelected(True); app.processEvents()
    assert ed._manager and ed.tool.active and win._image_view._label._mask_show is not None or ed.tool.active
    tree.clearSelection(); tree.topLevelItem(0).setSelected(True); pump(secs=0.8)
    assert win._detection_group == "all"
    ms.toggle(); pump(secs=0.8)                                             # the panel is closed
    assert not ms._expanded and not ed._manager and not ed.tool.active and win._detection_group == "" and not tree.selectedItems()
    assert win._image_view._label._mask_show is None and win._image_view._label._focus_marks == []
    print("OK extra power")
""")


def test_extra_modules_have_a_power_light_and_closing_masks_puts_everything_away():
    r = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=400)
    assert r.returncode == 0 and "OK extra power" in r.stdout, r.stdout[-1500:] + r.stderr[-3500:]
