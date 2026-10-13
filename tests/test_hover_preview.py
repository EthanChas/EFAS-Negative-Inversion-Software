"""Hovering a preset in the Presets list shows it on the picture; nothing is applied, and moving away puts the picture back."""
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
    from PyQt6.QtCore import QEvent
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    p = os.path.join(work, "a.png")
    cv2.imwrite(p, np.random.default_rng(0).integers(60, 200, (200, 300, 3), dtype=np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.show(); win.open_folder(work, prefer=p)
    c = win.controller
    def pump(s):
        end = time.time() + s
        while time.time() < end:
            app.processEvents(); time.sleep(0.01)
    pump(1.5)
    shown = []
    real = win._image_view.update_pixels
    win._image_view.update_pixels = lambda px: (shown.append(px.copy()), real(px))[1]

    # a preset that makes the picture much brighter
    c.set_exposure_ev(1.5); pump(0.6); c.save_look_preset("Bright"); pump(0.2)
    c.set_exposure_ev(0.0); pump(0.6)
    plain = c.state.image_rgb.copy()
    assert c.state.exposure_ev == 0.0 and c.look_presets() == ["Bright"]
    history = len(c.state.history)

    # the controller can render a look without applying it
    img = c.preview_look_preset("Bright")
    assert img is not None and img.shape == plain.shape and img.mean() > plain.mean() + 10
    assert c.state.exposure_ev == 0.0 and len(c.state.history) == history and np.array_equal(c.state.image_rgb, plain)
    assert c.preview_look_preset("nope") is None and c.preview_look({}) is None

    # hovering the list shows it after a short rest, and says so
    panel = win._presets_panel
    shown.clear()
    panel.preview_requested.emit("Bright"); pump(0.6)
    assert shown and shown[-1].mean() > plain.mean() + 10 and win._preset_previewing
    assert "Previewing the preset 'Bright'" in win._coord_label.text()
    assert c.state.exposure_ev == 0.0 and len(c.state.history) == history, "nothing was applied"
    # leaving puts the edited picture back
    shown.clear()
    panel.preview_ended.emit(); pump(0.2)
    assert not win._preset_previewing and shown and np.array_equal(shown[-1], c.state.image_rgb)
    # sweeping across the list only shows where the mouse comes to rest
    shown.clear()
    panel.preview_requested.emit("Bright"); panel.preview_ended.emit(); pump(0.4)
    assert not shown, "a quick pass does not render anything"
    # applying while previewing leaves the applied picture, not the preview state
    panel.preview_requested.emit("Bright"); pump(0.5)
    c.apply_look_preset("Bright"); pump(0.8)
    assert not win._preset_previewing and abs(c.state.exposure_ev - 1.5) < 1e-6
    # the setting turns it off
    S.save({"hover_preview": False})
    c.set_exposure_ev(0.0); pump(0.6); shown.clear()
    panel.preview_requested.emit("Bright"); pump(0.5)
    assert not shown and not win._preset_previewing
    print("ok")
''')


def test_hovering_a_preset_previews_it_without_applying_it():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    r = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=240)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-3000:]
