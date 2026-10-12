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
        return [l.text() for l in panel.findChildren(QLabel) if l.isVisibleTo(panel) or True]

    # ---- the panel on its own
    panel = ChannelStatsPanel(); panel.show()
    stats = {k: {"avg": 120.0, "shadow_clip_pct": 0.0, "highlight_clip_pct": 1.5} for k in "rgb"}
    ramp = np.repeat(np.arange(256, dtype=np.uint8)[None, :, None], 3, axis=2).repeat(8, axis=0)
    panel.set_stats(stats, "Well exposed", 127.5)
    assert not panel._contrast_head.isVisible(), "without a read-out the extra sections stay hidden"
    panel.set_stats(stats, "Well exposed", 127.5, R.tonal_readout(ramp))
    t = texts(panel)
    for expected in ("EXPOSURE", "CONTRAST", "CLIPPING", "COLOUR", "Median", "Range", "Dark / mid / light", "Contrast", "Spread", "Deviation", "Blocked shadows", "Blown highlights", "Average", "Saturation"):
        assert expected in t, (expected, t)
    assert panel._contrast_head.isVisible() and panel._exposure_value.text().startswith("Well exposed")
    assert panel._value_labels["r"].text() == "avg 120 · clip 0.0/1.5%"
    n = len(texts(panel))
    panel.set_stats(stats, "Well exposed", 127.5, R.tonal_readout(ramp))
    assert len(texts(panel)) == n, "refilling replaces the rows, it does not pile them up"
    panel.set_scan(ScanQuality("good", "Scan quality is good", "The whole negative is well above the noise floor."), [("Type", "Colour negative, inverted"), ("Film base", "Auto-estimated"), ("Inversion", "Standard")])
    t = texts(panel)
    assert "SCAN" in t and any("Scan quality is good" in x for x in t) and "Film base" in t and "Colour negative, inverted" in t
    panel.set_scan(None, [])
    assert not panel._scan_head.isVisible() and not panel._quality_head.isVisible()
    panel.clear()
    assert panel._exposure_value.text() == "-" and not panel._contrast_head.isVisible()

    # ---- in the app: it follows the photo, and the grading follows the Negative tab
    win = aw.AppWindow(); win.resize(1500, 1000); win.show(); app.processEvents()
    win.open_folder(folder, prefer=A)
    c = win.controller
    assert pump(lambda: c.state.readout is not None and c.state.image_rgb is not None)
    pump(secs=0.5)
    sp = win._stats_panel
    first = texts(sp)
    assert "Spread" in first and "CONTRAST" in first and "SCAN" in first
    assert c.state.readout["mean"] > 0
    c.set_exposure_ev(1.5)
    assert pump(lambda: c.state.readout["mean"] > 0 and texts(sp) != first)
    quality, lines = c.scan_grading()
    keys = [k for k, _v in lines]
    assert "Film base" in keys and "Inversion" in keys
    assert dict(lines)["Inversion"] == "Standard"
    c.state.film_base = (210, 130, 80)
    win._refresh_scan_grading()
    assert "Sampled (210, 130, 80)" in texts(sp)
    c.state.film_base = None
    win._refresh_scan_grading()
    assert "Auto-estimated" in texts(sp) and "Sampled (210, 130, 80)" not in texts(sp)
    print("HISTOGRAM TEXT OK"); sys.stdout.flush(); os._exit(0)
''')


def test_histogram_text_readout():
    data = tempfile.mkdtemp()
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""), PHOTOEDITOR_DATA_DIR=data)
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=600)
    assert "HISTOGRAM TEXT OK" in done.stdout, done.stdout[-1500:] + done.stderr[-4000:]
