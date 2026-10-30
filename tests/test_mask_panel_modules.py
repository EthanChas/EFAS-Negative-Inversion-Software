"""The Masks panel on the left: each module that was blended through a drawn mask has a folder of its own holding its shapes (named Brush, Curve...), a click on a shape that is already
picked shows it again, and the eye shows every mask on the picture."""
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
    from photoeditor.features.masks import model as M, blend as B
    S.save({"scan_quality": False})
    p = os.path.join(folder, "a.png"); cv2.imwrite(p, np.full((300, 450, 3), 110, np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=p)
    def pump(secs):
        end = time.time() + secs
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(3)
    mgr, ed = win._mask_manager, win._mask_editor
    def items():
        out = []; stack = [mgr._tree.topLevelItem(i) for i in range(mgr._tree.topLevelItemCount())]
        while stack:
            it = stack.pop(0); out.append(it); stack.extend(it.child(i) for i in range(it.childCount()))
        return out
    def top(text):
        return next((mgr._tree.topLevelItem(i) for i in range(mgr._tree.topLevelItemCount()) if mgr._tree.topLevelItem(i).text(0) == text), None)
    def children(item):
        return [item.child(i).text(0).split("  (")[0] for i in range(item.childCount())]
    def draw(key, kind, fx, fy):
        box = win._blend_boxes[key]
        if c.blend_of(key).mode != B.DRAWN:
            i = box._mode.findData(B.DRAWN); box._mode.setCurrentIndex(i); box._mode.activated.emit(i); pump(0.3)
        win.begin_mask_drawing(key, kind)
        x, y = c.raw_to_display(np.array([[fx, fy]], float))[0]
        assert ed.tool.press(x, y, "left", set(), 8.0); ed.tool.release(x, y, "left", set(), 8.0); pump(0.6)

    # --- a module's shapes are named for what they are, and sit under a folder named for the module
    draw("sharpening", M.ELLIPSE, 0.3, 0.4)
    assert [f.name for f in c.mask_set().shapes()] == ["Ellipse"], [f.name for f in c.mask_set().shapes()]
    folder_item = top("Sharpening mask")
    assert folder_item is not None and children(folder_item) == ["Ellipse"], [i.text(0) for i in items()]
    draw("sharpening", M.CIRCLE, 0.7, 0.5); draw("sharpening", M.CIRCLE, 0.5, 0.8)
    folder_item = top("Sharpening mask")
    assert children(folder_item) == ["Ellipse", "Circle", "Circle 2"], children(folder_item)
    assert [g.name for g in c.mask_set().groups()] == ["Sharpening mask"]
    assert top("Shapes").childCount() == 0 and top("Groups").childCount() == 0, "what a module made is not listed twice"
    draw("exposure", M.CIRCLE, 0.2, 0.2)
    assert children(top("Exposure mask")) == ["Circle"] and children(top("Sharpening mask")) == ["Ellipse", "Circle", "Circle 2"], "each module has its own folder and numbers its own"
    # a shape of the Masks panel's own is under Shapes, as before
    mgr.draw_requested.emit(M.CIRCLE); x, y = c.raw_to_display(np.array([[0.9, 0.9]], float))[0]
    ed.tool.press(x, y, "left", set(), 8.0); ed.tool.release(x, y, "left", set(), 8.0); pump(0.6)
    assert top("Shapes").childCount() == 1, [i.text(0) for i in items()]

    # --- clicking a folder shows its whole mask
    mgr._tree.clearSelection(); top("Sharpening mask").setSelected(True); pump(0.5)
    shown = set(c.mask_set().flatten(c.blend_of("sharpening").mask_id))
    assert ed.tool.visible == shown and len(shown) == 3, (ed.tool.visible, shown)

    # --- a click on a shape that is already picked shows it again after a module's Mask box took the picture
    first = top("Sharpening mask").child(0)
    mgr._tree.clearSelection(); first.setSelected(True); pump(0.5)
    first_id = (first.data(0, 256) or {})["id"]
    assert ed.tool.visible == {first_id} and ed._manager
    win.begin_mask_drawing("exposure", M.CIRCLE); ed.tool.cancel(); ed._take_over(module="exposure"); ed._apply(); pump(0.3)
    assert ed.tool.visible != {first_id} and not ed._manager, "the module has the picture"
    time.sleep(0.5)
    first = top("Sharpening mask").child(0)
    mgr._tree.itemClicked.emit(first, 0); pump(0.5)
    assert ed.tool.visible == {first_id} and ed._manager, ("clicking the picked shape shows it", ed.tool.visible)

    # --- the eye: every mask, whatever is picked
    everything = set(mgr.all_ids())
    assert len(everything) >= 5
    mgr._eye_btn.setChecked(True); pump(0.5)
    assert ed.tool.visible == everything, ("the eye shows every mask", ed.tool.visible)
    first = top("Sharpening mask").child(0)
    mgr._tree.clearSelection(); first.setSelected(True); pump(0.5)
    assert ed.tool.visible == everything, "and still does when one is picked"
    mgr._eye_btn.setChecked(False); pump(0.5)
    assert ed.tool.visible == {first_id}, ("eye off: back to what is picked", ed.tool.visible)
    mgr._eye_btn.setChecked(True); pump(0.3)
    mgr.set_expanded(False); pump(0.5)
    assert not mgr.all_shown(), "closing the panel puts the eye down too"
    print("OK mask panel modules")
""")


def test_each_modules_mask_has_its_folder_and_the_eye_shows_all():
    r = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "OK mask panel modules" in r.stdout, r.stdout[-1500:] + r.stderr[-3000:]
