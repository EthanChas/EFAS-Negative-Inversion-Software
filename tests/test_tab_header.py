"""Each tool tab opens with its name and what it is for, and its modules sit under named groups (desktop/view/tab_header.py); the module search still gathers and returns them in place."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_WINDOW = textwrap.dedent(r'''
    import os, sys, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    p1 = os.path.join(work, "a.png")
    cv2.imwrite(p1, np.tile(np.linspace(0, 255, 300, dtype=np.uint8)[None, :, None], (200, 1, 3)))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view.tab_header import GroupHeader, TabHeader
    win = aw.AppWindow(); win.show(); win.resize(1500, 900); win.open_folder(work, prefer=p1)
    def pump(s):
        end = time.time() + s
        while time.time() < end:
            app.processEvents(); time.sleep(0.01)
    pump(1.5)
    cols = win._tab_columns
    names = {"negative": "CONVERT", "correction": "FRAME & CLEAN", "exposure": "TONE", "color": "COLOR", "detail": "DETAIL", "watermark": "FINISH", "metadata": "ROLL CARD", "plugins": "PLUGINS"}
    for tab, title in names.items():
        first = cols[tab].itemAt(0).widget()
        assert isinstance(first, TabHeader) and first.title_label.text() == title and first.hint_label.text().endswith("."), (tab, first)
    def shape(tab):
        out = []
        for i in range(cols[tab].count()):
            w = cols[tab].itemAt(i).widget()
            out.append("#" + w.title_label.text() if isinstance(w, TabHeader) else "-" + w.label.text() if isinstance(w, GroupHeader) else getattr(w, "_title", None))
        return [x for x in out if x]
    assert shape("detail") == ["#DETAIL", "-NOISE", "Chroma Denoise", "-SHARPNESS", "Local Contrast", "Sharpening", "Grain Sharpening", "Diffuse or Sharpen"], shape("detail")
    assert shape("exposure")[:3] == ["#TONE", "-LIGHT", "Exposure"] and "-CURVES AND RESPONSE" in shape("exposure")
    assert shape("correction")[:4] == ["#FRAME & CLEAN", "-FRAME", "Crop & Rotate", "-CLEAN"]
    before = {t: shape(t) for t in names}
    # the module search takes modules out of their tabs and puts them back where they were, headers and all
    win._module_search_edit.setText("sharp"); win._module_search.run_now(); pump(0.5)
    assert win._module_search.active()
    win._module_search_edit.setText(""); win._module_search.dismiss(); pump(0.5)
    assert {t: shape(t) for t in names} == before
    print("ok")
''')


def test_every_tab_has_a_heading_and_named_groups():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    r = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _WINDOW], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "ok" in r.stdout, r.stdout[-2000:] + r.stderr[-3000:]
