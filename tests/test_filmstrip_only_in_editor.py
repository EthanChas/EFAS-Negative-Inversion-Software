"""The filmstrip belongs to the editor: it must stay hidden in the Workbench (and the other views) whatever happens to the photos in it - photos taken out or deleted, a folder chosen in the
Library list, the side panels toggled - and be back when the editor is."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False, "advanced_mode": False})
    paths = []
    for i in range(4):
        p = os.path.join(work, f"p{i}.png"); cv2.imwrite(p, np.random.default_rng(i).integers(30, 220, (60, 90, 3), dtype=np.uint8)); paths.append(p)
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.show(); win.open_folder(work)
    def pump(s):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(0.8)
    strip = win._filmstrip
    win.set_view("editor"); pump(0.3)
    assert strip.isVisible() and len(strip.paths()) == 4, "the editor shows the strip"

    win.set_view("lighttable"); pump(0.3)
    assert not strip.isVisible(), "the Workbench has no strip"
    win._after_photos_left([paths[0]], "removed"); pump(0.2)
    assert len(strip.paths()) == 3 and not strip.isVisible(), "photos taken out (or deleted) from the Workbench must not bring the strip back"
    win._on_library_folder_selected(work); pump(0.3)
    assert len(strip.paths()) >= 3 and not strip.isVisible(), "choosing a folder in the Workbench's Library list must not either"
    win.toggle_panels(); pump(0.2); win.toggle_panels(); pump(0.2)
    assert not strip.isVisible(), "nor hiding and showing the side panels"
    strip.load_folder(paths[:2]); assert not strip.isVisible()

    win.set_view("classroom"); pump(0.2); win._after_photos_left([paths[1]], "x"); assert not strip.isVisible(), "nor in the Classroom"
    win.set_view("editor"); pump(0.3)
    assert strip.isVisible(), "back in the editor the strip is back"
    win.toggle_panels(); pump(0.2)
    assert not strip.isVisible(), "hidden with the panels in the editor, as before"
    win.toggle_panels(); pump(0.2)
    assert strip.isVisible()
    win.close()
    print("OK")
""")


def test_the_filmstrip_stays_out_of_the_workbench():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC, "PHOTOEDITOR_AUDIO": "off"})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1800:] + out.stderr[-3000:]
