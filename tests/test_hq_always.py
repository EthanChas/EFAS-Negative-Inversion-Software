"""Settings > Always work in HQ: every photo opens with the HQ button already on; off by default."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    assert S.get("hq_always") is False, "off by default"
    paths = []
    for i in range(2):
        p = os.path.join(work, f"a{i}.png"); cv2.imwrite(p, np.random.default_rng(i).integers(30, 220, (200, 300, 3), dtype=np.uint8)); paths.append(p)
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    def pump(s):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    win = aw.AppWindow(); c = win.controller
    win.open_folder(work, prefer=paths[0]); pump(1.5)
    assert not c.state.hq_enabled and not win._hq_btn.isChecked()

    S.save({"scan_quality": False, "hq_always": True})
    assert S.get("hq_always") is True
    win.open_folder(work, prefer=paths[1]); pump(1.5)
    assert c.state.hq_enabled and win._hq_btn.isChecked() and win._hq_action.isChecked(), "opens in HQ"
    win._hq_btn.setChecked(False); pump(0.5)
    assert not c.state.hq_enabled, "it can still be switched off for the photo"
    win.close()
    print("HQ ALWAYS OK")
''')


def test_hq_always_setting():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert "HQ ALWAYS OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3500:]
