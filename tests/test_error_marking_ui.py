"""Error marking in the window: drag a coloured, named box round a fault; it follows the crop and rotation, is kept with the photo, and View > Error Marks hides it."""
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
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.features.persistence import edit_store
    from photoeditor.features.errormarks import logic as em
    S.save({"scan_quality": False})
    p1, p2 = os.path.join(work, "a.png"), os.path.join(work, "b.png")
    for p in (p1, p2):
        cv2.imwrite(p, np.full((200, 300, 3), 128, np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.show(); win.resize(1400, 850); win.open_folder(work, prefer=p1)
    c = win.controller
    def pump(s):
        end = time.time() + s
        while time.time() < end:
            app.processEvents(); time.sleep(0.01)
    pump(1.5)
    panel, view = win._error_marks_panel, win._image_view
    label = view._label

    # the module is in the Negative tab, and every kind has its own coloured button
    assert panel.parent() is not None and set(panel._buttons) == set(em.KIND_IDS)
    view_menu = [a for a in win._menubar.actions() if a.text() == "View"][0].menu()
    action = [a for a in view_menu.actions() if a.text() == "Error Marks"][0]
    assert action.isCheckable() and action.isChecked() and panel._show.isChecked()

    # choosing a kind turns the marking tool on; dragging a box adds a mark of that kind
    panel._buttons["scratch"].click(); pump(0.1)
    assert label._err_tool == "scratch" and win._error_tool_kind == "scratch" and panel.active_kind() == "scratch"
    panel._buttons["watermark"].click(); pump(0.1)
    assert label._err_tool == "watermark" and not panel._buttons["scratch"].isChecked(), "one kind at a time"
    panel._buttons["scratch"].click(); pump(0.1)
    k = label._scale
    def drag(x1, y1, x2, y2):
        QTest.mousePress(label, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(x1 * k), round(y1 * k)))
        QTest.mouseMove(label, QPoint(round(x2 * k), round(y2 * k)))
        QTest.mouseRelease(label, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(x2 * k), round(y2 * k)))
        pump(0.2)
    drag(50, 40, 120, 90)
    assert [m["kind"] for m in c.state.error_marks] == ["scratch"]
    pts = c.error_mark_shapes()[0]["points"]
    for got, want in zip(pts, [(50, 40), (120, 40), (120, 90), (50, 90)]):
        assert abs(got[0] - want[0]) < 1.5 and abs(got[1] - want[1]) < 1.5, pts
    drag(200, 100, 200, 100)   # a click, not a box
    assert len(c.state.error_marks) == 1
    panel._buttons["watermark"].click(); drag(10, 10, 60, 30)
    panel._buttons["transport"].click(); drag(200, 20, 230, 180)
    assert [m["kind"] for m in c.state.error_marks] == ["scratch", "watermark", "transport"]
    assert panel._summary.text() == "3 marks: 1 scratches, 1 watermarks, 1 transport lines", panel._summary.text()

    # each kind is drawn in its own colour (scratches red, watermarks yellow, transport lines dark navy)
    pump(0.3)
    from PyQt6.QtGui import QImage
    img = label.grab().toImage().convertToFormat(QImage.Format.Format_RGB888)
    arr = np.frombuffer(img.constBits().asstring(img.sizeInBytes()), np.uint8).reshape(img.height(), img.bytesPerLine())[:, : img.width() * 3].reshape(img.height(), img.width(), 3)
    def has(colour, tol=24):
        want = np.array([int(colour[i:i + 2], 16) for i in (1, 3, 5)])
        return bool((np.abs(arr.astype(int) - want).max(axis=2) <= tol).any())
    assert has("#e5484d") and has("#f5d90a") and has("#1f2f7a")

    # the marks are kept with the photo
    saved = edit_store.load_edit_state(c._db, p1)["error_marks"]
    assert len(saved) == 3 and saved[0]["kind"] == "scratch"

    # a mark stays on its fault when the picture is rotated
    before = c.error_mark_shapes()
    c.rotate(1); pump(0.8)
    after = c.error_mark_shapes()
    assert c.state.image_rgb.shape[:2] == (300, 200)
    for shape in after:
        for x, y in shape["points"]:
            raw = c._display_to_raw(x - 0.5, y - 0.5)
            assert -0.01 <= raw[0] <= 1.01 and -0.01 <= raw[1] <= 1.01
    for m, shape in zip(c.state.error_marks, after):
        for raw, (x, y) in zip(m["pts"], shape["points"]):
            back = c._display_to_raw(x - 0.5, y - 0.5)
            assert abs(back[0] - raw[0]) < 1e-3 and abs(back[1] - raw[1]) < 1e-3
    assert after[0]["points"] != before[0]["points"]
    c.rotate(-1); pump(0.8)

    # the other photo has none; coming back finds them again
    win.controller.open_file(p2); pump(1.2)
    assert c.state.error_marks == [] and view._label._err_shapes == [] and panel._summary.text() == "No marks on this photo."
    win.controller.open_file(p1); pump(1.2)
    assert len(c.state.error_marks) == 3 and len(view._label._err_shapes) == 3

    # right-click on a mark offers to change or remove it
    from PyQt6.QtWidgets import QMenu
    menus = []
    QMenu.exec = lambda self, *a: menus.append([x.text() for x in self.actions()])
    seen = []
    view.error_mark_context.connect(lambda i, where: seen.append(i))
    cx, cy = 85, 65
    QTest.mouseClick(label, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, QPoint(round(cx * k), round(cy * k)))
    assert seen == [0] and menus == [["Change to", "Remove this mark", "Remove all scratches"]], menus
    c.set_error_mark_kind(0, "newton"); assert c.state.error_marks[0]["kind"] == "newton"
    c.delete_error_mark(1); assert [m["kind"] for m in c.state.error_marks] == ["newton", "transport"]
    assert c.clear_error_marks("transport") == 1 and [m["kind"] for m in c.state.error_marks] == ["newton"]

    # View > Error Marks hides them, stops marking, and the module's box follows
    panel._buttons["dust"].click(); pump(0.1)
    action.setChecked(False); pump(0.1)
    assert not label._err_visible and not panel._show.isChecked() and label._err_tool is None and win._error_tool_kind == "" and not panel._buttons["dust"].isChecked()
    assert S.get("error_marks_visible") is False
    panel._show.setChecked(True); pump(0.1)
    assert label._err_visible and action.isChecked() and S.get("error_marks_visible") is True
    # choosing a kind while they are hidden shows them again
    action.setChecked(False); panel._buttons["unknown"].click(); pump(0.1)
    assert label._err_visible and action.isChecked() and label._err_tool == "unknown"

    # marks are never part of the edit that is exported
    from photoeditor.desktop.controller import LOOK_FIELDS
    assert "error_marks" not in LOOK_FIELDS
    assert c.clear_error_marks() == 1 and c.state.error_marks == []
    print("ok")
''')


def test_error_marking_in_the_window():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    r = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-3000:]
