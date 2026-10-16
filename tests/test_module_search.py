"""The module search: type in the Search tab and the modules that match, from every tab, are gathered there; clear it or leave the tab and each goes back where it was."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from photoeditor.features.modulesearch import logic as L

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _mods():
    return [("exposure", "Exposure", L.haystack("Exposure", ["Exposure", "Reset"])), ("color", "Color", L.haystack("Color", ["Saturation", "Temperature", "Tint"])),
            ("toning", "Color Toning", L.haystack("Color Toning", ["Hue", "Strength"])), ("edge", "Edge Color", L.haystack("Edge Color", ["Tint", "Warmth", "Light"])),
            ("finishing", "Finishing", L.haystack("Finishing", ["Vignette", "Border"])), ("flat", "Flat Field", L.haystack("Flat Field", ["Method", "Reference"]))]


def test_a_search_is_words_that_all_have_to_be_found_best_title_first():
    mods = _mods()
    assert L.words("  Edge  Color & ") == ["edge", "color"] and L.words("") == []
    assert L.search(mods, "color") == ["color", "toning", "edge"], "titles that start with it first (in editor order), then ones that have it later in the title"
    assert L.search(mods, "tint") == ["color", "edge"], "a slider's name finds its module"
    assert L.search(mods, "brightness") == ["exposure"], "a common word for what it does (Find's synonyms) finds it"
    assert L.search(mods, "vignette") == ["finishing", "flat"], "found in a control's name (Finishing) and in the synonyms of the title (Flat Field)"
    assert L.search(mods, "hue strength") == ["toning"] and L.search(mods, "hue banana") == [] and L.search(mods, "") == [] and L.search(mods, "   ") == []
    assert L.score("exp", "Exposure", mods[0][2]) == 0 and L.score("field", "Flat Field", mods[5][2]) == 1 and L.score("reference", "Flat Field", mods[5][2]) == 2


def test_a_control_called_color_does_not_borrow_the_synonyms_of_the_color_module():
    border = L.haystack("Finishing", ["Vignette", "Color", "Border"])
    assert "tint" not in border and "color" in border and "temperature" not in border
    assert "warm" in L.haystack("Color", ["Temperature"]) and "kelvin" in L.haystack("Color", ["Temperature"]), "a specific control still brings its synonyms"
    assert L.search([("fin", "Finishing", border), ("col", "Color", L.haystack("Color", ["Tint"]))], "tint") == ["col"]


def test_long_help_text_does_not_make_every_module_match_everything():
    long = "x" * 200 + " tint"
    stack = L.haystack("Sharpening", [long, "Amount"])
    assert "tint" not in stack and "amount" in stack


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False, "advanced_mode": False})
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt, QEvent
    from PyQt6.QtGui import QKeyEvent
    p = os.path.join(work, "a.png"); cv2.imwrite(p, np.random.default_rng(0).integers(40, 200, (200, 300, 3), dtype=np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view.collapsible_panel import CollapsiblePanel
    win = aw.AppWindow(); win.show(); win.open_folder(work, prefer=p)
    def pump(s):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(1.5)
    def settle():
        end = time.time() + 15
        while ms.busy() and time.time() < end: app.processEvents(); time.sleep(0.01)
        pump(0.3)
    ms = win._module_search; edit = win._module_search_edit
    columns = win._tab_columns

    def layout_state():
        out = {}
        for tab, layout in columns.items():
            out[tab] = [(layout.itemAt(i).widget()._title if isinstance(layout.itemAt(i).widget(), CollapsiblePanel) else None) for i in range(layout.count())]
        return out
    def where(title):
        for tab, titles in layout_state().items():
            if title in titles: return tab
        return None
    before = layout_state()

    # there is no Search tab: the box sits above the modules, over the tool rail
    assert "search" not in win._tool_rail._buttons and list(win._tool_rail._buttons)[0] == "negative"
    from PyQt6.QtCore import QPoint
    assert edit.mapToGlobal(QPoint(0, 0)).y() < win._tool_rail.mapToGlobal(QPoint(0, 0)).y(), "above the modules"
    assert edit.placeholderText().startswith("Search modules") and not win._module_search_status.isVisible() and not ms.active()

    # with a tab open, a word: the modules that match come together in a list in its place, from different tabs
    win._tool_rail._buttons["color"].click(); pump(0.6)
    assert win._color_panel._is_open and win._tool_rail._buttons["color"].isChecked()
    edit.setText("vignette"); ms.run_now(); pump(0.4)
    assert ms.active() and set(ms.result_titles()) >= {"Flat Field", "Finishing"}, ms.result_titles()
    assert win._search_panel._is_open and not win._color_panel._is_open and not win._tool_rail._buttons["color"].isChecked(), "the list replaces the tab that was showing"
    assert where("Flat Field") is None and where("Finishing") is None, "they have left their own tabs"
    assert win._module_search_status.isVisible() and "found" in win._module_search_status.text()
    for title in ("Flat Field", "Finishing"):
        panel = next(m for m in win.findChildren(CollapsiblePanel) if m._title == title)
        assert panel._expanded, "a few results are opened at once"
        assert win._search_panel.isAncestorOf(panel)

    # clearing puts every module back where it was, in the same place, closes what the search opened, and the tab that was showing comes back
    ms.clear(); settle()
    assert not ms.active() and layout_state() == before, (layout_state(), before)
    assert not win._search_panel._is_open and win._color_panel._is_open and win._tool_rail._buttons["color"].isChecked(), "the colour tab is open again"
    assert not win._module_search_status.isVisible()
    for title in ("Flat Field", "Finishing"):
        assert not next(m for m in win.findChildren(CollapsiblePanel) if m._title == title)._expanded

    # a control's name, a common word, several words, no match
    edit.setText("tint"); ms.run_now()
    assert {"Color", "Edge Color"} <= set(ms.result_titles()) and "Sharpening" not in ms.result_titles(), ms.result_titles()
    assert "Finishing" not in ms.result_titles() and "Watermark" not in ms.result_titles(), "a border's Color box is not a tint control"
    edit.setText("brightness"); ms.run_now()
    assert "Exposure" in ms.result_titles()
    edit.setText("zzzz qqqq"); ms.run_now(); pump(0.3)
    assert not ms.active() and "No module matches" in win._module_search_status.text() and layout_state() == before and win._search_panel._is_open, "an empty list, with the reason"
    edit.setText("color"); ms.run_now()
    assert len(ms.result_titles()) >= 4 and ms.active() and layout_state() != before

    # Esc empties the box
    for t in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        app.sendEvent(edit, QKeyEvent(t, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    settle()
    assert edit.text() == "" and not ms.active() and layout_state() == before and not win._search_panel._is_open and win._color_panel._is_open

    # choosing a tab while the list is showing sends the modules home, empties the box, and opens the tab that was chosen
    edit.setText("dust"); ms.run_now(); pump(0.3)
    assert ms.active() and "Dust & Scratches" in ms.result_titles() and win._search_panel._is_open
    win._tool_rail._buttons["exposure"].click(); pump(0.7)
    assert not ms.active() and layout_state() == before and edit.text() == "" and not win._search_panel._is_open
    assert win._wb_tools_panel._is_open and win._tool_rail._buttons["exposure"].isChecked() and not win._color_panel._is_open

    # with no tab open, the search still works and closing it leaves none open
    win._tool_rail._buttons["exposure"].click(); pump(0.6)
    assert not win._wb_tools_panel._is_open
    edit.setText("exposure"); ms.run_now(); pump(0.4)
    exposure = next(m for m in win.findChildren(CollapsiblePanel) if m._title == "Exposure")
    assert win._search_panel.isAncestorOf(exposure)
    ms.clear(); settle()
    assert layout_state() == before and not win._search_panel._is_open and not any(b.isChecked() for b in win._tool_rail._buttons.values())
    assert win._wb_tools_panel._content.widget().isAncestorOf(exposure), "the module is back in its own tab"

    # the Edit menu puts the cursor in the box
    assert win._search_modules_action.text() == "Search Modules"
    win._search_modules_action.trigger(); pump(0.2)
    assert edit.hasFocus() or not win.isActiveWindow()
    win.close()
    print("OK")
""")


def test_the_search_box_gathers_matching_modules_from_every_tab_and_puts_them_back():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC, "PHOTOEDITOR_AUDIO": "off"})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-2500:]
