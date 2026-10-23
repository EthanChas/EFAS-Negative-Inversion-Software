"""Copies of a module in the window: a header button makes one, it appears right after its module with its number and name, has its own controls, Mask box and light, goes with an undo,
is saved with the photo, and is listed by the Enabled tab."""
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
    rng = np.random.default_rng(0)
    img = np.clip(110 + rng.normal(0, 5, (400, 600, 3)), 0, 255).astype(np.uint8)
    path = os.path.join(folder, "a.png"); cv2.imwrite(path, img)
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=path)
    def pump(secs):
        end = time.time() + secs
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(3)
    s = c.state
    base = win._exposure_tool
    assert not base.instances_button.isHidden(), "the module has the multiple-instances button"
    before = s.image_rgb.astype(int).mean()

    # --- a new copy: next to its module, numbered, with its own Mask box and light
    win._new_instance("exposure", None); pump(1.0)
    panel = win._instance_panels["exposure#1"]
    layout = base.parentWidget().layout()
    assert layout.indexOf(panel) == layout.indexOf(base) + 1, "right after the module it is a copy of"
    assert panel._header._title_label.text() == "Exposure 1" and panel.power_on() and "exposure#1" in win._blend_boxes
    assert not panel.instances_button.isHidden() and not panel.reset_button.isHidden()
    assert s.instances["exposure"][0]["values"]["exposure_ev"] == 0.0

    # --- its own controls change the picture
    panel.values_changed.emit({"exposure_ev": 1.0}, False); pump(2.0)
    assert s.instances["exposure"][0]["values"]["exposure_ev"] == 1.0 and s.exposure_ev == 0.0, "the copy's setting, not the module's"
    assert s.image_rgb.astype(int).mean() > before + 8
    # --- it can be named
    c.rename_instance("exposure", 1, "skin"); pump(0.5)
    assert panel._header._title_label.text() == "Exposure 1 - skin"
    # --- the light switches it off and on again
    panel.power_toggled.emit(False); pump(2.0)
    assert abs(s.image_rgb.astype(int).mean() - before) < 1.0 and not panel.power_on()
    panel.power_toggled.emit(True); pump(2.0)
    assert s.image_rgb.astype(int).mean() > before + 8
    # --- a duplicate of the module starts with what the module is set to now
    c.set_exposure_ev(0.4); pump(1.0)
    new_id = c.add_instance("exposure", 0); pump(1.0)
    assert new_id == 2 and s.instances["exposure"][1]["values"]["exposure_ev"] == 0.4 and "exposure#2" in win._instance_panels
    assert win._instance_panels["exposure#2"]._header._title_label.text() == "Exposure 2"
    # --- its own mask
    box = win._blend_boxes["exposure#2"]
    from photoeditor.features.masks import blend as B
    i = box._mode.findData(B.DRAWN); box._mode.setCurrentIndex(i); box._mode.activated.emit(i); pump(0.5)
    assert c.blend_of("exposure#2").mode == B.DRAWN and c.blend_of("exposure#1").mode == B.OFF and c.blend_of("exposure").mode == B.OFF

    # --- saved with the photo, listed by the Enabled tab
    c._save_edit_state()
    saved = edit_store.load_edit_state(c._db, path)
    assert [i["id"] for i in saved["instances"]["exposure"]] == [1, 2] and saved["instances"]["exposure"][0]["name"] == "skin"
    rail = win._tool_rail
    rail._buttons["active"].click(); pump(1.0)
    titles = win._module_search.result_titles()
    assert titles.count("Exposure") == 3, ("the module and both copies are listed", titles)
    rail._buttons["active"].click(); pump(0.6)

    # --- undo takes the last copy away, delete takes one away, and the panels follow
    c.undo(); c.undo(); pump(1.0)
    c.remove_instance("exposure", 1); pump(1.0)
    assert "exposure#1" not in win._instance_panels and "exposure#1" not in win._blend_boxes and not c.state.instances.get("exposure")
    c.undo(); pump(1.0)
    assert "exposure#1" in win._instance_panels, "undo brings the deleted copy back"
    print("OK instances")
""")


def test_copies_of_a_module_in_the_window():
    r = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=400)
    assert r.returncode == 0 and "OK instances" in r.stdout, r.stdout[-1500:] + r.stderr[-3500:]
