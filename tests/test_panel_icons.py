"""The icons beside the panels' names come from the .svg files in assets/icon, not from drawing code."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
ICONS = Path(SRC) / "photoeditor" / "assets" / "icon"


def _run(script: str) -> str:
    env = {**os.environ, "PYTHONPATH": SRC, "QT_QPA_PLATFORM": "offscreen", "PHOTOEDITOR_DATA_DIR": os.path.join(os.environ.get("TEMP", "."), "efas-icon-test")}
    out = subprocess.run([sys.executable, "-c", textwrap.dedent(script)], capture_output=True, text=True, timeout=120, env=env)
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-1500:]
    return out.stdout


def test_every_named_icon_is_a_file_in_the_icon_folder_with_its_licence():
    from photoeditor.desktop.view import panel_icons

    assert panel_icons.ICON_DIR == ICONS and (ICONS / "LICENSE-lucide.txt").read_text(encoding="utf-8").startswith("ISC License")
    for name in sorted(panel_icons.NAMES):
        text = (ICONS / f"{name}.svg").read_text(encoding="utf-8")
        assert text.lstrip().startswith("<!-- Lucide") and 'stroke="currentColor"' in text and "viewBox=\"0 0 24 24\"" in text, name
    for title in ("Library", "Tagging", "Tags", "Presets", "Snapshots", "Versions", "History", "Export"):
        assert title in panel_icons.BY_TITLE, title


def test_icons_are_loaded_from_the_files_recoloured_and_kept():
    _run(r'''
        from PyQt6.QtWidgets import QApplication
        app = QApplication([])
        from photoeditor.desktop.view import panel_icons as P
        for name in sorted(P.NAMES):
            pix = P.pixmap(name, 16, "#ff0000")
            assert not pix.isNull() and pix.width() >= 16, name
            img = pix.toImage()
            seen = [(img.pixelColor(x, y).alpha(), x, y) for x in range(img.width()) for y in range(img.height())]
            assert sum(1 for a, _x, _y in seen if a > 100) >= 8, (name, "nothing was drawn")
            _a, bx, by = max(seen)
            c = img.pixelColor(bx, by)
            assert c.red() > 200 and c.green() < 60 and c.blue() < 60, (name, c.name(), "the stroke takes the colour asked for")
        green = P.pixmap("library", 16, "#00ff00").toImage()
        assert max((green.pixelColor(x, y).alpha(), green.pixelColor(x, y).green()) for x in range(16) for y in range(16))[1] > 200
        assert P.pixmap("library", 16, "#ff0000") is P.pixmap("library", 16, "#ff0000"), "made once"
        assert P.pixmap("no-such-icon", 16).isNull() and P.pixmap(None).isNull() and P.for_title("A Title With No Icon").isNull()
        assert not P.for_title("Library").isNull() and not P.for_tab("negative").isNull()
        print("OK")
    ''')


def test_panels_show_their_icon_beside_the_name_and_follow_the_theme():
    _run(r'''
        from PyQt6.QtWidgets import QApplication
        app = QApplication([])
        from photoeditor.theme import runtime, tokens
        from photoeditor.desktop.view.collapsible_panel import CollapsiblePanel
        runtime.apply(app, {"theme": "classic", "theme_accent": "Blue", "theme_text_scale": 100})
        lib, plain = CollapsiblePanel("Library"), CollapsiblePanel("Something Else")
        keep = []
        assert not lib._header._icon_label.pixmap().isNull() and lib._header._icon_label.isVisibleTo(lib), "Library has its icon"
        assert plain._header._icon_label.pixmap().isNull() and not plain._header._icon_label.isVisibleTo(plain), "no icon, no gap, for a title without one"
        for title in ("Tagging", "Presets", "Snapshots", "Versions", "History", "Export"):
            panel = CollapsiblePanel(title); keep.append(panel)
            assert not panel._header._icon_label.pixmap().isNull(), title
        def colour():
            img = lib._header._icon_label.pixmap().toImage()
            return max((img.pixelColor(x, y).alpha(), img.pixelColor(x, y).name()) for x in range(img.width()) for y in range(img.height()))[1]
        before = colour()
        runtime.apply(app, {"theme": "modern", "theme_accent": "Coral", "theme_text_scale": 100})
        lib._header.apply_theme()
        after = colour()
        assert before == tokens.classic_theme().text_primary and after == tokens.THEME.text_primary and before != after, (before, after)
        print("OK")
    ''')


def test_the_tool_rail_and_the_droppers_use_the_icon_files_too():
    _run(r'''
        import tempfile, os
        os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
        from PyQt6.QtWidgets import QApplication
        app = QApplication([])
        from photoeditor.desktop.view.negative_tool_panel import NegativeToolPanel
        from photoeditor.desktop.view import icons
        p = NegativeToolPanel()
        for b in p._droppers.values():
            assert not b.icon().isNull(), "a dropper has its icon"
        assert not icons.eyedropper_cursor(28).pixmap().isNull()
        src = open(icons.__file__, encoding="utf-8").read()
        assert "def sun_icon" not in src and "def eyedropper_icon" not in src, "the hand-drawn icons are gone"
        from photoeditor.desktop.view import app_window
        text = open(app_window.__file__, encoding="utf-8").read()
        assert "panel_icons.for_tab(" in text and "sun_icon(" not in text
        print("OK")
    ''')


def test_a_header_with_no_arrow_keeps_its_icon_clear_of_the_colour_bar():
    _run(r'''
        from PyQt6.QtWidgets import QApplication
        app = QApplication([])
        from photoeditor.theme import runtime
        from photoeditor.desktop.view.collapsible_panel import CollapsiblePanel
        runtime.apply(app, {"theme": "modern", "theme_accent": "Blue", "theme_text_scale": 100})
        def icon_x(collapsible):
            panel = CollapsiblePanel("Masking", collapsible=collapsible)
            panel.resize(320, 120); panel.show(); app.processEvents()
            return panel._header._icon_label.mapTo(panel._header, panel._header._icon_label.rect().topLeft()).x()
        plain, arrowed = icon_x(False), icon_x(True)
        assert plain >= 13, ("the icon starts past the colour bar, which ends at x=8", plain)
        assert arrowed > 13, arrowed
        runtime.apply(app, {"theme": "classic", "theme_accent": "Blue", "theme_text_scale": 100})
        assert icon_x(False) < plain, "the classic theme has no bar, so no extra room"
        print("OK")
    ''')
