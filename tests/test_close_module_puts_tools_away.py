"""Closing Dust & Scratches (or Error marking), or the tab they are in, puts away what was in hand: the repair tool, Show Detections, the kind of fault being marked - as a darktable module's are when it loses focus."""
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
    from photoeditor.features.errormarks import logic as E
    S.save({"scan_quality": False})
    cv2.imwrite(os.path.join(folder, "a.png"), np.random.default_rng(0).integers(60, 200, (400, 600, 3), dtype=np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=os.path.join(folder, "a.png"))
    def pump(secs):
        end = time.time() + secs
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(3)
    d = win._dust_tool; rail = win._tool_rail
    rail._buttons["correction"].click(); pump(0.6)
    if not d._expanded: d.toggle()
    pump(0.5)

    # --- the delete repair tool: it turns Show Detections on; closing the module puts both away
    d._tool_buttons["delete"].setChecked(True); pump(0.8)
    assert d.active_tool() == "delete" and c.state.show_detections and d.detections_shown()
    d.toggle(); pump(0.8)
    assert d.active_tool() is None and not c.state.show_detections and not d.detections_shown(), "tool and Show Detections are put away"
    assert win._image_view._label._tool is None

    # --- a drawing tool, and closing the tab instead
    d.toggle(); pump(0.5)
    d._tool_buttons["heal"].setChecked(True); d.show_detections(); pump(0.8)
    assert d.active_tool() == "heal" and c.state.show_detections
    rail._buttons["correction"].click(); pump(0.8)             # the tab is closed
    assert d.active_tool() is None and not c.state.show_detections, "closing the tab does the same"

    # --- Error marking
    rail._buttons["correction"].click(); pump(0.6)
    em = win._error_marks_panel
    if not em._expanded: em.toggle()
    pump(0.4)
    kind = E.KIND_IDS[0]
    em.kind_chosen.emit(kind); em.set_active_kind(kind); pump(0.3)
    assert win._error_tool_kind == kind
    em.toggle(); pump(0.6)
    assert win._error_tool_kind == "", "the kind being marked is put away"
    print("OK put away")
""")


def test_closing_a_module_or_its_tab_puts_its_tools_away():
    r = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "OK put away" in r.stdout, r.stdout[-1500:] + r.stderr[-3000:]
