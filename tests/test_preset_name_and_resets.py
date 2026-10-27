"""A built-in preset (darktable's, a paper) shows its name beside the module's title as a stored one does, and every editing module has a Reset button."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_WINDOW = textwrap.dedent(r'''
    import os, sys, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    p1 = os.path.join(work, "a.png")
    ramp = np.tile(np.linspace(0, 255, 300, dtype=np.uint8)[None, :, None], (200, 1, 3))
    cv2.imwrite(p1, ramp)
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.show(); win.resize(1500, 900); win.open_folder(work, prefer=p1)
    c = win.controller
    def pump(s):
        end = time.time() + s
        while time.time() < end:
            app.processEvents(); time.sleep(0.01)
    pump(1.5)

    # a preset that comes with the module names itself in the header, and a hand-made change to the module does not turn it into an update
    for key, panel, name in (("diffuse", win._diffuse_tool, "lens deblur | soft"), ("toneequalizer", win._tone_eq_tool, None), ("colorbalancergb", win._color_balance_tool, None), ("printresponse", win._print_response_tool, None)):
        names = c.module_darktable_presets(key)
        assert names, key
        name = name or names[0]
        assert c.module_active_preset(key) is None
        assert c.apply_darktable_module_preset(key, name), key
        pump(0.6)
        assert c.module_active_preset(key) == name, key
        win._module_menus.refresh(); pump(0.1)
        assert not panel._header.preset_label.isHidden() and panel._header.preset_label.text().startswith("PRESET: "), (key, panel._header.preset_label.text())
        assert c.module_preset_modified(key) is False, "a built-in preset is read-only: no Update Preset"
    c.reset_module("diffuse"); pump(0.4); win._module_menus.refresh(); pump(0.1)
    assert c.module_active_preset("diffuse") is None and win._diffuse_tool._header.preset_label.isHidden(), "Reset takes the name off"

    # the saved photo keeps it
    from photoeditor.features.persistence import edit_store
    saved = edit_store.load_edit_state(c._db, p1)
    assert saved["module_presets"].get("toneequalizer") == c.module_darktable_presets("toneequalizer")[0]

    # every editing module has a Reset button
    for name, panel in (("crop", win._crop_tool), ("dust", win._dust_tool), ("retouch", win._retouch_tool), ("aidust", win._ai_dust_tool), ("errormarks", win._error_marks_panel),
                        ("exposure", win._exposure_tool), ("negative", win._negative_tool), ("sharpening", win._sharpening_tool), ("tonecurve", win._curve_tool)):
        assert not panel.reset_button.isHidden(), name

    # Crop & Rotate goes back to its defaults in one undoable step
    c.set_fine_rotation(2.5); c.set_keystone(0.2, 0.1); c.rotate(1); c.set_flip_h(True); c.set_crop_rect((10, 10, 150, 100)); pump(0.8)
    steps = len(c.state.history)
    assert c.state.fine_rotation == 2.5 and c.state.rotation_quarter_turns == 1 and c.state.crop_rect is not None
    win._crop_tool.reset_button.click(); pump(0.8)
    s = c.state
    assert (s.fine_rotation, s.keystone_v, s.keystone_h, s.rotation_quarter_turns, s.flip_h, s.crop_rect, s.distortion) == (0.0, 0.0, 0.0, 0, False, None, 0.0)
    assert len(c.state.history) == steps + 1 and c.state.history[-1].description == "Reset Crop & Rotate"
    c.undo(); pump(0.6)
    assert c.state.fine_rotation == 2.5 and c.state.crop_rect is not None, "one undo brings it back"

    # Dust & Scratches
    c.set_dust(True, 0.3, 6, 0.8); pump(0.6)
    assert c.state.dust_auto
    win._dust_tool.reset_button.click(); pump(0.8)
    assert not c.state.dust_auto and c.state.dust_threshold == 0.66 and c.state.dust_size == 4 and c.state.scratch_sensitivity == 0.5
    print("ok")
''')


def test_built_in_presets_name_themselves_and_every_module_resets():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    r = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _WINDOW], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "ok" in r.stdout, r.stdout[-2000:] + r.stderr[-3000:]
