"""The Presets search box: it narrows the list that is showing to the presets that have every word typed in their folder, name or description."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from photoeditor.features.presettree import logic as t

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_search_finds_names_by_every_word_in_the_folders_the_name_or_the_description():
    names = ["B&W/Number 1", "B&W/Soft", "Lab/Frontier/Warm", "Warm Sky"]
    assert t.search(names, "") == names and t.search(names, "   ") == names, "nothing typed, nothing left out"
    assert t.search(names, "warm") == ["Lab/Frontier/Warm", "Warm Sky"], "in the order given"
    assert t.search(names, "b&w soft") == ["B&W/Soft"], "every word has to be there, wherever in the path"
    assert t.search(names, "FRONTIER  warm") == ["Lab/Frontier/Warm"], "case and spacing do not matter"
    assert t.search(names, "lab/frontier") == ["Lab/Frontier/Warm"], "a slash in the query is just a word break"
    assert t.search(names, "nothing") == []
    tips = {"Lab/Frontier/Warm": "A warm, saturated lab look", "B&W/Soft": "Gentle contrast, lifted blacks"}
    assert t.search(names, "gentle", tips) == ["B&W/Soft"], "a built-in preset's description counts"
    assert t.search(names, "gentle") == [], "and only when it is given"
    assert t.search(names, "saturated frontier", {"lab / FRONTIER / warm": "A warm, saturated lab look"}) == ["Lab/Frontier/Warm"], "the description is found whatever the spacing of its name"


_SCRIPT = textwrap.dedent(r'''
    import os, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_GPU"] = "off"
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    from photoeditor.desktop.view.look_presets_panel import LookPresetsPanel
    panel = LookPresetsPanel(); panel.show(); app.processEvents()
    panel.set_presets(["B&W/Number 1", "B&W/Soft", "Warm Sky"])
    panel.set_builtin_presets(["Film Stocks/Kodak/Portra", "Scanners/Frontier 100"], {"Scanners/Frontier 100": "A warm lab look"})
    tree = panel._tree
    folders = lambda: [tree.topLevelItem(i) for i in range(tree.topLevelItemCount()) if tree.topLevelItem(i).childCount()]

    # nothing typed: the whole list, folders closed, no count
    assert tree.names_in_view() == ["B&W/Number 1", "B&W/Soft", "Warm Sky"] and panel._found.isHidden()
    assert not any(f.isExpanded() for f in folders())

    # typing narrows the list, opens the folders the matches are in, and says how many are left
    panel.search("b&w")
    assert tree.names_in_view() == ["B&W/Number 1", "B&W/Soft"] and all(f.isExpanded() for f in folders())
    assert panel._found.text() == "2 of 3 presets" and not panel._found.isHidden()
    panel.search("b&w soft")
    assert tree.names_in_view() == ["B&W/Soft"] and panel._found.text() == "1 of 3 presets"
    panel.search("warm")
    assert tree.names_in_view() == ["Warm Sky"]

    # nothing here, but the other list has some: the box says so
    panel.search("portra")
    assert tree.names_in_view() == [] and tree.topLevelItem(0).text(0) == "No preset matches."
    assert panel._found.text() == "No match here; 1 in Built-in Presets", panel._found.text()
    panel.search("zzzz")
    assert panel._found.text() == "No match here"

    # the search stays when the list is switched, and a built-in preset is found by its description too
    panel.search("portra"); panel._builtin_btn.click()
    assert tree.names_in_view() == ["Film Stocks/Kodak/Portra"]
    panel.search("warm")
    assert tree.names_in_view() == ["Scanners/Frontier 100"], "found by its description"
    panel.search("warm lab"); assert tree.names_in_view() == ["Scanners/Frontier 100"]
    panel.search("frontier"); panel._mine_btn.click()
    assert tree.names_in_view() == [] and panel._found.text() == "No match here; 1 in Built-in Presets"

    # clearing brings the whole list back, the folders closed again (a search opening them is not the person's choice)
    panel.search("")
    assert tree.names_in_view() == ["B&W/Number 1", "B&W/Soft", "Warm Sky"] and panel._found.isHidden() and not any(f.isExpanded() for f in folders())
    panel.search("b&w"); QTest.keyClick(panel._search, Qt.Key.Key_Escape)
    assert panel.search_text() == "" and len(tree.names_in_view()) == 3, "Esc clears the box"

    # the selection survives a search that still shows it; Enter and Down pick the first one found
    tree.select_name("B&W/Soft")
    panel.search("soft"); assert panel.selected() == "B&W/Soft"
    panel.search("b&w"); assert panel.selected() == "B&W/Soft", "still in the list, so still selected"
    panel.search("warm"); assert panel.selected() is None, "gone from the list, so no longer selected"
    panel.search("b&w"); panel._search.returnPressed.emit()
    assert panel.selected() == "B&W/Number 1" and tree.hasFocus()
    panel.search("warm"); panel._search.setFocus(); QTest.keyClick(panel._search, Qt.Key.Key_Down)
    assert panel.selected() == "Warm Sky"

    # it works on the list that is shown: applying what was found still asks for the right preset
    asked = []
    panel.apply_requested.connect(asked.append); panel.set_has_photo(True)
    panel.search("soft"); tree.select_name("B&W/Soft"); panel._apply_btn.click()
    assert asked == ["B&W/Soft"]
    print("OK")
''')


def test_the_presets_panel_has_a_search_box_that_narrows_the_list():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=120, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-2500:]
