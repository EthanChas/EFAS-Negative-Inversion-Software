"""As in darktable, a module that is folded up, or whose tab is closed, stops drawing, editing and showing its masks: a shape being placed is let go, the shapes are no longer on the picture to edit,
a mask shown for a module goes, and Retouch's views of the picture are put back."""
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
    from photoeditor.features.masks import blend as B, model as M
    S.save({"scan_quality": False})
    rng = np.random.default_rng(0)
    img = np.clip(110 + rng.normal(0, 5, (600, 900, 3)), 0, 255).astype(np.uint8)
    path = os.path.join(folder, "a.png"); cv2.imwrite(path, img)
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=path)
    def pump(secs):
        end = time.time() + secs
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(3)
    ed = win._mask_editor; tool = ed.tool; rail = win._tool_rail; r = win._retouch_tool
    for panel in (win._exposure_tool, r):
        if not panel._expanded: panel.toggle()
    pump(0.6)

    # --- Retouch: a shape being placed, and a view of the picture, stop when its tab is closed
    rail._buttons["correction"].click(); pump(0.6)
    r._draw[M.CIRCLE].click(); app.processEvents()
    assert tool.creation is not None and ed._retouch
    r._view_scale.setChecked(True); pump(0.5)
    assert c.state.retouch_view == "scale"
    rail._buttons["correction"].click(); pump(0.6)         # the tab is closed
    assert tool.creation is None and not ed._retouch and not tool.active, "the shape being placed is let go and nothing is on the picture to edit"
    assert c.state.retouch_view == "" and r.view() == "", "the picture is as it was"

    # --- the same when another tab is opened in its place
    rail._buttons["correction"].click(); pump(0.6)
    r._edit.setChecked(True); app.processEvents()
    r._draw[M.CIRCLE].click(); app.processEvents()
    assert ed._retouch
    rail._buttons["exposure"].click(); pump(0.6)
    assert tool.creation is None and not ed._retouch, "opening another tab ends it too"

    # --- a module's own mask: edited and shown on the picture until its module is folded up
    box = win._blend_boxes["exposure"]
    i = box._mode.findData(B.DRAWN); box._mode.setCurrentIndex(i); box._mode.activated.emit(i); app.processEvents()
    win.begin_mask_drawing("exposure", M.CIRCLE)
    x, y = c.raw_to_display(np.array([[0.4, 0.5]], float))[0]
    tool.press(x, y, "left", set()); tool.release(x, y, "left", set()); pump(1.5)
    win.set_mask_display("exposure", True); pump(0.8)
    assert ed._module == "exposure" and tool.active and win._image_view._label._mask_show is not None
    win._exposure_tool.toggle(); pump(0.8)                 # the module is folded up
    assert ed._module is None and not tool.active and ed._show_key is None, "its mask is no longer edited or shown"
    assert win._image_view._label._mask_show is None
    win._exposure_tool.toggle(); pump(0.4)
    win.set_mask_editing("exposure", True); win.set_mask_display("exposure", True); pump(0.8)
    assert ed._module == "exposure"
    rail._buttons["exposure"].click(); pump(0.6)          # ... or its tab is closed
    assert ed._module is None and ed._show_key is None and not tool.active
    print("OK stopped")
""")


def test_masking_stops_when_a_module_is_folded_or_its_tab_is_closed():
    r = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "OK stopped" in r.stdout, r.stdout[-1500:] + r.stderr[-3500:]
