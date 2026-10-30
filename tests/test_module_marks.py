"""The red star beside a module that has been changed from its defaults, and the Enabled list that follows it: put the module back to its defaults and it leaves the list."""
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
    S.save({"scan_quality": False})
    cv2.imwrite(os.path.join(folder, "a.png"), np.random.default_rng(0).integers(60, 200, (400, 600, 3), dtype=np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=os.path.join(folder, "a.png"))
    def pump(secs):
        end = time.time() + secs
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(3)
    ex, sh = win._exposure_tool, win._module_menus._panels["sharpening"]
    assert not ex.is_changed() and not sh.is_changed(), "a fresh photo has no stars"
    c.set_exposure_ev(0.5); pump(0.6)
    assert ex.is_changed() and not sh.is_changed(), "the module that was changed has the star, the other does not"
    assert ex._header.changed_star.text() == "*" and "e5484d" in ex._header.changed_star.styleSheet().lower()
    win._tool_rail._buttons["active"].click(); pump(0.8)
    assert "Exposure" in win._module_search.result_titles()
    c.reset_module("exposure"); pump(0.8)
    assert not ex.is_changed(), "back at its defaults: no star"
    assert "Exposure" not in win._module_search.result_titles(), win._module_search.result_titles()
    c.set_exposure_ev(-0.4); pump(0.8)
    assert ex.is_changed() and "Exposure" in win._module_search.result_titles(), "changed again: it is back in the list"
    crop = win._crop_tool
    assert not crop.is_changed()
    c.set_crop_rect((50, 40, 400, 300)); pump(0.8)
    assert crop.is_changed() and "Crop & Rotate" in win._module_search.result_titles(), "a crop gives Crop & Rotate its star and a place in the list"
    c.reset_geometry(); pump(0.8)
    assert not crop.is_changed() and "Crop & Rotate" not in win._module_search.result_titles()
    c.set_fine_rotation(1.5); pump(0.8)
    assert crop.is_changed(), "straightening is Crop & Rotate's too"
    c.reset_geometry(); pump(0.5)
    ai = win._ai_dust_tool
    assert not ai.is_changed()
    c.set_ai_dust(True, 0.3, 2); pump(0.8)
    assert ai.is_changed()
    print("OK module marks")
""")


def test_the_star_follows_a_changed_module_and_the_enabled_list_follows_the_star():
    r = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "OK module marks" in r.stdout, r.stdout[-1500:] + r.stderr[-3000:]
