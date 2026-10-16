"""The small grey "PRESET: name" beside the Presets panel's title, like the modules have."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    from PyQt6.QtWidgets import QApplication
    rng = np.random.default_rng(0)
    paths = []
    for i in range(3):
        p = os.path.join(work, f"a{i}.png"); cv2.imwrite(p, rng.integers(60, 190, (160, 240, 3), dtype=np.uint8)); paths.append(p)
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.show(); win.open_folder(work, prefer=paths[0]); c = win.controller
    def pump(s):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(2)
    panel = win._presets_panel
    label = panel._header.preset_label
    text = lambda: label.text() if label.isVisibleTo(panel) else ""

    # nothing applied: nothing shown
    assert text() == "" and c.look_preset_status() is None

    # a built-in look: its own name (without the folders), the full name in the tip
    c.apply_builtin_preset("Scanners (EFAS Original)/Frontier 100"); pump(0.9)
    assert text() == "PRESET: Frontier 100", text()
    assert "Scanners (EFAS Original)/Frontier 100" in label.toolTip() and "photo" in label.toolTip() and "changed" not in label.toolTip()
    assert c.look_preset_status() == ("Frontier 100", "Scanners (EFAS Original)/Frontier 100", False)

    # edited since: the cue appears, and goes when the values are put back
    keep = c.state.saturation
    c.apply_look({"saturation": 0.6}, "edit"); pump(0.8)
    assert text() == "PRESET: Frontier 100 (edited)" and "changed" in label.toolTip(), text()
    c.apply_look({"saturation": keep}, "back"); pump(0.8)
    assert text() == "PRESET: Frontier 100", text()

    # one of My Presets
    c.save_look_preset("Mine/Warm Test"); pump(0.5)
    c.apply_look_preset("Mine/Warm Test"); pump(0.8)
    assert text() == "PRESET: Warm Test", text()
    assert c.look_preset_status()[:2] == ("Warm Test", "Mine/Warm Test")
    # a long name is shortened like the modules' are
    c.save_look_preset("A very long preset name indeed"); pump(0.5)
    c.apply_look_preset("A very long preset name indeed"); pump(0.8)
    assert text().startswith("PRESET: A very long pre") and text().endswith("..."), text()

    # kept with the photo: another photo shows nothing, this one shows it again when reopened
    c.open_file(paths[1]); pump(1.5)
    assert text() == "", text()
    c.open_file(paths[0]); pump(1.5)
    assert text().startswith("PRESET: A very long"), text()

    # deleted since: the label goes
    c.delete_look_preset("A very long preset name indeed"); pump(0.6)
    win._refresh_look_preset_label()
    assert text() == "", text()

    # to the whole roll: every photo in the folder carries it
    c.apply_builtin_preset_to_folder("Film Stocks/Kodak/Gold"); pump(1.5)
    assert text() == "PRESET: Gold", text()
    from photoeditor.features.persistence import edit_store
    for other in paths[1:]:
        saved = edit_store.load_edit_state(c._db, other)
        assert saved["module_presets"].get("__look__") == "builtin:Film Stocks/Kodak/Gold", (other, saved["module_presets"])
    c.open_file(paths[2]); pump(1.5)
    assert text() == "PRESET: Gold", text()

    # Clear takes it away
    c.clear_look(); pump(1.0)
    assert text() == "" and c.look_preset_status() is None
    print("OK")
""")


def test_the_presets_panel_names_the_look_applied_to_the_photo():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-2500:]
