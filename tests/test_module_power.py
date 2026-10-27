"""The on/off light beside a module's name: green on, red off; square in the Classic theme, a circle with a grey border in the others."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np

from photoeditor.desktop.render import EditParams
from photoeditor.features.lookpresets import modules as M
from photoeditor.features.tonecurve.logic import DEFAULT_POINTS

SRC = str(Path(__file__).resolve().parents[1] / "src")


class _Saved:
    """A saved edit state, as EditParams.from_dict reads one."""

    def __init__(self, **over):
        from photoeditor.desktop.export_worker import default_edit_state

        for key, value in {**default_edit_state(True), **over}.items():
            setattr(self, key, value)


def test_every_module_but_negative_can_be_switched_off():
    assert "negative" not in M.SWITCHABLE and set(M.SWITCHABLE) == set(M.PANEL_MODULES) - {"negative"}
    assert M.off_overrides(["negative"]) == {}, "the inversion cannot be switched off"
    over = M.off_overrides(["exposure", "tonecurve", "canisterwm", "sharpening", "color"])
    assert over["exposure_ev"] == 0.0 and over["wm_film"] == "off" and over["sharpen_amount"] == 0.0
    assert over["saturation"] == over["temperature"] == over["tint"] == 0.0
    assert over["tone_curve_points"] == tuple(tuple(p) for p in DEFAULT_POINTS)


def test_an_off_module_is_made_as_if_untouched_and_its_settings_are_kept():
    saved = _Saved(exposure_ev=1.2, contrast=0.4, saturation=0.5, sharpen_amount=0.7, wm_film="portra", vignette=0.3,
                   tone_curve_points=[(0, 0), (128, 90), (255, 255)])
    on = EditParams.from_state(saved)
    assert (on.exposure_ev, on.contrast, on.saturation) == (1.2, 0.4, 0.5) and on.wm_film == "portra"
    saved.modules_off = ["exposure", "color", "canisterwm", "tonecurve", "finishing"]
    off = EditParams.from_state(saved)
    assert off.exposure_ev == 0.0 and off.saturation == 0.0 and off.wm_film == "off" and off.vignette == 0.0
    assert off.tone_curve_points == tuple(tuple(p) for p in DEFAULT_POINTS)
    assert off.contrast == 0.4 and off.sharpen_amount == 0.7, "modules still on are left alone"
    assert saved.exposure_ev == 1.2 and saved.saturation == 0.5 and saved.wm_film == "portra", "the saved settings are untouched"
    assert EditParams.from_dict({**vars(saved), "modules_off": ["exposure"]}).exposure_ev == 0.0, "exports read it from the saved state too"
    assert EditParams.from_state(_Saved(exposure_ev=1.0)).exposure_ev == 1.0, "a state without the field is simply all on"


def test_the_light_is_a_square_in_classic_and_a_grey_ringed_circle_in_the_others():
    script = textwrap.dedent(r'''
        import os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication
        app = QApplication([])
        from photoeditor.desktop.view import collapsible_panel as cp
        class T: style = "classic"
        cp.THEME = T
        light = cp._PowerLight(); light.show()
        def px(x, y):
            c = light.grab().toImage().pixelColor(x, y)
            return c.red(), c.green(), c.blue()
        # classic: a filled square, right out to its corners, with a black edge
        assert px(8, 8) == (0x2f, 0xb3, 0x44) and px(3, 3) == (0x2f, 0xb3, 0x44) and px(12, 12) == (0x2f, 0xb3, 0x44) and px(2, 2) == (0, 0, 0)
        light.set_on(False)
        assert px(8, 8) == (0xd6, 0x39, 0x39) and px(3, 3) == (0xd6, 0x39, 0x39)
        # the others: a circle, so the corner of its box is empty, with a grey ring
        T.style = "modern"; light.update()
        assert px(8, 8) == (0xd6, 0x39, 0x39) and px(3, 3) != (0xd6, 0x39, 0x39)
        light.set_on(True)
        assert px(8, 8) == (0x2f, 0xb3, 0x44)
        ring = px(8, 2)
        assert abs(ring[0] - ring[1]) < 40 and abs(ring[1] - ring[2]) < 40 and 90 < ring[0] < 190, ring   # grey, not green
        assert "switch it off" in light.toolTip()
        light.set_on(False)
        assert "switch it back on" in light.toolTip()
        print("ok")
    ''')
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    r = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-2500:]


_WINDOW = textwrap.dedent(r'''
    import os, sys, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.features.persistence import edit_store
    from photoeditor.features.lookpresets.modules import SWITCHABLE
    S.save({"scan_quality": False})
    p1, p2 = os.path.join(work, "a.png"), os.path.join(work, "b.png")
    for p in (p1, p2):
        cv2.imwrite(p, np.random.default_rng(0).integers(40, 160, (200, 300, 3), dtype=np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.show(); win.resize(1500, 900); win.open_folder(work, prefer=p1)
    c = win.controller
    def pump(s):
        end = time.time() + s
        while time.time() < end:
            app.processEvents(); time.sleep(0.01)
    pump(1.5)
    panels = win._module_menus._panels
    assert set(panels) == set(SWITCHABLE) | {"negative"}
    for key, panel in panels.items():
        assert (not panel._header.power_light.isHidden()) == (key in SWITCHABLE), key
        if key in SWITCHABLE:
            assert panel.power_on()

    c.set_exposure_ev(1.5); pump(0.8)
    bright = float(c.state.image_rgb.mean())
    c.set_exposure_ev(0.0); pump(0.8)
    base = float(c.state.image_rgb.mean())
    c.set_exposure_ev(1.5); pump(0.8)
    assert abs(float(c.state.image_rgb.mean()) - bright) < 0.01 and bright > base + 5
    exposure = panels["exposure"]
    light = exposure._header.power_light
    # clicking the light switches the module off: the picture goes back, the setting stays, the module's controls grey out, and the module does not open or close
    was_open = exposure._expanded
    QTest.mouseClick(light, Qt.MouseButton.LeftButton); pump(0.9)
    assert c.state.modules_off == ["exposure"] and not exposure.power_on() and exposure._expanded == was_open
    assert abs(float(c.state.image_rgb.mean()) - base) < 0.01, "the picture is made without the module"
    assert c.state.exposure_ev == 1.5, "the setting is kept"
    assert not exposure._body_container.isEnabled() and exposure._header.isEnabled()
    assert "Exposure switched off" in win._coord_label.text()
    saved = edit_store.load_edit_state(c._db, p1)
    assert saved["modules_off"] == ["exposure"] and saved["exposure_ev"] == 1.5
    # the others are unaffected, and so is the Negative module (it has no light)
    assert all(panels[k].power_on() for k in SWITCHABLE if k != "exposure")
    # another photo has its own lights; coming back finds this one still off
    c.open_file(p2); pump(1.2)
    assert c.state.modules_off == [] and exposure.power_on() and exposure._body_container.isEnabled()
    c.open_file(p1); pump(1.2)
    assert c.state.modules_off == ["exposure"] and not exposure.power_on() and abs(float(c.state.image_rgb.mean()) - base) < 0.01
    # switching it back on
    QTest.mouseClick(light, Qt.MouseButton.LeftButton); pump(0.9)
    assert c.state.modules_off == [] and exposure.power_on() and abs(float(c.state.image_rgb.mean()) - bright) < 0.01
    # a module that makes no difference can still be switched, e.g. Sharpening and Color together
    panels["color"].power_toggled.emit(False); panels["sharpening"].power_toggled.emit(False); pump(0.5)
    assert sorted(c.state.modules_off) == ["color", "sharpening"]
    # a photo exported from the saved state is made the same way as on screen
    from photoeditor.desktop.render import EditParams
    assert EditParams.from_dict(edit_store.load_edit_state(c._db, p1)).saturation == 0.0
    print("ok")
''')


def test_the_light_switches_a_module_in_the_window():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    r = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _WINDOW], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-3000:]
