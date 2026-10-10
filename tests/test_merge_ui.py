"""The Merge Scans dialog end to end: bracket and per-colour merges run in the background, are saved with their sidecar, and the editor then reads the merged
scan as exact linear light."""
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
    import numpy as np
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": True})
    import test_merge as T
    from photoeditor.features.densitometry import merge, merge_job
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view.merge_dialog import MergeDialog

    truth = T.field(4)
    times = {"s1.cr2": 1.0, "s2.cr2": 4.0, "s3.cr2": 16.0}
    scans = {name: T.capture(truth, t, i) for i, (name, t) in enumerate(times.items())}
    for name in list(times) + ["r.cr2", "g.cr2", "b.cr2"]:
        open(os.path.join(work, name), "wb").write(b"x")
    ch = T.field(5)
    for name, c in (("r.cr2", 0), ("g.cr2", 1), ("b.cr2", 2)):
        rgb = np.zeros_like(ch); rgb[...] = ch * 0.05; rgb[..., c] = ch[..., c]
        scans[name] = T.LinearScan(rgb.astype(np.float32), T.info())
    merge_job.decode_linear_raw = lambda p: scans[os.path.basename(p)]
    merge_job.capture_info = lambda p: {"exposure_time": times.get(os.path.basename(p))}

    win = aw.AppWindow(); c = win.controller
    opened = []
    dlg = MergeDialog(win)
    dlg.open_requested.connect(opened.append)
    dlg.add_paths([os.path.join(work, n) for n in times])
    assert dlg.times() == [1.0, 4.0, 16.0], dlg.times()
    assert dlg.output.text().endswith("s1_merged.tif")
    dlg._start(); dlg._worker.wait(60000); app.processEvents()
    out = os.path.join(work, "s1_merged.tif")
    assert os.path.isfile(out) and merge.is_merged_scan(out), dlg.status.toPlainText()
    assert "times lower" in dlg.status.toPlainText() and dlg.open_button.isEnabled()
    back = merge.load_merged(out)
    dark = truth[..., 1] < 0.02
    err = np.abs(back.rgb[..., 1] - truth[..., 1])[dark].mean()
    assert err < 3e-4, err

    # the editor reads it as exact linear light
    dlg._open_result(); assert opened == [out]
    c.open_file(out)
    c.wait_linear_workers(60000); app.processEvents()
    assert c.linear_ready(), c.scan_quality()
    lin = c._linear[1]
    assert lin.info.measured and lin.info.encoding == "merged-linear"

    # a missing exposure time is refused with a plain message
    d2 = MergeDialog(win)
    d2.add_paths([os.path.join(work, "s1.cr2"), os.path.join(work, "s2.cr2")])
    merge_job.capture_info = lambda p: {"exposure_time": None}
    d2.table.cellWidget(0, 1).setValue(0.0)
    d2.output.setText(os.path.join(work, "x.tif")); d2._start(); d2._worker.wait(60000); app.processEvents()
    assert "exposure time" in d2.status.toPlainText() and not os.path.exists(os.path.join(work, "x.tif"))

    # refuses to overwrite a scan that is not a merge result
    d3 = MergeDialog(win)
    d3.add_paths([os.path.join(work, "s1.cr2"), os.path.join(work, "s2.cr2")])
    d3.output.setText(os.path.join(work, "s1.cr2")); d3._start()
    assert "already exists" in d3.status.toPlainText() and d3._worker is None

    # one light per colour
    d4 = MergeDialog(win)
    d4.mode.setCurrentIndex(1)
    for e, n in zip(d4.channel_edits, ("r.cr2", "g.cr2", "b.cr2")):
        e.setText(os.path.join(work, n))
    assert d4.output.text().endswith("r_merged-colour.tif")
    d4._start(); d4._worker.wait(60000); app.processEvents()
    m = merge.load_merged(os.path.join(work, "r_merged-colour.tif"))
    assert m is not None
    for k in range(3):
        assert np.abs(m.rgb[..., k] / ch[..., k] - 1).mean() < 0.01, k
    win.close()
    print("MERGE UI OK")
'''.replace("TESTS", repr(TESTS)))


def test_merge_dialog_end_to_end():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert "MERGE UI OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3000:]
