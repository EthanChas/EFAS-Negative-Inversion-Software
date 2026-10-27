"""Ctrl+1 ... Ctrl+9 go to the tool tabs."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from photoeditor.features.keybinds import logic as binds

SRC = str(Path(__file__).resolve().parents[1] / "src")

TABS = ("active", "negative", "correction", "exposure", "color", "detail", "watermark", "metadata", "plugins")


def test_the_tab_keys_are_ctrl_1_to_9_in_the_rail_order():
    for number, tab in enumerate(TABS, start=1):
        action = binds.BY_ID[f"tab_{tab}"]
        assert action.default == f"Ctrl+{number}" and action.kind == "menu" and action.category == "Tool tabs", tab
    assert len({a.default for a in binds.ACTIONS if a.default}) == len([a for a in binds.ACTIONS if a.default]), "no two actions share a key"


_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile, time, faulthandler
    faulthandler.enable()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    folder = os.path.join(work, "roll"); os.makedirs(folder)
    import numpy as np, cv2
    from PyQt6.QtGui import QKeySequence
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    p = os.path.join(folder, "a.png"); cv2.imwrite(p, np.full((200, 300, 3), 120, np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1400, 900); c = win.controller
    win.show(); app.processEvents()
    win.open_folder(folder, prefer=p)
    end = time.time() + 20
    while time.time() < end and c.state.image_rgb is None:
        app.processEvents(); time.sleep(0.01)

    keys = {t: win._tab_actions[t].shortcut().toString() for t in win._tab_actions}
    assert keys["negative"] == "Ctrl+2" and keys["exposure"] == "Ctrl+4" and keys["metadata"] == "Ctrl+8", keys
    for tab in ("negative", "correction", "exposure", "color", "detail", "watermark", "metadata"):
        win._tab_actions[tab].trigger(); app.processEvents()
        assert win._open_tab == tab, (tab, win._open_tab)
        assert win._tool_tab_panels()[tab]._is_open and win._tool_rail._frames[tab] is not None
        others = [t for t, panel in win._tool_tab_panels().items() if t != tab and panel._is_open]
        assert not others, (tab, others)
    win._tab_actions["active"].trigger(); app.processEvents()
    assert win._active_tab_open, "Ctrl+1 is the Enabled modules tab"
    win._tab_actions["negative"].trigger(); app.processEvents()
    assert win._open_tab == "negative" and not win._active_tab_open
    win._tab_actions["plugins"].trigger(); app.processEvents()
    assert win._open_tab == "negative", "the Plugins tab is hidden until a plugin uses it: its key does nothing"
    win.close()
    print("TAB KEYS OK"); sys.stdout.flush()
    os._exit(0)
''')


def test_the_keys_switch_tabs_in_the_window():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""), PHOTOEDITOR_AUDIO="off")
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=400)
    assert "TAB KEYS OK" in done.stdout, done.stdout[-1500:] + done.stderr[-4000:]
