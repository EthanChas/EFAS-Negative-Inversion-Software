"""Extra > Grain Report in the window: the report for the open photo, with and without sharpening, and the dialog."""
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
    S.save({"scan_quality": False})
    rng = np.random.default_rng(5)
    noise = cv2.GaussianBlur(rng.standard_normal((1000, 1400, 3)).astype(np.float32), (0, 0), 1.6); noise /= noise.std()
    scan = np.clip(150 * (1 + 0.05 * noise), 0, 255).astype(np.uint8)    # a flat, mid-tone negative with a soft grain 5% strong
    path = os.path.join(folder, "a.png"); cv2.imwrite(path, scan)
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents()
    empty = c.grain_report(); assert not empty["ok"] and "Open a photo" in empty["message"]
    win.open_folder(folder, prefer=path)
    def pump(cond=lambda: False, secs=20.0):
        end = time.time() + secs
        while time.time() < end:
            app.processEvents()
            if cond(): return True
            time.sleep(0.01)
        return cond()
    assert pump(lambda: c.state.image_rgb is not None); pump(secs=1.0)
    s = c.state

    r = c.grain_report()
    assert r["ok"] and r["name"] == "a.png" and r["size"] == (1400, 1000) and r["reading"].patches
    assert 3.0 < r["reading"].strength < 8.0 and r["reading"].width > 1.0, (r["reading"].strength, r["reading"].width)
    assert r["verdict"] in ("partly resolved", "resolved") and r["advice"]
    assert r["effect"] is not None and "off" in r["effect_note"] and r["effect_text"] == "", "no detail module is on: nothing to compare"
    assert abs(r["effect"].ratio - 1.0) < 0.05, r["effect"].ratio

    c.set_sharpen(1.0, 1.0, 0.0, s.sharpen_method); pump(secs=1.0)
    r2 = c.grain_report()
    assert r2["effect"].ratio > 1.2 and "sharpening is making the grain" in r2["effect_text"] and "Sharpening" in r2["effect_text"], (r2["effect"].ratio, r2["effect_text"])
    assert set(r2["effect"].by_module) == {"sharpen"} and r2["crops"][0].shape == (256, 256, 3)
    assert not np.array_equal(r2["crops"][0], r2["crops"][1]), "the two crops differ"
    before = s.image_rgb.copy()

    # the roll's format gives the size of a pixel on the film
    from photoeditor.features.metadata.roll import RollCard
    c.set_roll(RollCard(format="35mm"))
    r3 = c.grain_report()
    assert abs(r3["pitch_um"] - 36000 / 1400) < 1e-6

    # the dialog, from the menu: it says the numbers and changes nothing
    from photoeditor.desktop.view.grain_report_dialog import GrainReportDialog
    win._grain_report_action.trigger(); app.processEvents()
    dialog = win._grain_report
    assert isinstance(dialog, GrainReportDialog) and "Grain Report" in dialog.windowTitle()
    short, text = dialog._summary.text(), dialog._details.text()
    assert "a.png" in short and "Grain: " in short and "Your edits: boosting" in short and "sharpening is too strong" in short and len(short) < 900, short
    assert not dialog._details.isVisibleTo(dialog) and dialog._toggle.text() == "Details"
    dialog._toggle.setChecked(True); app.processEvents()
    assert dialog._details.isVisibleTo(dialog), "Details opens the rest"
    assert "never adds grain" in text and "Do your edits keep the grain?" in text and "35 mm" in text and "&micro;m" in text, text[:400]
    assert GrainReportDialog.edits_word(r)[0] == "off" and GrainReportDialog.edits_word({"effect": None})[0] == "off"
    assert len(dialog._pictures) == 2 and np.array_equal(s.image_rgb, before) and s.sharpen_amount == 1.0, "nothing was changed"
    dialog.close()

    # nothing flat to measure: said so, no crash
    cv2.imwrite(os.path.join(folder, "b.png"), np.tile(np.arange(1400, dtype=np.uint8)[None, :, None], (1000, 1, 3)))
    win.open_folder(folder, prefer=os.path.join(folder, "b.png")); pump(lambda: c.state.image_path and c.state.image_path.endswith("b.png"), 20); pump(secs=1.0)
    r4 = c.grain_report()
    assert r4["ok"] and not r4["reading"].patches and r4["reading"].notes and r4["effect"] is None
    assert "Nothing to measure" in GrainReportDialog._html(r4)
    win.close()
    print("GRAIN REPORT OK")
""")


def test_the_grain_report_in_the_window():
    done = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=400, env={**os.environ, "PYTHONPATH": SRC, "PHOTOEDITOR_AUDIO": "off"})
    assert "GRAIN REPORT OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3500:]
