"""Opening the Masks panel shows every mask on the picture, and the Shapes and Groups folders show all they hold when clicked."""
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
    from photoeditor.features.masks import model as M
    S.save({"scan_quality": False})
    p = os.path.join(folder, "a.png"); cv2.imwrite(p, np.full((300, 450, 3), 110, np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=p)
    def pump(secs):
        end = time.time() + secs
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(3)
    a = c.add_mask_form(M.CIRCLE, M.circle(0.3, 0.3)); b = c.add_mask_form(M.CIRCLE, M.circle(0.7, 0.6)); pump(0.5)
    assert a and b and a != b
    manager, editor = win._mask_manager, win._mask_editor
    assert set(manager.all_ids()) == {a, b}
    manager.set_expanded(False); pump(0.5)
    manager.set_expanded(True); pump(0.5)
    assert editor.tool.visible == {a, b}, ("opening the panel shows every mask", editor.tool.visible)
    # clicking the Shapes folder shows all the shapes too, from an empty picture of the tool
    manager.set_expanded(False); pump(0.5)
    manager.picked.emit([], 0); pump(0.2)
    shapes = next(manager._tree.topLevelItem(i) for i in range(manager._tree.topLevelItemCount()) if manager._tree.topLevelItem(i).text(0) == "Shapes")
    shapes.setSelected(True); pump(0.3)
    assert editor.tool.visible == {a, b}, ("the Shapes folder", editor.tool.visible)
    print("OK")
""")


def test_masks_panel_shows_all_masks():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-3000:]
