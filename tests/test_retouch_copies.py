"""Copies of Retouch (darktable's multiple instances of retouch): each has its own shapes, scales and algorithm, its own panel, number, name and light; they act one after the other."""
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
    S.save({"scan_quality": False})
    img = np.clip(120 + np.random.default_rng(0).normal(0, 3, (600, 900, 3)), 0, 255).astype(np.uint8)
    path = os.path.join(folder, "a.png"); cv2.imwrite(path, img)
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=path)
    def pump(secs, cond=lambda: False):
        end = time.time() + secs
        while time.time() < end:
            app.processEvents()
            if cond(): return True
            time.sleep(0.01)
        return cond()
    pump(3)
    s = c.state; ed = win._mask_editor
    red = lambda: int(((s.image_rgb[..., 0].astype(int) - s.image_rgb[..., 2].astype(int)) > 80).sum())
    base = win._retouch_tool
    assert not base.instances_button.isHidden()

    # --- a copy of Retouch: a panel of its own after the module, numbered
    win._new_instance("retouch", None); pump(1.0)
    copy = win._retouch_panels[1]
    layout = base.parentWidget().layout()
    assert layout.indexOf(copy) == layout.indexOf(base) + 1 and copy._header._title_label.text() == "Retouch 1" and copy.power_on()
    assert s.instances["retouch"][0]["id"] == 1

    # --- its shapes are its own
    copy._algo["fill"].click(); c.set_retouch({"fill_mode": "color", "fill_color": [1.0, 0.0, 0.0]}, instance=1); pump(0.4)
    copy._draw[M.CIRCLE].click(); app.processEvents()
    assert ed._retouch and ed.retouch_instance == 1 and ed.tool.creation.key == "retouch#1" and ed.tool.creation.source is False
    x, y = c.raw_to_display(np.array([[0.4, 0.5]], float))[0]
    ed.tool.press(x, y, "left", set()); ed.tool.release(x, y, "left", set()); pump(2.5)
    assert len(c.retouch_settings(1).forms) == 1 and not c.retouch_settings(0).forms, "the shape is the copy's, not the module's"
    assert red() > 50 and c.retouch_instance_of(c.retouch_settings(1).forms[0].formid) == 1
    assert win._retouch_picked == c.retouch_settings(1).forms[0].formid and "shape selected: #" in copy._picked_label.text() and "none" in base._picked_label.text()
    assert ed.tool.visible == {c.retouch_settings(1).forms[0].formid}, "only the copy's shapes are shown for editing"

    # --- the module and its copy act one after the other
    base._algo["fill"].click(); c.set_retouch({"fill_mode": "color", "fill_color": [0.0, 1.0, 0.0]}); pump(0.4)
    base._draw[M.CIRCLE].click(); app.processEvents()
    assert ed.retouch_instance == 0
    x2, y2 = c.raw_to_display(np.array([[0.7, 0.5]], float))[0]
    ed.tool.press(x2, y2, "left", set()); ed.tool.release(x2, y2, "left", set()); pump(2.5)
    assert len(c.retouch_settings(0).forms) == 1 and len(c.retouch_settings(1).forms) == 1
    green = int(((s.image_rgb[..., 1].astype(int) - s.image_rgb[..., 0].astype(int)) > 80).sum())
    assert red() > 50 and green > 50

    # --- the copy's light, a name, a view of its own, saved with the photo
    copy.power_toggled.emit(False); pump(2.5)
    assert red() == 0 and not copy.power_on() and green > 0
    copy.power_toggled.emit(True); assert pump(15, lambda: red() > 50)
    c.rename_instance("retouch", 1, "dust"); pump(0.4)
    assert copy._header._title_label.text() == "Retouch 1 - dust"
    c.set_retouch_view("mask", 1); pump(2.0); win._refresh_retouch()
    assert s.retouch_view == "mask" and s.retouch_view_of == 1 and copy._show_mask.isChecked() and not base._show_mask.isChecked()
    c.set_retouch_view("", 1); pump(1.0)
    c._save_edit_state()
    saved = edit_store.load_edit_state(c._db, path)["instances"]["retouch"]
    assert saved[0]["name"] == "dust" and saved[0]["settings"]["forms"], saved

    # --- deleting its shape takes it out of the copy only; deleting the copy takes its panel away; an undo brings it back
    c.delete_masks([c.retouch_settings(1).forms[0].formid]); pump(1.5)
    assert not c.retouch_settings(1).forms and len(c.retouch_settings(0).forms) == 1 and red() == 0
    c.remove_instance("retouch", 1); pump(1.0)
    assert 1 not in win._retouch_panels and not c.state.instances.get("retouch")
    c.undo(); pump(1.0)
    assert 1 in win._retouch_panels
    print("OK retouch copies")
""")


def test_copies_of_retouch_have_their_own_shapes_panel_and_light():
    r = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=500)
    assert r.returncode == 0 and "OK retouch copies" in r.stdout, r.stdout[-1500:] + r.stderr[-3500:]
