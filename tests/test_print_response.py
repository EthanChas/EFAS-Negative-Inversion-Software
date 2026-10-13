"""Print Response (Snap, Toe, Shoulder) as a module: in the renderer, saved with the photo, undoable, a preset, and switchable off with its light."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np

from photoeditor.desktop.render import EditParams
from photoeditor.features.lookpresets import modules as M
from photoeditor.features.printresponse import logic as pr

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_it_is_a_module_with_the_five_fields_and_a_light():
    spec = {m.id: m for m in M.MODULES}["printresponse"]
    assert [f.key for f in spec.fields] == list(pr.DEFAULTS)
    assert M.PANEL_MODULES["printresponse"][0] == "Print Response" and "printresponse" in M.SWITCHABLE
    assert M.panel_defaults("printresponse") == pr.DEFAULTS
    off = M.off_overrides(["printresponse"])
    assert off == pr.DEFAULTS, "off means the neutral curve"
    assert {f.key for f in spec.fields} <= set(M.LOOK_KEYS)


def test_the_renderer_parameters_carry_it_and_off_removes_it():
    from photoeditor.desktop.export_worker import default_edit_state

    class S:
        pass

    state = S()
    for k, v in {**default_edit_state(True), "print_snap": 0.3, "print_toe": 0.5, "print_shoulder": -0.4}.items():
        setattr(state, k, v)
    params = EditParams.from_state(state)
    assert (params.print_snap, params.print_toe, params.print_shoulder) == (0.3, 0.5, -0.4)
    state.modules_off = ["printresponse"]
    off = EditParams.from_state(state)
    assert (off.print_snap, off.print_toe, off.print_shoulder) == (0.0, 0.0, 0.0) and state.print_snap == 0.3
    del state.print_snap
    assert EditParams.from_state(state).print_snap == 0.0, "an older saved state without the fields is neutral"


def test_the_sidecar_round_trips_it():
    from photoeditor.features.xmp import logic as xmp

    state = {"print_snap": 0.25, "print_toe": -0.3, "print_toe_width": 1.2, "print_shoulder": 0.6, "print_shoulder_width": 4.0}
    import tempfile

    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "a.png")
    open(path, "wb").write(b"x")
    from photoeditor.desktop.export_worker import default_edit_state

    full = {**default_edit_state(True), **state, "crop_rect": None}
    xmp.write_sidecar(path, full, (100, 150))
    back = xmp.read_sidecar(path)
    for key, value in state.items():
        assert back[key] == value, key


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
    S.save({"scan_quality": False})
    p1, p2 = os.path.join(work, "a.png"), os.path.join(work, "b.png")
    ramp = np.tile(np.linspace(0, 255, 300, dtype=np.uint8)[None, :, None], (200, 1, 3))
    for p in (p1, p2):
        cv2.imwrite(p, ramp)
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.show(); win.resize(1500, 900); win.open_folder(work, prefer=p1)
    c = win.controller
    def pump(s):
        end = time.time() + s
        while time.time() < end:
            app.processEvents(); time.sleep(0.01)
    pump(1.5)
    c.set_negative_inverted(False); pump(0.6)      # a plain positive gradient: the ends and the middle are easy to read
    panel = win._print_response_tool
    assert panel.parent() is not None and not panel._header.power_light.isHidden() and panel._expanded is False
    base = c.state.image_rgb.copy()
    cols = lambda im, a, b: float(im[:, a:b].mean())

    # Toe: a positive toe lifts the blacks, a negative one crushes the shadows
    c.set_print_response(0.0, 1.0, 2.5, 0.0, 2.5); pump(0.8)
    toe = c.state.image_rgb
    assert toe[:, :6].mean() > base[:, :6].mean() + 8 and abs(cols(toe, 270, 300) - cols(base, 270, 300)) < 6
    # Shoulder: a positive shoulder pulls the whites down
    c.set_print_response(0.0, 0.0, 2.5, 1.0, 2.5); pump(0.8)
    sh = c.state.image_rgb
    assert sh[:, -6:].mean() < base[:, -6:].mean() - 8 and abs(cols(sh, 0, 30) - cols(base, 0, 30)) < 4
    # Snap: the midtones get steeper while the middle grey stays
    c.set_print_response(0.5, 0.0, 2.5, 0.0, 2.5); pump(0.8)
    sn = c.state.image_rgb
    assert float(sn[:, 130:170].astype(float).std()) > float(base[:, 130:170].astype(float).std()) + 2
    # back to neutral gives back the very same picture
    c.set_print_response(0.0, 0.0, 2.5, 0.0, 2.5); pump(0.8)
    assert np.array_equal(c.state.image_rgb, base)

    # the graph paints (an open module draws it) and shows the curve in the accent colour
    panel.set_expanded(True); pump(0.5)
    panel._plot.set_values(0.3, 0.5, 2.5, 0.4, 2.5)
    img = panel._plot.grab().toImage()
    from PyQt6.QtGui import QImage
    from photoeditor.theme.tokens import THEME
    accent = [int(THEME.accent_primary[i:i + 2], 16) for i in (1, 3, 5)]
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    arr = np.frombuffer(img.constBits().asstring(img.sizeInBytes()), np.uint8).reshape(img.height(), img.bytesPerLine())[:, : img.width() * 3].reshape(img.height(), img.width(), 3)
    assert (np.abs(arr.astype(int) - np.array(accent)).max(axis=2) < 30).sum() > 30, "the curve is drawn"

    # the sliders show what is set, the graph follows, and the preview path works
    c.set_print_response(0.2, 0.3, 1.0, 0.4, 3.0); pump(0.6)
    win._on_reverted(); pump(0.1)
    assert [round(v, 2) for v in panel._current()] == [0.2, 0.3, 1.0, 0.4, 3.0]
    assert panel._plot._values == (0.2, 0.3, 1.0, 0.4, 3.0)
    panel._snap.set_value(-0.3)
    panel._on_value_changed(-0.3); pump(0.5)
    assert abs(c.state.print_snap + 0.3) < 1e-6, "dragging a slider changes the picture"
    assert c.state.history[-1].description.startswith("Print response")
    assert c.can_undo()

    # saved with the photo; the other photo has its own; coming back finds it
    saved = edit_store.load_edit_state(c._db, p1)
    assert abs(saved["print_snap"] + 0.3) < 1e-6 and saved["print_toe_width"] == 1.0
    c.open_file(p2); pump(1.2)
    assert panel._current() == (0.0, 0.0, 2.5, 0.0, 2.5) and c.state.print_snap == 0.0
    c.open_file(p1); pump(1.2)
    assert abs(c.state.print_snap + 0.3) < 1e-6 and abs(panel._snap.value() + 0.3) < 0.006

    # the light switches the curve off and on without losing the settings
    shaped = c.state.image_rgb.copy()
    QTest.mouseClick(panel._header.power_light, Qt.MouseButton.LeftButton); pump(0.9)
    assert np.array_equal(c.state.image_rgb, base) and c.state.print_snap < 0 and not panel._body_container.isEnabled()
    QTest.mouseClick(panel._header.power_light, Qt.MouseButton.LeftButton); pump(0.9)
    assert np.array_equal(c.state.image_rgb, shaped)

    # a module preset can store and bring it back
    c.store_module_preset("printresponse", "Soft"); pump(0.2)
    c.set_print_response(0.0, 0.0, 2.5, 0.0, 2.5); pump(0.5)
    assert c.state.print_snap == 0.0
    c.apply_module_preset("printresponse", "Soft"); pump(0.8)
    assert abs(c.state.print_snap + 0.3) < 1e-6 and c.state.print_toe_width == 1.0
    # and so can a look
    c.save_look_preset("Pop"); pump(0.2)
    c.set_print_response(0.0, 0.0, 2.5, 0.0, 2.5); pump(0.5)
    c.apply_look_preset("Pop"); pump(0.8)
    assert abs(c.state.print_snap + 0.3) < 1e-6
    print("ok")
''')


def test_print_response_in_the_window():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    r = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _WINDOW], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-3000:]
