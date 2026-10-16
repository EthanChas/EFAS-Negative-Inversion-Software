"""Hotstack folders: right-click a folder in a Library list and mark it, and it is saved, drawn red (icon and name) in both lists, and watched - each photo that lands in it, or in a
day folder inside it, is read in, selected in the Workbench and, if asked, opened in the editor; unmark it and nothing more arrives."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from photoeditor.features.settings import logic as S

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_the_settings_for_hotstack_folders_are_kept_and_checked(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    assert S.load()["hotstack_folders"] == [] and S.load()["live_open_editor"] is True and S.load()["live_session"] == []
    S.save({"hotstack_folders": ["D:/Scans/Live", "E:/More"], "live_open_editor": False, "live_session": ["D:/a.CR2", 5]})
    assert S.load()["hotstack_folders"] == ["D:/Scans/Live", "E:/More"] and S.load()["live_open_editor"] is False
    assert S.load()["live_session"] == ["D:/a.CR2"], "an entry that is not a path is dropped"
    S.save({"hotstack_folders": "D:/x", "live_open_editor": "yes"})
    assert S.load()["hotstack_folders"] == [] and S.load()["live_open_editor"] is True, "a wrong-typed value falls back to the default"


_TREE_SCRIPT = textwrap.dedent(r"""
    import os, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    top = os.path.join(work, "scans"); sub = os.path.join(top, "roll1")
    os.makedirs(sub)
    for folder in (top, sub):
        open(os.path.join(folder, "a.jpg"), "wb").write(b"x")
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QColor
    app = QApplication([])
    from photoeditor.desktop.view.folder_tree import FolderTree
    from photoeditor.theme.tokens import THEME
    red = QColor(THEME.status_critical)
    tree = FolderTree(removable=True)
    tree.set_roots([top])
    root = tree.topLevelItem(0)
    asked = []
    tree.hotstack_requested.connect(lambda folder, on: asked.append((folder, on)))
    def action(menu, text):
        return next(a for a in menu.actions() if a.text() == text)

    # the right-click menu offers the mark; choosing it asks for it
    menu = tree.build_context_menu(root)
    action(menu, "Mark as Hotstack").trigger()
    assert asked == [(top, True)]
    assert root.foreground(0).color() != red, "nothing changes until the window has saved the choice"

    # marked: the icon and the name turn red - for a folder that is shown now, and for one that is only made when it is opened
    tree.set_hotstack([sub])
    tree.expandItem(root)
    child = root.child(0)
    assert child.data(0, 256) == sub and child.foreground(0).color() == red and child.foreground(1).color() == red
    assert root.foreground(0).color() != red, "only the marked folder is red"
    plain = tree._folder_icon(False).pixmap(16, 16).toImage(); hot = child.icon(0).pixmap(16, 16).toImage()
    assert plain != hot, "the icon is red too"
    assert action(tree.build_context_menu(child), "Remove Hotstack Mark") and tree.is_hotstack(sub) and not tree.is_hotstack(top)
    action(tree.build_context_menu(child), "Remove Hotstack Mark").trigger()
    assert asked[-1] == (sub, False)
    tree.collapseItem(root); tree.expandItem(root)
    assert tree.topLevelItem(0).child(0).foreground(0).color() == red, "a folder is drawn red again when the list is rebuilt"
    tree.set_hotstack([])
    assert tree.topLevelItem(0).child(0).foreground(0).color() != red
    tree.set_roots([top]); tree.set_hotstack([top])
    assert tree.topLevelItem(0).foreground(0).color() == red, "after a refresh too"
    print("OK")
""")


def test_a_folder_tree_marks_hotstack_folders_in_red():
    out = subprocess.run([sys.executable, "-c", _TREE_SCRIPT], capture_output=True, text=True, timeout=120, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-2500:]


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp()
    shoot = os.path.join(work, "shoot"); other = os.path.join(work, "other")
    os.makedirs(shoot); os.makedirs(other)
    import numpy as np, cv2
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False, "advanced_mode": False})
    def frame(path, seed):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cv2.imwrite(path, np.random.default_rng(seed).integers(30, 220, (60, 90, 3), dtype=np.uint8))
    frame(os.path.join(shoot, "old1.png"), 1); frame(os.path.join(shoot, "old2.png"), 2); frame(os.path.join(other, "elsewhere.png"), 3)
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.features.library import query as Q
    from photoeditor.theme.tokens import THEME
    red = QColor(THEME.status_critical)
    win = aw.AppWindow(); win.show(); win.open_folder(other)
    def pump(s):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    def until(cond, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            app.processEvents()
            if cond(): return True
            time.sleep(0.01)
        return False
    pump(1.0)
    lt = win._lighttable; live = win._live
    live._interval = 60
    got = []; live.arrived.connect(got.append)
    win.set_view("lighttable"); pump(0.5)
    assert until(lambda: win._index_worker is None)
    assert not hasattr(lt, "_live_btn"), "there is no Live Folder button any more"
    assert not live.running() and "right-click" in lt._hot_info.text()

    # right-click the folder in the Workbench's Library list and mark it
    tree = lt.library_panel._tree
    tree.add_root(shoot)
    item = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount()) if tree.topLevelItem(i).data(0, 256) == shoot)
    next(a for a in tree.build_context_menu(item).actions() if a.text() == "Mark as Hotstack").trigger(); pump(0.3)
    assert live.running() and live.folders() == [shoot] and S.load()["hotstack_folders"] == [shoot], "saved, and watched"
    assert item.foreground(0).color() == red and tree.is_hotstack(shoot) and win._library_panel._tree.is_hotstack(shoot), "red in both lists"
    assert next(a for a in tree.build_context_menu(item).actions() if "Hotstack" in a.text()).text() == "Remove Hotstack Mark"
    assert "shoot" in lt._hot_info.text() and shoot in lt._hot_btn.toolTip()
    assert until(lambda: win._index_worker is None and lt.row_count() >= 3), lt.row_count()
    base = lt.row_count()

    # a photo lands in a day folder (as EOS Utility makes them): it is selected in the Workbench and the editor is left alone
    lt._live_editor_action.setChecked(False); assert S.load()["live_open_editor"] is False
    new1 = os.path.join(shoot, "2026_10_16", "new1.png")
    frame(new1, 11)
    assert until(lambda: got), "the photo arrived"
    assert got[-1] == [new1]
    assert lt.row_count() == base + 1 and [Q.norm(p) for p in lt.selected_paths()] == [Q.norm(new1)], lt.selected_paths()
    assert win.lighttable_active() and "new1.png arrived" in win._coord_label.text()

    # with "show in the editor" on, the next one opens large, and the filmstrip has it
    lt._live_editor_action.setChecked(True); assert S.load()["live_open_editor"] is True
    new2 = os.path.join(shoot, "new2.png")
    n = len(got); frame(new2, 12)
    assert until(lambda: len(got) > n) and got[-1] == [new2]
    assert until(lambda: not win.lighttable_active() and Q.norm(win.controller.state.image_path or "") == Q.norm(new2)), (win.lighttable_active(), win.controller.state.image_path)
    assert Q.norm(new2) in [Q.norm(p) for p in win._filmstrip.paths()], "the strip lists the new frame"

    # a search that hides the new photo does not break it, and says so
    win.set_view("lighttable"); pump(0.5)
    lt._live_editor_action.setChecked(False)
    lt._search.setText("old1"); lt.apply_filters()
    new3 = os.path.join(shoot, "new3.png")
    n = len(got); frame(new3, 13)
    assert until(lambda: len(got) > n)
    assert "hiding it" in win._coord_label.text() and win.lighttable_active(), win._coord_label.text()
    lt.clear_filters(); lt._search.setText(""); lt.apply_filters()

    # a second folder marked as well is watched too
    tree.add_root(other)
    item2 = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount()) if tree.topLevelItem(i).data(0, 256) == other)
    next(a for a in tree.build_context_menu(item2).actions() if a.text() == "Mark as Hotstack").trigger(); pump(0.3)
    assert sorted(live.folders()) == sorted([shoot, other]) and sorted(S.load()["hotstack_folders"]) == sorted([shoot, other])
    n = len(got); frame(os.path.join(other, "o1.png"), 21)
    assert until(lambda: len(got) > n) and got[-1] == [os.path.join(other, "o1.png")]

    # unmarked from the editor's list: it is no longer red or watched, and nothing more arrives from it
    win._on_hotstack_requested(other, False); pump(0.2)
    assert live.folders() == [shoot] and S.load()["hotstack_folders"] == [shoot] and not tree.is_hotstack(other) and item2.foreground(0).color() != red
    n = len(got); frame(os.path.join(other, "o2.png"), 22); pump(0.6)
    assert len(got) == n, "an unmarked folder is not watched"
    win._on_hotstack_requested(shoot, False); pump(0.2)
    assert not live.running() and S.load()["hotstack_folders"] == [] and item.foreground(0).color() != red
    n = len(got); frame(os.path.join(shoot, "new4.png"), 14); pump(0.6)
    assert len(got) == n, "off: nothing arrives"
    win._on_hotstack_requested(shoot, True); pump(0.3)
    n = len(got); frame(os.path.join(shoot, "new5.png"), 15)
    assert until(lambda: len(got) > n) and got[-1] == [os.path.join(shoot, "new5.png")], "new4 was there when it was marked again, so it is not news"
    win.close()

    # the mark is remembered: a new window watches the folder and draws it red from the start
    win2 = aw.AppWindow(); win2.show(); pump(0.5)
    assert win2._live.folders() == [shoot] and win2._lighttable.library_panel._tree.is_hotstack(shoot) and win2._library_panel._tree.is_hotstack(shoot)
    win2.close()
    print("OK")
""")


def test_a_hotstack_folder_is_marked_by_right_click_and_its_photos_are_shown_as_they_arrive():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC, "PHOTOEDITOR_AUDIO": "off"})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-2500:]


_LEFT_SCRIPT = textwrap.dedent(r"""
    import os, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    from PyQt6.QtWidgets import QApplication, QScrollArea
    app = QApplication([])
    from photoeditor.desktop.view.lighttable_view import LighttableView
    def host_width(long_lens):
        lt = LighttableView(None)
        if long_lens:
            lt._lens.addItem("EF100mm f/2.8L Macro IS USM  (700)", "x"); lt._camera.addItem("Canon EOS 5D Mark IV with a very long name  (512)", "y")
        lt.show(); app.processEvents()
        host = lt.findChildren(QScrollArea)[0].widget()
        width = host.minimumSizeHint().width()
        lt.close()
        return width
    plain, long = host_width(False), host_width(True)
    assert long == plain, (plain, long)   # a long lens or camera name does not widen the left column
    print("OK")
""")


def test_a_long_lens_name_does_not_push_the_workbench_left_column_out_of_sight():
    out = subprocess.run([sys.executable, "-c", _LEFT_SCRIPT], capture_output=True, text=True, timeout=120, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-2500:]
