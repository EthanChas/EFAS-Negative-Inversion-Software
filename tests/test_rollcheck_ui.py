"""The roll consistency dialog and its menu entry, with synthetic frames standing in for decoded RAW files."""
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
    sys.path.insert(0, TESTS)
    import numpy as np
    from PyQt6.QtWidgets import QApplication
    import test_rollcheck as R
    from photoeditor.features.densitometry import roll_job
    from photoeditor.features.densitometry.linear import LinearScan
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view.roll_check_dialog import RollCheckDialog

    names = [f"IMG_{i}.cr2" for i in range(5)]
    frames = {n: R.frame(i, light=1.7 if i == 2 else 1.0) for i, n in enumerate(names)}
    roll_job.decode_linear_raw = lambda p, half_size=False: LinearScan(frames[os.path.basename(p)], R.INFO)
    roll_job.is_measurable = lambda p: p.endswith(".cr2")

    dlg = RollCheckDialog(["/x/" + n for n in names] + ["/x/notes.txt"], None)
    dlg._worker.wait(60000); app.processEvents()
    rep = dlg.report
    assert rep is not None and dlg.table.rowCount() == 5
    assert "1 of 5" in dlg.headline.text() and dlg.table.item(2, 1).text() == "Differs" and dlg.table.item(0, 1).text() == "Consistent"
    assert "Brighter" in dlg.table.item(2, 4).text()

    empty = RollCheckDialog(["/x/a.jpg"], None)
    assert "No RAW" in empty.headline.text() and empty._worker is None

    win = aw.AppWindow(); c = win.controller
    paths, ref = c.roll_check_inputs()
    assert isinstance(paths, list) and ref is None
    assert win._roll_check_action.text().startswith("Check Roll")
    win.close()
    print("ROLLCHECK UI OK")
'''.replace("TESTS", repr(TESTS)))


def test_roll_check_dialog_lists_the_odd_frame_out():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert "ROLLCHECK UI OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3000:]
