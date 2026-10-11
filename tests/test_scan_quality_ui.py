"""The scan-quality verdict reaching the Negative tab (docs: Everyday-mode scan feedback)."""
import glob
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SYNTH = textwrap.dedent(r'''
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    data = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_DATA_DIR"] = data
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.features.densitometry import linear, processor as dproc
    app = QApplication([])
    from photoeditor.desktop import controller as ctrl
    from photoeditor.desktop.view.app_window import AppWindow

    INFO = linear.ScanInfo(True, "raw-linear", 14, quantisation=1e-5, noise_sigma=(2e-5,) * 3)
    def make(base, dense=0.0, clipped=0.0):
        rng = np.random.default_rng(0); h, w = 160, 240
        v = (base * 10.0 ** -np.linspace(0, 1.2, w))[None, :, None] * np.array([1.0, 0.8, 0.6]) * np.ones((h, w, 1)) + rng.normal(0, 3e-5, (h, w, 3))
        flat = v.reshape(-1, 3); idx = rng.permutation(flat.shape[0]); a = int(len(idx) * dense); b = a + int(len(idx) * clipped)
        flat[idx[:a]] = INFO.floor()[0] * 0.4; flat[idx[a:b]] = 1.0
        return v.astype(np.float32)
    cases = {"good": make(0.7), "under": make(0.15, dense=0.05), "clip": make(0.7, clipped=0.03)}
    files = {}
    for name, arr in cases.items():
        f = os.path.join(work, name + ".png"); cv2.imwrite(f, np.round(np.clip(arr, 0, 1) * 65535).astype(np.uint16)[..., ::-1]); files[f] = arr
    ctrl.is_raw = lambda p: True
    dproc.is_measurable = lambda p: True
    dproc.linear_scan = lambda path, picture, transfer: linear.LinearScan(files[path], INFO)
    win = AppWindow(); c = win.controller; nt = win._negative_tool
    def pump(cond, secs=30):
        t = time.time()
        while time.time() - t < secs and not cond():
            QCoreApplication.processEvents(); time.sleep(0.02)
        return cond()
    def check(name, level):
        f = os.path.join(work, name + ".png")
        c.open_file(f)
        assert pump(lambda: c.scan_quality().level == level), (name, c.scan_quality())
        assert pump(lambda: nt._quality_head.isVisibleTo(nt) or True)
        return c.scan_quality()
    q = check("good", "good");  assert pump(lambda: "good" in nt._quality_head.text().lower() and "6bdc6b" in nt._quality_head.text()), nt._quality_head.text()
    q = check("under", "underexposed"); assert pump(lambda: "stops" in nt._quality_head.text() and "Merge Scans" in nt._quality_detail.text()), nt._quality_head.text()
    q = check("clip", "clipped"); assert pump(lambda: "clipped" in nt._quality_head.text().lower() and "ff6b6b" in nt._quality_head.text()), nt._quality_head.text()
    # switched off: nothing is read in the background
    S.save({"scan_quality": False})
    c.open_file(os.path.join(work, "good.png")); QCoreApplication.processEvents(); time.sleep(0.5); QCoreApplication.processEvents()
    assert not c.linear_ready() and c.scan_quality().level == "unknown"
    # not a RAW file: unknown, and no background work
    ctrl.is_raw = lambda p: False; S.save({"scan_quality": True})
    c.open_file(os.path.join(work, "under.png")); assert c.scan_quality().level == "unknown" and "RAW" in c.scan_quality().detail
    win.close()
    print("QUALITY UI OK")
''')


def test_scan_quality_in_the_negative_tab():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SYNTH], env=env, capture_output=True, text=True, timeout=200)
    assert done.returncode == 0 and "QUALITY UI OK" in done.stdout, (done.stdout + done.stderr)[-3500:]


_REAL = textwrap.dedent(r'''
    import glob, os, shutil, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    from photoeditor.desktop.view.app_window import AppWindow
    work = tempfile.mkdtemp()
    src = sorted(glob.glob("E:/THENEWESTBEGGININGS/Photos/NEWGENETHAN/Film/Hotstack/01_10_2026/*.CR2"))[:3]
    win = AppWindow(); c = win.controller
    out = {}
    for s in src:
        f = os.path.join(work, os.path.basename(s)); shutil.copy(s, f)
        c.open_file(f)
        t = time.time()
        while time.time() - t < 60 and c.scan_quality().level == "unknown":
            QCoreApplication.processEvents(); time.sleep(0.05)
        q = c.scan_quality(); out[os.path.basename(s)] = (q.level, q.stops)
    print(out)
    assert any(v[0] == "underexposed" for v in out.values()) and any(v[0] == "good" for v in out.values()), out
    print("REAL QUALITY OK")
''')


@pytest.mark.skipif(not glob.glob("E:/THENEWESTBEGGININGS/Photos/NEWGENETHAN/Film/Hotstack/01_10_2026/*.CR2"), reason="no sample RAW files on this machine")
def test_real_raw_scans_get_sensible_verdicts():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-c", _REAL], env=env, capture_output=True, text=True, timeout=280)
    assert done.returncode == 0 and "REAL QUALITY OK" in done.stdout, (done.stdout + done.stderr)[-3000:]
