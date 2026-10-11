"""Find (Ctrl+K): matching by name and by common words, and going to the thing it found."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from photoeditor.features.find import logic as F  # noqa: E402

ENTRIES = [
    F.Entry("module", "Exposure", "Editor"), F.Entry("control", "Exposure", "in Exposure"), F.Entry("module", "Crop & Rotate", "Editor"),
    F.Entry("control", "Angle", "in Crop & Rotate"), F.Entry("control", "Distortion", "in Crop & Rotate"), F.Entry("control", "Vertical", "in Crop & Rotate"),
    F.Entry("module", "Contrast", "Editor"), F.Entry("control", "Contrast", "in Negative"), F.Entry("control", "Saturation", "in Color"),
    F.Entry("action", "Auto Crop && Straighten".replace("&&", "&"), "Edit menu"), F.Entry("module", "Flat Field", "Editor"),
    F.Entry("action", "Export Selected...", "File menu"), F.Entry("module", "Export", "Editor"), F.Entry("control", "Output sharpening", "in Export"),
    F.Entry("control", "Sharpening", "in Sharpening"), F.Entry("module", "Sharpening", "Editor"),
]


def titles(q, entries=ENTRIES):
    return [(e.kind, e.title) for e in F.search(entries, q)]


def test_a_common_word_finds_the_control_that_does_it():
    assert titles("brightness")[0][1] == "Exposure"
    assert ("control", "Angle") in titles("straighten") and ("action", "Auto Crop & Straighten") in titles("straighten")
    assert titles("vignette")[0] == ("module", "Flat Field")
    assert ("control", "Distortion") in titles("barrel")
    assert titles("perspective")[0][1] in ("Vertical", "Crop & Rotate"), titles("perspective")
    assert ("control", "Contrast") in titles("iso-r") or ("control", "Contrast") in titles("grade")


def test_a_name_beats_a_synonym_and_a_start_beats_the_middle():
    assert titles("exp")[0][1] == "Exposure" and titles("sharp")[0][1] == "Sharpening"
    assert titles("contrast")[0][1] == "Contrast"
    got = [t for _k, t in titles("sharpening")]
    assert got.index("Sharpening") < got.index("Output sharpening"), got


def test_every_word_must_match_and_nothing_is_not_everything():
    assert titles("output sharpening")[0] == ("control", "Output sharpening")
    assert titles("exposure zzzz") == [] and titles("") == [] and titles("   ") == [] and titles("???") == []
    assert titles("EXPOSURE")[0][1] == "Exposure", "case does not matter"


def test_where_it_is_helps_and_results_are_capped_and_not_repeated():
    assert titles("crop angle")[0] == ("control", "Angle")
    many = [F.Entry("control", f"Slider {i}", "in Big") for i in range(40)] + [F.Entry("control", "Slider 1", "in Big")]
    out = F.search(many, "slider", limit=10)
    assert len(out) == 10 and len({e.title for e in out}) == 10
    found = F.search(many, "slider 1", limit=50)
    assert found[0].title == "Slider 1" and len(found) >= 11


_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.features.find import logic as F
    S.save({"scan_quality": False})
    p = os.path.join(work, "a.png"); cv2.imwrite(p, np.full((60, 90, 3), 100, np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view.find_dialog import FindDialog
    from photoeditor.desktop.view.collapsible_panel import CollapsiblePanel
    from photoeditor.desktop.view.slider_row import SliderRow
    win = aw.AppWindow(); win.show(); win.controller.open_file(p)
    def pump(ms=400):
        end = time.time() + ms / 1000
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(100)
    entries = win.find_entries()
    kinds = {k: sum(1 for e in entries if e.kind == k) for k in ("module", "control", "action")}
    assert kinds["module"] >= 15 and kinds["control"] >= 25 and kinds["action"] >= 20, kinds
    names = {e.title for e in entries}
    for want in ("Exposure", "Crop & Rotate", "Angle", "Horizontal", "Vertical", "Saturation", "Export", "Output sharpening", "Check Roll Consistency...", "Find a Control or Action..."):
        assert want in names or want.rstrip(".") in names, want
    assert [e.title for e in F.search(entries, "brightness")][0] == "Exposure"

    # going to a slider shows its panel and puts focus on it
    ent = next(e for e in F.search(entries, "keystone") if isinstance(e.target, SliderRow))
    panel = win._panel_of(ent.target)
    panel.set_expanded(False); pump(300)
    win.go_to_entry(ent); pump(600)
    assert panel._expanded and panel.is_pinned(), "its module is opened and kept open"
    assert ent.target._slider.hasFocus() or ent.target.isVisible()

    # a Workbench-only module takes you to the Workbench
    wb = next(e for e in entries if e.kind == "module" and e.title == "Smart Collections")
    assert not win.lighttable_active()
    win.go_to_entry(wb); pump(500)
    assert win.lighttable_active()
    ed = next(e for e in entries if e.kind == "module" and e.title == "Exposure")
    win.go_to_entry(ed); pump(500)
    assert not win.lighttable_active()

    # a menu action is run
    asked = []
    act = next(e for e in entries if e.kind == "action" and "shortcut" in e.title.lower())
    act.target.triggered.connect(lambda: asked.append(1))
    win.go_to_entry(act); assert asked == [1]

    # the dialog: typing narrows, Down/Enter chooses
    chosen = []
    dlg = FindDialog(entries, win); dlg.chosen.connect(chosen.append); dlg.show()
    dlg.box.setText("brightness"); assert dlg.list.count() >= 1 and "Exposure" in dlg.list.item(0).text()
    QTest.keyClick(dlg.box, Qt.Key.Key_Down)
    if dlg.list.count() > 1: assert dlg.list.currentRow() == 1
    QTest.keyClick(dlg.box, Qt.Key.Key_Up); QTest.keyClick(dlg.box, Qt.Key.Key_Return)
    assert len(chosen) == 1 and chosen[0].title == "Exposure"
    d2 = FindDialog(entries, win); d2.show(); d2.box.setText("qqqqqq"); assert d2.list.count() == 1 and "Nothing matches" in d2.list.item(0).text()
    assert win._find_action.shortcut().toString() == "Ctrl+K"
    win.close()
    print("FIND OK")
    sys.stdout.flush(); os._exit(0)
''')


def test_find_goes_to_modules_sliders_and_menu_actions():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert "FIND OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3500:]
