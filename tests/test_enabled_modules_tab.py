"""The Enabled modules tab (the power button): the modules that are on and doing something to this photo are gathered into one list, from whichever tab each lives in, and go home when it is closed."""
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
    rail = win._tool_rail
    assert list(rail._buttons)[0] == "active", "the power button is the first tab"
    c.set_exposure_ev(0.5); c.set_sharpen(0.6, 1.0, 0.0, "usm"); pump(1.5)
    rail._buttons["active"].click(); pump(0.8)
    titles = win._module_search.result_titles()
    assert "Exposure" in titles and "Sharpening" in titles, titles
    assert "Tone Curve" not in titles and "Color Mixer" not in titles and "Retouch" not in titles, "only what is doing something"
    assert win._search_panel._is_open and rail._buttons["active"].isChecked()
    # a module can be switched off from the list; it is gone the next time the tab is opened
    win._exposure_tool.power_toggled.emit(False); pump(1.0)
    rail._buttons["active"].click(); pump(0.6)            # closed
    assert not win._module_search.active() and not rail._buttons["active"].isChecked() and not win._search_panel._is_open, "every module went home"
    rail._buttons["active"].click(); pump(0.8)
    titles = win._module_search.result_titles()
    assert "Exposure" not in titles and "Sharpening" in titles, ("a module that is off is not listed", titles)
    # choosing another tab sends them home and puts the button out
    rail._buttons["exposure"].click(); pump(0.8)
    assert not win._module_search.active() and not rail._buttons["active"].isChecked() and rail._buttons["exposure"].isChecked()
    assert win._exposure_tool.parentWidget() is not None
    # nothing enabled in a fresh photo: the list says so
    c.reset_module("sharpening"); win._exposure_tool.power_toggled.emit(True); c.reset_module("exposure"); pump(1.0)
    rail._buttons["active"].click(); pump(0.8)
    assert "Sharpening" not in win._module_search.result_titles() and "Exposure" not in win._module_search.result_titles()
    print("OK enabled tab")
""")


def test_the_enabled_modules_tab_lists_what_is_doing_something():
    r = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "OK enabled tab" in r.stdout, r.stdout[-1500:] + r.stderr[-3000:]
