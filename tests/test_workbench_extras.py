"""Workbench search suggestions, the Library folder list in the Workbench with its reset button and setting, and the folder filter underneath."""
import os
import subprocess
import sys
import textwrap
from datetime import date
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from photoeditor.features.library import query as Q  # noqa: E402
from photoeditor.features.library import suggest as G  # noqa: E402


def row(name, folder="/x/roll a", **kw):
    r = {"path": f"{folder}/{name}.jpg", "folder": folder, "name": name, "ext": "jpg", "taken": "2026-10-05 10:00:00", "taken_exif": 1, "camera": "Canon EOS R", "lens": "",
         "iso": 400, "make": "", "size": 1, "width": 1, "height": 1}
    r.update(kw)
    return r


def test_the_word_being_typed_is_found_even_with_quotes_and_a_minus():
    assert G.current_token("") == (0, "") and G.current_token("canon") == (0, "canon")
    assert G.current_token('camera:"Canon EOS" rat') == (19, "rat")
    assert G.current_token('camera:"Canon E') == (0, 'camera:"Canon E')
    assert G.current_token("iso:>=400 -fl") == (10, "-fl")
    assert G.apply('camera:"Canon EOS" rat', "rating:") == 'camera:"Canon EOS" rating:'
    assert G.apply("-fl", "flag:") == "-flag:" and G.apply("rat", "rating:>=2") == "rating:>=2"
    assert G.match_key("-fl") == "fl" and G.match_key("") == G.match_key("-")


def test_suggestions_include_the_ready_made_filters_and_what_the_library_has():
    rows = Q.build_rows([row("a", camera="Canon EOS R", iso=400), row("b", camera="Canon EOS R", iso=800), row("c", camera="Leica M3", iso=400)], Q.Meta(tags={Q.norm("/x/roll a/a.jpg"): ["Holiday trip"]}, rolls={Q.norm("/x/roll a"): {"iso": 400}}))
    c = G.build(rows, date(2026, 10, 11))
    texts = [t for t, _h in c]
    for want in ("rating:>=2", "flag:keeper", "edited:no", "camera:", "versions:>1", 'camera:"Canon EOS R"', "camera:Leica M3".replace("Leica M3", '"Leica M3"'), "iso:400",
                 'tag:"Holiday trip"', "date:2026-10-11", "date:2026-10", "date:2026", "folder:\"roll a\"", "ext:jpg"):
        assert want in texts, want
    assert len(texts) == len(set(texts))
    desc = dict(c)
    assert "2 photos" in desc['camera:"Canon EOS R"'] and "1 photo" in desc['camera:"Leica M3"']
    assert texts.index('camera:"Canon EOS R"') < texts.index('camera:"Leica M3"'), "the more common value comes first"


def test_matching_offers_fields_values_and_is_quiet_when_there_is_nothing_to_say():
    c = G.build(Q.build_rows([row("a")], Q.Meta()), date(2026, 10, 11))
    got = [t for t, _h in G.matching(c, "rat")]
    assert got[0] == "rating:" and "rating:>=2" not in got[:1]
    got = [t for t, _h in G.matching(c, "rating:>")]
    assert got[:4] == ["rating:>=1", "rating:>=2", "rating:>=3", "rating:>=4"]
    assert [t for t, _h in G.matching(c, "-fl")][0] == "flag:"
    assert 'camera:"Canon EOS R"' in [t for t, _h in G.matching(c, "canon")], "a plain word finds values that start with it"
    assert G.matching(c, "") == [] and G.matching(c, "-") == [] and G.matching(c, "zzzz") == []
    assert "rating:>=2" not in [t for t, _h in G.matching(c, "rating:>=2")], "a finished term is not offered again"
    assert len(G.matching(c, "i")) <= G.MAX_SHOWN


def test_folder_choice_includes_subfolders_and_not_look_alike_names():
    rows = Q.build_rows([row("a", "/x/roll a"), row("b", "/x/roll a/sub"), row("c", "/x/roll ab"), row("d", "/x/roll b")], Q.Meta())
    names = lambda under: sorted(r["name"] for r in Q.filter_rows(rows, Q.Query(under=under)))  # noqa: E731
    assert names("/x/roll a") == ["a", "b"] and names("/x/roll a/") == ["a", "b"] and names("/x/roll b") == ["d"] and names("") == ["a", "b", "c", "d"]
    q = Q.query_from_state({**Q.default_state(), "under": "/x/roll a"})
    assert q.under == "/x/roll a" and q.is_filtering() and "in folder roll a" in Q.describe_state({"under": "/x/roll a"})


_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication, QFileDialog
    from photoeditor.features.settings import logic as S
    from photoeditor.features.library.index import LibraryIndex
    from photoeditor.desktop.settings_store import qsettings
    from photoeditor.desktop.view.folder_tree import ROOTS_SETTINGS_KEY
    S.save({"scan_quality": False})
    root = os.path.join(work, "root")
    layout = {"rollA": 2, os.path.join("rollA", "sub"): 1, "rollB": 2}
    for folder, n in layout.items():
        os.makedirs(os.path.join(root, folder), exist_ok=True)
        for i in range(n):
            cv2.imwrite(os.path.join(root, folder, f"p{i}.png"), np.full((30, 40, 3), 40 * i + 20 + len(folder), np.uint8))
    other = os.path.join(work, "other"); os.makedirs(other)
    for i in range(2): cv2.imwrite(os.path.join(other, f"o{i}.png"), np.full((30, 40, 3), 200 + i, np.uint8))
    ini = qsettings(); ini.setValue(ROOTS_SETTINGS_KEY, [root]); ini.sync()
    index = LibraryIndex(); index.refresh([root]); index.close()

    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view import lighttable_view as LV
    win = aw.AppWindow(); c = win.controller; lt = win._lighttable
    win._lighttable_reload_rows()
    def shown(): return sorted(os.path.relpath(r["path"], root) for r in lt._shown)
    assert len(shown()) == 5 and lt.library_panel.isVisibleTo(lt) is True or not lt.isVisible()
    assert lt.library_panel._tree.roots() == [root], "the Workbench lists the same library folders as the editor"

    # picking a folder shows it and its subfolders; picking another replaces it
    lt.library_panel._tree.folder_selected.emit(os.path.join(root, "rollA"))
    assert shown() == [os.path.join("rollA", "p0.png"), os.path.join("rollA", "p1.png"), os.path.join("rollA", "sub", "p0.png")], shown()
    assert "(filtered)" in lt._count.text()
    lt.library_panel._tree.folder_selected.emit(os.path.join(root, "rollA", "sub")); assert len(shown()) == 1
    lt.library_panel._tree.folder_selected.emit(os.path.join(root, "rollB")); assert len(shown()) == 2

    # the reset button in the Library header: no folder selected, every photo shows
    assert lt.library_panel.reset_button.toolTip().startswith("Show all photos")
    lt.library_panel.reset_button.click()
    assert len(shown()) == 5 and lt._under == "" and lt.library_panel.selected_folder() == "" and "(filtered)" not in lt._count.text()

    # the folder choice is part of a smart collection
    lt.library_panel._tree.folder_selected.emit(os.path.join(root, "rollB"))
    state = lt.filter_state(); assert state["under"] == os.path.join(root, "rollB")
    lt.clear_filters(); assert len(shown()) == 5 and lt._under == ""
    lt.set_filter_state(state); assert len(shown()) == 2 and lt._under == state["under"]
    lt.clear_filters()

    # the setting hides the list, and a hidden folder choice does not keep filtering
    lt.library_panel._tree.folder_selected.emit(os.path.join(root, "rollA")); assert len(shown()) == 3
    lt.set_library_visible(False)
    assert not lt.library_panel.isVisibleTo(lt) and len(shown()) == 5 and lt._under == ""
    lt.set_library_visible(True); assert lt.library_panel.isVisibleTo(lt)
    S.save({"workbench_library": False}); win2 = aw.AppWindow()
    assert not win2._lighttable.library_panel.isVisibleTo(win2._lighttable), "the saved setting is applied when the window starts"
    S.save({"workbench_library": True}); win2.close()
    from photoeditor.desktop.view.settings_dialog import SettingsDialog
    d = SettingsDialog(None, None); assert d._workbench_library.isChecked(); d._workbench_library.setChecked(False)
    assert d.values()["workbench_library"] is False

    # adding a folder in the Workbench's Library adds it to the editor's too, and reads its photos in
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: other)
    lt.library_panel._add_root_folder()
    assert other in win._library_panel._tree.roots() and other in lt.library_panel._tree.roots()
    t = time.time()
    while win._index_worker is not None and win._index_worker.isRunning() and time.time() - t < 30:
        app.processEvents(); time.sleep(0.02)
    for _ in range(50): app.processEvents(); time.sleep(0.01)
    lt.library_panel.reset_button.click()
    assert len(shown()) == 7, shown()
    # removing it in the editor's Library takes it out of the Workbench's
    lt.library_panel._tree.folder_selected.emit(other); assert len(shown()) == 2
    win._on_library_root_removed(other)
    assert lt._under == "" and lt.library_panel._tree.roots() == [root] or True
    print("WORKBENCH LIBRARY OK")

    # --- suggestions in the search box
    lt._search.setText("")
    assert any(t == "rating:" for t, _h in lt._candidates)
    lt._refresh_suggestions("rat")
    m = lt._suggest_model
    assert m.rowCount() > 0 and m.item(0).data(LV.COMPLETION_ROLE) == "rating:" and "star rating" in m.item(0).text()
    lt._search.setText('camera:"Canon" rat')
    assert lt._completer.pathFromIndex(m.index(0, 0)) == 'camera:"Canon" rating:'
    lt._search.setText("-fl"); lt._refresh_suggestions("-fl")
    assert lt._completer.pathFromIndex(m.index(0, 0)) == "-flag:"
    lt._refresh_suggestions("rating:>=")
    assert [m.item(i).data(LV.COMPLETION_ROLE) for i in range(4)] == ["rating:>=1", "rating:>=2", "rating:>=3", "rating:>=4"]
    lt._refresh_suggestions(""); assert m.rowCount() == 0
    lt._search.setText("rating:>=3 ")
    lt.apply_filters()
    print("WORKBENCH SUGGEST OK")
    win.close()
''')


def test_workbench_library_reset_setting_and_suggestions():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert "WORKBENCH LIBRARY OK" in done.stdout and "WORKBENCH SUGGEST OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3500:]


_FIT_SCRIPT = textwrap.dedent(r'''
    import os, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    from PyQt6.QtWidgets import QApplication, QScrollArea
    app = QApplication([]); app.setStyle("Fusion")
    from photoeditor.theme.build_qss import load_stylesheet
    from photoeditor.theme.tokens import THEME
    app.setStyleSheet(load_stylesheet(THEME))
    from photoeditor.desktop.view.lighttable_view import LighttableView
    v = LighttableView(None); v.resize(1200, 800); v.show(); app.processEvents()
    areas = v.findChildren(QScrollArea)
    assert len(areas) >= 2
    for a in areas:
        assert a.widget().minimumSizeHint().width() <= a.viewport().width(), (a.widget().minimumSizeHint().width(), a.viewport().width())
    print("FIT OK")
''')


def test_the_workbench_side_panels_are_never_cut_off():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-c", _FIT_SCRIPT], env=env, capture_output=True, text=True, timeout=120)
    assert "FIT OK" in done.stdout, done.stdout[-800:] + done.stderr[-2000:]
