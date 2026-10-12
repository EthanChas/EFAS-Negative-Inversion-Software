"""The text read-out under the histogram in the running editor: it follows the picture and the Negative tab's grading."""
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r'''
    import os, sys, time, faulthandler
    faulthandler.enable()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication, QLabel
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    DATA = os.environ["PHOTOEDITOR_DATA_DIR"]
    folder = os.path.join(DATA, "photos"); os.makedirs(folder)
    rng = np.random.default_rng(1)
    img = cv2.GaussianBlur(rng.random((300, 400, 3)).astype(np.float32), (0, 0), 20)
    A = os.path.join(folder, "a.png"); cv2.imwrite(A, (30 + 190 * (img - img.min()) / np.ptp(img)).astype(np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view.stats_panel import ChannelStatsPanel
    from photoeditor.features.densitometry.quality import ScanQuality
    from photoeditor.features.whitebalance import readout as R

    def pump(cond=lambda: False, secs=15.0):
        end = time.time() + secs
        while time.time() < end:
            app.processEvents()
            if cond(): return True
            time.sleep(0.01)
        return cond()

    def texts(panel):
        return [l.text() for l in panel.findChildren(QLabel)]

    # ---- the panel on its own: a few compact rows
    panel = ChannelStatsPanel(); panel.show()
    stats = {k: {"avg": 120.0, "shadow_clip_pct": 0.0, "highlight_clip_pct": 1.5} for k in "rgb"}
    ramp = np.repeat(np.arange(256, dtype=np.uint8)[None, :, None], 3, axis=2).repeat(8, axis=0)
    panel.set_stats(stats, "Well exposed", 127.5)
    assert panel._rows["Exposure"][1].text() == "Well exposed, 128" and panel._rows["Contrast"][1].text() == "-"
    panel.set_stats(stats, "Well exposed", 127.5, R.tonal_readout(ramp))
    labels = [panel._rows[k][0].text() for k in panel._rows]
    assert labels == ["Exposure", "Contrast", "Range", "Clipping", "Colour", "Saturation", "Channels"], labels
    assert panel._rows["Exposure"][1].text() in ("Well exposed, 128", "Well exposed, 127")
    assert panel._rows["Range"][1].text().startswith("Full ")
    assert "120" in panel._rows["Channels"][1].text() and panel._rows["Channels"][1].text().count("120") == 3
    assert "average 120" in panel._rows["Channels"][1].toolTip() and "1.5%" in panel._rows["Channels"][1].toolTip()
    assert "median" in panel._rows["Exposure"][0].toolTip() and "Dark (below 64)" in panel._rows["Range"][1].toolTip(), "the detail is in the tooltips"
    n = len(texts(panel))
    panel.set_stats(stats, "Well exposed", 127.5, R.tonal_readout(ramp))
    assert len(texts(panel)) == n
    assert len([t for t in texts(panel) if t.isupper() and len(t) > 3]) == 0, "no section headings"
    panel.set_scan(ScanQuality("good", "Scan quality is good", "The whole negative is well above the noise floor."), ("Colour neg, inverted, auto base", "Recognised as: Colour negative, inverted"))
    assert panel._quality_head.isVisible() and "Scan quality is good" in panel._quality_head.text() and "noise floor" in panel._quality_head.toolTip()
    assert panel._negative.text() == "Colour neg, inverted, auto base" and "Recognised as" in panel._negative.toolTip()
    panel.set_scan(None, ("", ""))
    assert not panel._quality_head.isVisible() and not panel._negative.isVisible()
    panel.clear()
    assert panel._rows["Exposure"][1].text() == "-"
    assert len(panel.findChildren(QLabel)) <= 18, "a compact block"

    # ---- in the app: it follows the photo, and the grading follows the Negative tab
    win = aw.AppWindow(); win.resize(1500, 1000); win.show(); app.processEvents()
    win.open_folder(folder, prefer=A)
    c = win.controller
    assert pump(lambda: c.state.readout is not None and c.state.image_rgb is not None)
    pump(secs=0.5)
    sp = win._stats_panel
    first = texts(sp)
    assert "Contrast" in first and "Colour" in first
    assert c.state.readout["mean"] > 0
    c.set_exposure_ev(1.5)
    assert pump(lambda: texts(sp) != first)
    quality, (summary, tip) = c.scan_grading()
    assert summary and "base" in summary and "Inversion: standard" in tip
    c.state.film_base = (210, 130, 80)
    win._refresh_scan_grading()
    assert sp._negative.text().endswith("sampled base") and "sampled (210, 130, 80)" in sp._negative.toolTip()
    c.state.film_base = None
    win._refresh_scan_grading()
    assert sp._negative.text().endswith("auto base")
    print("HISTOGRAM TEXT OK"); sys.stdout.flush(); os._exit(0)
''')


def test_histogram_text_readout():
    data = tempfile.mkdtemp()
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""), PHOTOEDITOR_DATA_DIR=data)
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=600)
    assert "HISTOGRAM TEXT OK" in done.stdout, done.stdout[-1500:] + done.stderr[-4000:]
