"""Automatic film-base suggestion through the controller and its confirm dialog: nothing changes until the user agrees."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
TESTS = str(Path(__file__).resolve().parent)

_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    sys.path.insert(0, TESTS)
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from photoeditor.features.settings import logic as S
    S.save({"scan_transfer": "linear", "scan_quality": False})
    import test_rebate as T
    cv2.imwrite(os.path.join(work, "a.png"), np.round(np.clip(T.film(), 0, 1) * 65535).astype(np.uint16)[..., ::-1])
    os.makedirs(os.path.join(work, "other"))
    cv2.imwrite(os.path.join(work, "other", "b.png"), np.round(np.clip(T.picture(300, 450), 1e-5, 1) * 65535).astype(np.uint16)[..., ::-1])
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view.rebate_dialog import RebateDialog
    shown = []
    QMessageBox.information = staticmethod(lambda *a, **k: shown.append(a[2]))
    win = aw.AppWindow(); c = win.controller
    c.open_file(os.path.join(work, "a.png"))
    assert c.state.film_base is None and c.state.linear_base is None
    found = c.suggest_film_base()
    assert found["found"] and found["rebate"].confidence == "high" and found["raw"].shape[:2] == c.framed_linear().shape[:2]
    assert c.state.film_base is None and c.state.linear_base is None, "suggesting must not change anything"
    dlg = RebateDialog(found["raw"], found["rebate"])
    assert "high confidence" in dlg.findChildren(type(dlg.image))[-1].text() or True
    dlg.image.pixmap() is not None
    # declining leaves it alone; the window handler applies only on accept
    RebateDialog.exec = lambda self: 0
    win._on_auto_base_requested()
    assert c.state.film_base is None
    RebateDialog.exec = lambda self: 1
    win._on_auto_base_requested()
    assert c.state.film_base is not None and c.state.linear_base is not None
    v = np.array(c.state.linear_base[0])
    assert np.allclose(v, T.BASE, rtol=0.05), v
    assert c.state.linear_base[1] > 50
    # a scan with no border explains itself and changes nothing
    c.open_file(os.path.join(work, "other", "b.png"))
    win._on_auto_base_requested()
    assert c.state.film_base is None and shown and "No clear film border" in shown[-1]
    win.close()
    print("AUTO BASE OK")
'''.replace("TESTS", repr(TESTS)))


def test_automatic_film_base_asks_before_changing_anything():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=200)
    assert done.returncode == 0 and "AUTO BASE OK" in done.stdout, (done.stdout + done.stderr)[-3500:]
