"""Settings > General "Close a tab's modules when I switch to another tab": on by default; off keeps every module as it was left."""
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
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    assert S.get("collapse_on_tab_change") is True, "on by default"
    p = os.path.join(work, "a.png"); cv2.imwrite(p, np.random.default_rng(0).integers(30, 220, (200, 300, 3), dtype=np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view.collapsible_panel import CollapsiblePanel
    win = aw.AppWindow(); win.show(); win.open_folder(work, prefer=p)
    def pump(s):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(1.5)
    panels = {"negative": win._negative_panel, "correction": win._correction_panel, "exposure": win._wb_tools_panel}
    def modules(tab):
        return [m for m in panels[tab].findChildren(CollapsiblePanel) if m._collapsible]
    def open_tab(tab):
        win._tool_rail._buttons[tab].click(); pump(0.7)
    def open_all(tab):
        for m in modules(tab): m.set_expanded(True)
        pump(0.4)
    def state(tab):
        return [m._expanded for m in modules(tab)]

    # on: leaving a tab for another folds its modules shut
    open_tab("negative"); open_all("negative")
    assert modules("negative") and all(state("negative"))
    open_tab("correction")
    assert not any(state("negative")), "switched tabs: the Negative modules are closed"
    assert all(m._body_container.maximumHeight() == 0 for m in modules("negative"))
    open_all("correction")
    win._tool_rail._buttons["correction"].click(); pump(0.7)   # closing the tab leaves it too
    assert not win._correction_panel._is_open and not any(state("correction")), "closing the tab closes its modules"

    # coming straight back (before the tab has slid shut) keeps what you had
    open_tab("negative"); open_all("negative")
    win._tool_rail._buttons["exposure"].click(); win._tool_rail._buttons["negative"].click(); pump(0.7)
    assert win._negative_panel._is_open and all(state("negative")), "switched away and back at once: nothing was folded"

    # off: every module stays as you left it
    S.save({"collapse_on_tab_change": False})
    win._tool_rail._buttons["correction"].click(); pump(0.7)
    open_all("correction")
    open_tab("exposure")
    assert all(state("correction")) and all(state("negative")), "setting off: modules stay open after switching tabs"
    win.close()
    print("COLLAPSE OK")
''')


def test_modules_close_on_tab_change_unless_the_setting_is_off():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert "COLLAPSE OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3500:]


def test_the_setting_is_validated():
    from photoeditor.features.settings import logic as S

    assert S._clean({})["collapse_on_tab_change"] is True
    assert S._clean({"collapse_on_tab_change": False})["collapse_on_tab_change"] is False
    assert S._clean({"collapse_on_tab_change": "no"})["collapse_on_tab_change"] is True
