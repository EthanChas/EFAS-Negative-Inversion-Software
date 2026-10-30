"""A theme can arrange the window: the panels beside the picture (which, in what order), which side they are on, the tool rail (its tabs and its side) and the filmstrip."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time, dataclasses
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp(); folder = os.path.join(work, "r"); os.makedirs(folder)
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.theme import cssfile, themes, tokens
    S.save({"scan_quality": False})
    p = os.path.join(folder, "a.png"); cv2.imwrite(p, np.full((300, 450, 3), 110, np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); win.show(); app.processEvents(); win.open_folder(folder, prefer=p)
    def pump(secs):
        end = time.time() + secs
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(2)
    lay, panels, col = win._theme_layout, win._theme_layout.panels, win._left_tools_col
    def order():
        return [name for i in range(col.count()) for name, w in panels.items() if col.itemAt(i).widget() is w]
    def put(css):
        spec, errors, _w = cssfile.parse(css)
        assert errors == [], errors
        tokens.use(themes.build(spec)); win.apply_theme(); pump(0.5)
    default_order = order()
    assert default_order == ["library", "tagging", "history", "masks", "snapshots", "versions", "presets", "export"], default_order
    assert win._splitter.widget(0) is win._left_scroll and win._splitter.widget(2) is win._sidebar_pane

    # --- which panels, in what order
    put(":root { --layout-left-panels: masks, history, library; }")
    assert order()[:3] == ["masks", "history", "library"], order()
    assert win._mask_manager.isVisible() and win._history_panel.isVisible()
    for name in ("tagging", "snapshots", "versions", "presets", "export"):
        assert panels[name].isHidden(), name
    panels["export"].show(); pump(0.3)
    assert panels["export"].isHidden(), "a panel the theme left out stays away when the window shows it"
    put(":root { }")
    assert order() == default_order and all(not w.isHidden() for w in panels.values()), "back to the default: every panel is back, in its place"

    # --- the other side
    put(":root { --layout-side-panels: right; --layout-tool-rail: right; }")
    assert win._splitter.widget(0) is win._sidebar_pane and win._splitter.widget(2) is win._left_scroll and lay.swapped
    row = win._tool_row
    assert row.indexOf(win._tool_rail) == row.count() - 2, ("the rail is the last thing before the stretch", row.indexOf(win._tool_rail), row.count())
    put(":root { }")
    assert win._splitter.widget(0) is win._left_scroll and win._splitter.widget(2) is win._sidebar_pane and not lay.swapped and row.indexOf(win._tool_rail) == 0

    # --- the filmstrip
    flay = win._window_frame.layout()
    assert flay.indexOf(win._filmstrip) == flay.count() - 1
    put(":root { --layout-filmstrip: top; }")
    assert flay.indexOf(win._filmstrip) < flay.indexOf(win._view_stack) and win._filmstrip.isVisible()
    put(":root { --layout-filmstrip: hidden; }")
    assert win._filmstrip.isHidden()
    win._filmstrip.show(); pump(0.3)
    assert win._filmstrip.isHidden(), "hidden by the theme stays hidden"
    put(":root { }")
    assert flay.indexOf(win._filmstrip) == flay.count() - 1 and not win._filmstrip.isHidden()

    # --- the tool rail's tabs
    rail = win._tool_rail
    put(":root { --layout-tool-tabs: color, negative; }")
    shown = [t for t, f in rail._frames.items() if not f.isHidden()]
    assert shown == ["negative", "color"] or set(shown) == {"negative", "color"}, shown
    ordered = [t for i in range(rail._layout.count()) for t, f in rail._frames.items() if rail._layout.itemAt(i).widget() is f]
    assert ordered[:2] == ["color", "negative"], ordered
    put(":root { }")
    assert not rail._frames["exposure"].isHidden()

    # --- widths are set when a theme is put in force
    put(":root { --layout-left-width: 430; --layout-sidebar-width: 540; }")
    sizes = win._splitter.sizes()
    assert abs(sizes[0] - 430) <= 3 and abs(sizes[2] - 540) <= 3, sizes
    print("OK theme layout")
""")


def test_a_theme_arranges_the_window():
    r = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "OK theme layout" in r.stdout, r.stdout[-1500:] + r.stderr[-3000:]
