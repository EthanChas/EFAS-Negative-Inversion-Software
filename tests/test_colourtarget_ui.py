"""The colour target dialog end to end on a synthetic scanned target: grid, reference file, fit, and saving the result with a camera set-up."""
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
    from PyQt6.QtWidgets import QApplication, QMessageBox, QInputDialog
    from photoeditor.features.settings import logic as S
    S.save({"scan_transfer": "linear", "scan_quality": False})
    import test_colourtarget as T
    from photoeditor.features.densitometry import colourtarget as ct
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view.colour_target_dialog import ColourTargetDialog
    from photoeditor.desktop.view.profile_dialogs import SetupsDialog

    cols, rows = 22, 12
    t, xyz = T.synthetic(n=cols * rows, noise=0.001)
    H, W = 480, 880
    img = np.full((H, W, 3), 0.002)
    clear = np.array([0.8, 0.7, 0.6])
    img[:, :] = clear
    left, top, right, bottom = 0.04 * W, 0.08 * H, 0.96 * W, 0.80 * H
    cw, ch = (right - left) / cols, (bottom - top) / rows
    for k in range(cols * rows):
        r, c = divmod(k, cols)
        img[int(top + r * ch):int(top + (r + 1) * ch), int(left + c * cw):int(left + (c + 1) * cw)] = t[k] * clear
    f = os.path.join(work, "target.png")
    cv2.imwrite(f, np.round(np.clip(img, 0, 1) * 65535).astype(np.uint16)[..., ::-1])
    ref = os.path.join(work, "it8.txt")
    open(ref, "w").write(T.cgats(xyz, ct.grid_ids(cols, rows)))

    win = aw.AppWindow(); c = win.controller
    shown = []
    QMessageBox.information = staticmethod(lambda *a, **k: shown.append(a[2]))

    # without a photo or a clear-light sample the dialog says what to do
    d0 = ColourTargetDialog(c)
    assert "Open the photo" in d0.report.toPlainText() and not d0.fit_button.isEnabled()
    c.open_file(f)
    d1 = ColourTargetDialog(c)
    assert "clear light" in d1.report.toPlainText() and not d1.fit_button.isEnabled()
    problems = c.set_linear_reference("clear", (int(W * 0.5), int(H * 0.93)), 12)
    assert not problems, problems

    dlg = ColourTargetDialog(c)
    assert dlg.fit_button.isEnabled() and dlg.image.pixmap() is not None
    dlg._fit()
    assert "Load the reference" in dlg.report.toPlainText()
    dlg.load_reference(os.path.join(work, "missing.txt"))
    assert dlg.reference is None
    dlg.load_reference(ref)
    assert dlg.reference is not None and "264 patches" in dlg.ref_label.text()
    for key, v in (("Left", 4.0), ("Top", 8.0), ("Right", 96.0), ("Bottom", 80.0)):
        dlg.edges[key].setValue(v)
    dlg._fit()
    text = dlg.report.toPlainText()
    assert dlg.fit is not None and dlg.fit.verdict == "excellent" and "264 patches" in text and dlg.save_button.isEnabled(), text
    assert dlg.fit.de_after.mean() < 0.6

    # a badly placed grid is reported, not hidden
    dlg.edges["Left"].setValue(30.0); dlg._fit()
    assert dlg.fit is None or dlg.fit.verdict != "excellent"
    dlg.edges["Left"].setValue(4.0); dlg._fit()
    assert dlg.fit.verdict == "excellent"

    QInputDialog.getText = staticmethod(lambda *a, **k: ("Copy stand", True))
    dlg.setup_box.setCurrentIndex(dlg.setup_box.count() - 1)
    dlg._save()
    listed = c.setup_store().list()
    assert len(listed) == 1 and listed[0]["name"] == "Copy stand" and shown and "unchanged" in shown[-1]
    saved = c.setup_store().load(listed[0]["id"]).calibration["colour"]
    assert saved["patches"] == 264 and saved["illuminant"] == "D50" and saved["after"]["mean"] < 0.6 and len(saved["matrix"]) == 3

    sd = SetupsDialog(c)
    sd._show()
    assert "Colour accuracy" in sd.detail.toPlainText() and "excellent" in sd.detail.toPlainText()
    win.close()
    print("COLOUR UI OK")
'''.replace("TESTS", repr(TESTS)))


def test_colour_target_dialog_fits_and_saves_to_a_setup():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert "COLOUR UI OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3000:]
