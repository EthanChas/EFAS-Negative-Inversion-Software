"""A painted repair stroke runs to the point where the mouse button was let go (a quick stroke used to lose its last stretch, so the repair stopped short of where it was painted)."""
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
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    path = os.path.join(folder, "a.png"); cv2.imwrite(path, np.full((800, 1200, 3), 120, np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=path)
    def pump(cond=lambda: False, secs=20.0):
        end = time.time() + secs
        while time.time() < end:
            app.processEvents()
            if cond(): return True
            time.sleep(0.01)
        return cond()
    assert pump(lambda: c.state.image_rgb is not None); pump(secs=1.0)
    view = win._image_view; label = view._label; k = label._scale
    got = []; view.stroke_completed.connect(got.append)
    view.set_tool("heal", lambda: 8)
    y = int(300 * k)
    QTest.mousePress(label, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(100 * k), y))
    QTest.mouseMove(label, QPoint(int(130 * k), y))
    QTest.mouseRelease(label, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(260 * k), y))   # let go far past the last move
    stroke = got[0]
    assert abs(stroke[-1][0] - 260) < 2.5 and abs(stroke[-1][1] - 300) < 2.5, stroke[-3:]
    assert abs(stroke[0][0] - 100) < 2.5
    got.clear()
    QTest.mousePress(label, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(100 * k), y))
    QTest.mouseRelease(label, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(100 * k), y))
    assert len(got[0]) == 1, "a click is still one point"
    win.close()
    print("STROKE END OK")
""")


def test_a_painted_stroke_runs_to_where_the_button_was_let_go():
    done = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC, "PHOTOEDITOR_AUDIO": "off"})
    assert "STROKE END OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3000:]
