"""The Classroom page in the window: the guides and the search, Previous / Next, links between guides, the shortcut table, remembering which guide you were reading, and Show me,
which takes the person to the tool a guide is about."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from photoeditor.features.settings import logic as S

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_the_classroom_remembers_only_the_last_guide_and_checks_it(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    assert S.load()["classroom_last"] == "" and "classroom_done" not in S.load(), "there is no checklist to keep"
    S.save({"classroom_last": "dust-auto"})
    assert S.load()["classroom_last"] == "dust-auto"
    S.save({"classroom_last": 7})
    assert S.load()["classroom_last"] == "", "a wrong type falls back to the default"


_VIEW_SCRIPT = textwrap.dedent(r"""
    import os, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_GPU"] = "off"
    from PyQt6.QtCore import Qt, QEvent, QUrl
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    from photoeditor.features.classroom.content import COURSE
    from photoeditor.features.classroom import logic as L
    from photoeditor.features.settings import logic as S
    from photoeditor.desktop.view.classroom_view import ClassroomView
    total = len(COURSE.lessons)
    view = ClassroomView(); view.resize(1200, 800); view.show(); app.processEvents()

    # it opens on the first lesson, with the whole course in the tree in order
    assert view.current_lesson_id() == "what-is-efas" and "What EFAS does" in view._title.text()
    assert view._tree.topLevelItemCount() == len(COURSE.sections)
    assert [view._tree.topLevelItem(i).text(0).split("   (")[0] for i in range(view._tree.topLevelItemCount())][:4] == ["Start here", "Photography basics", "How film works", "Scanning your film"]
    assert view._count.text() == f"1 of {total}" and not view._prev.isEnabled() and view._next.isEnabled()
    assert not hasattr(view, "_done_btn") and not hasattr(view, "_progress"), "the Classroom is a guide to read, not a checklist"
    assert not view._show_btn.isVisibleTo(view), "a lesson that is not about one tool has no Show me button"

    # next / previous walk the course; the lesson page shows its text, and a lesson about a tool has Show me
    view._next.click(); assert view.current_lesson_id() == "how-this-guide-works" and view._prev.isEnabled()
    view._prev.click(); assert view.current_lesson_id() == "what-is-efas"
    view.open_lesson("exposure-module")
    assert view._show_btn.isVisibleTo(view) and "Exposure" in view._show_btn.text() and "stops" in view.page_text().lower() and "Read next" in view.page_text()
    asked = []; view.module_requested.connect(asked.append); view._show_btn.click(); assert asked == ["Exposure"]
    assert view._count.text().endswith(f" of {total}") and "Tool guide" in view._crumb.text() and view._tree.currentItem().data(0, Qt.ItemDataRole.UserRole + 1) == "exposure-module"

    # "On this page" lists the headings of an in-depth guide, and a click scrolls the guide to that part
    view.open_lesson("color-mixer-module")
    heads = L.headings(COURSE.get("color-mixer-module").text)
    assert view._outline.isVisibleTo(view) and view.outline_titles() == heads and len(heads) >= 4
    assert view._page.verticalScrollBar().value() == 0
    view.go_to_heading(len(heads) - 1); app.processEvents()
    assert view._page.verticalScrollBar().value() > 0, "the guide scrolled to its last part"
    view.open_lesson("exposure-module")
    assert view._page.verticalScrollBar().value() == 0 and view.outline_titles() == L.headings(COURSE.get("exposure-module").text)

    # a link in a lesson opens that lesson
    view._on_anchor(QUrl("lesson:dust-manual")); assert view.current_lesson_id() == "dust-manual"

    # search: the list of lessons that mention every word, best first; Esc clears; Enter opens the first
    view.search("flat field"); assert view._stack.currentIndex() == 1 and view.result_ids()[0] == "flat-field-module" and "guide" in view._found_label.text() and "found" in view._found_label.text()
    for w in view.result_ids(): assert COURSE.get(w) is not None
    view._search.setFocus()
    for t in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        app.sendEvent(view._search, QKeyEvent(t, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))
    assert view.current_lesson_id() == "flat-field-module"
    for t in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        app.sendEvent(view._search, QKeyEvent(t, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert view._search.text() == "" and view._stack.currentIndex() == 0 and view.result_ids() == []
    view.search("zzzzqqqq"); assert view.result_ids() == [] and "No guide mentions" in view._found_label.text()
    view.search("")
    view.search("grain"); first = view.result_ids()[0]; view._list.setCurrentRow(1); assert view.current_lesson_id() == view.result_ids()[1]
    view._on_anchor(QUrl("lesson:glossary")); assert view._search.text() == "" and view.current_lesson_id() == "glossary", "following a link leaves the search"

    # remembered: a new page opens on the guide that was being read, and that is all that is kept
    view.open_lesson("exposure-module")
    assert S.load()["classroom_last"] == "exposure-module"
    view2 = ClassroomView()
    assert view2.current_lesson_id() == "exposure-module"

    # the keyboard lesson gets the shortcut table from the window
    view2.set_shortcuts_provider(lambda: [("Culling a roll", [("K", "Mark keeper"), ("Ctrl+K", "Find <a control>")])])
    view2.open_lesson("shortcuts")
    text = view2.page_text()
    assert "Culling a roll" in text and "Mark keeper" in text and "Find <a control>" in text
    view2.set_shortcuts_provider(lambda: [])
    view2.open_lesson("shortcuts"); assert "Settings > Keybinds" in view2.page_text()
    print("OK")
""")


def test_the_classroom_page_lists_searches_and_remembers_lessons():
    out = subprocess.run([sys.executable, "-c", _VIEW_SCRIPT], capture_output=True, text=True, timeout=180, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-2500:]


_WINDOW_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"; os.environ["PHOTOEDITOR_GPU"] = "off"
    from PyQt6.QtWidgets import QApplication, QScrollArea
    app = QApplication([])
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False, "advanced_mode": True})
    from photoeditor.features.classroom.content import COURSE
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view.collapsible_panel import CollapsiblePanel
    win = aw.AppWindow(); win.resize(1600, 1000); win.show()   # a real window's size: in a small one a module's top can really be out of view
    def pump(s):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(0.5)

    # the Classroom button is a real page now, not a "coming soon" notice
    assert win.view_name() == "editor"
    win.set_view("classroom"); pump(0.3)
    assert win.view_name() == "classroom" and win._classroom.isVisible() and win._classroom.current_lesson_id() == "what-is-efas"
    assert win._view_buttons["classroom"].isChecked() and "coming soon" not in win._view_buttons["classroom"].toolTip().lower()
    assert win._view_buttons["maps"].toolTip().lower().endswith("coming soon")

    # every tool the lessons say they are about is a module in the window (so Show me can go to it)
    titles = {w._title for w in win.findChildren(CollapsiblePanel)}
    missing = sorted({l.module for l in COURSE.lessons if l.module} - titles)
    assert not missing, missing

    # Show me: the editor comes up with that module open
    win._classroom.open_lesson("tone-curve-module")
    win._classroom._show_btn.click(); pump(0.8)
    assert win.view_name() == "editor"
    panel = next(w for w in win.findChildren(CollapsiblePanel) if w._title == "Tone Curve")
    assert panel._expanded and panel.isVisible(), "the Tone Curve module is open and in view"
    pump(0.5)
    assert win._open_tab == "exposure" and win._wb_tools_panel._is_open and panel.width() > 100 and not panel.visibleRegion().isEmpty(), "its tab is open beside the rail, not shut"
    win.set_view("classroom"); pump(0.2)
    assert win._classroom.current_lesson_id() == "tone-curve-module"

    # a module in another tab: that tab opens (and the one that was open closes), and the module is shown in it
    win.set_view("classroom"); pump(0.2)
    for lesson_id, tab, title in (("film-type-setting", "negative", "Negative"), ("color-module", "color", "Color"), ("sharpening-module", "detail", "Sharpening")):
        win._classroom.open_lesson(lesson_id)
        assert win._classroom._show_btn.text().endswith(title), (lesson_id, win._classroom._show_btn.text())
        win._classroom._show_btn.click(); pump(1.0)
        panel = next(w for w in win.findChildren(CollapsiblePanel) if w._title == title)
        assert win.view_name() == "editor" and win._open_tab == tab and panel._expanded, (title, win._open_tab)
        assert panel.width() > 100 and panel.visibleRegion().boundingRect().height() > 20, f"the {title} module is on screen"
        assert win._tool_rail.visibleRegion().boundingRect().height() > 100, f"the rail is still in view with {title} open"
        w = panel
        while w is not None:
            if isinstance(w, QScrollArea): assert w.horizontalScrollBar().value() == 0, "nothing was pushed sideways"
            w = w.parentWidget()
        win.set_view("classroom"); pump(0.2)

    # a lesson about a module in the Workbench goes there
    win._classroom.open_lesson("workbench-lesson")
    win._classroom._show_btn.click(); pump(0.8)
    assert win.view_name() == "lighttable"
    win.set_view("classroom"); pump(0.2)

    # the keyboard lesson follows the keys as they are bound
    win._classroom.open_lesson("shortcuts"); pump(0.2)
    text = win._classroom.page_text()
    assert "Mark keeper" in text and "Previous photo" in text
    win.close()
    print("OK")
""")


def test_the_classroom_button_opens_the_page_and_show_me_goes_to_the_tool():
    out = subprocess.run([sys.executable, "-c", _WINDOW_SCRIPT], capture_output=True, text=True, timeout=240, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-2500:]
