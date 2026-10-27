"""Selecting several photos: in the editor's filmstrip (Shift-click for a range, Ctrl-click to add or take away, Ctrl+A for all of them, a plain click opens one) and in the Workbench grid
(which already did). A selection of several photos is what the rating and flag keys and the right-click menu then act on."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False, "advanced_mode": False})
    rng = np.random.default_rng(0)
    paths = []
    for n in "abcdef":
        p = os.path.join(work, n + ".png"); cv2.imwrite(p, rng.integers(60, 190, (120, 180, 3), dtype=np.uint8)); paths.append(p)
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view.thumbnail_delegate import OPEN_ROLE
    from photoeditor.features.persistence import edit_store as E
    win = aw.AppWindow(); win.resize(1500, 900); win.show(); win.open_folder(work, prefer=paths[0])
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
    pump(2)
    names = lambda ps: [os.path.basename(p) for p in ps]
    opened = lambda: os.path.basename(win.controller.state.image_path)
    fs = win._filmstrip; lst = fs.list_widget()
    assert lst.count() == 6 and lst.selectionMode().name == "ExtendedSelection"
    def tile(i): return lst.visualItemRect(lst.item(i)).center()
    def click(i, mods=Qt.KeyboardModifier.NoModifier):
        QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, mods, tile(i)); pump(0.7)

    # a plain click opens the photo and selects only it
    click(1); assert opened() == "b.png" and names(fs.selected_paths()) == ["b.png"] and win.strip_selection() == []
    # Shift-click: the range from the open photo, and nothing is opened
    click(4, Qt.KeyboardModifier.ShiftModifier)
    assert opened() == "b.png" and names(fs.selected_paths()) == ["b.png", "c.png", "d.png", "e.png"], names(fs.selected_paths())
    assert names(win.strip_selection()) == ["b.png", "c.png", "d.png", "e.png"]
    # Ctrl-click adds one and takes one away, opening nothing
    click(5, Qt.KeyboardModifier.ControlModifier); click(2, Qt.KeyboardModifier.ControlModifier)
    assert opened() == "b.png" and names(fs.selected_paths()) == ["b.png", "d.png", "e.png", "f.png"], names(fs.selected_paths())
    # the open photo has its own mark, selected or not
    assert [lst.item(i).data(OPEN_ROLE) for i in range(6)] == [False, True, False, False, False, False]
    click(1, Qt.KeyboardModifier.ControlModifier)
    assert "b.png" not in names(fs.selected_paths()) and lst.item(1).data(OPEN_ROLE) is True and opened() == "b.png"

    # the rating and flag keys act on the whole selection; pressing the same key again takes the mark off all of them
    chosen = fs.selected_paths(); assert names(chosen) == ["d.png", "e.png", "f.png"]
    db = win.controller._db
    win.run_photo_action("rating_3"); pump(0.3)
    assert E.get_ratings(db, chosen) == {p: 3 for p in chosen} and all(fs.ratings().get(p) == 3 for p in chosen)
    assert names(fs.selected_paths()) == ["d.png", "e.png", "f.png"], "still selected"
    win.run_photo_action("rating_3"); pump(0.3)
    assert not any(E.get_ratings(db, chosen).get(p) for p in chosen), E.get_ratings(db, chosen)
    win.run_photo_action("flag_keeper"); pump(0.3)
    assert E.get_flags(db, chosen) == {p: "keeper" for p in chosen} and opened() == "b.png", "no auto-advance with several selected"
    win.run_photo_action("flag_keeper"); pump(0.3)
    assert not E.get_flags(db, chosen)
    win.run_photo_action("flag_rejected"); pump(0.3)
    assert E.get_flags(db, chosen) == {p: "rejected" for p in chosen}
    win.run_photo_action("flag_clear"); pump(0.3)
    assert not E.get_flags(db, chosen)

    # the right-click menu over the selection acts on all of it (a strip of its own, so nothing is really moved or deleted by the test)
    from photoeditor.desktop.view.filmstrip import Filmstrip
    bare = Filmstrip()
    menu = bare.build_selection_menu(chosen)
    texts = [a.text() for a in menu.actions() if a.text()]
    assert texts == ["Rate 3 photos", "Flag 3 photos", "Paste Settings to 3 photos", "Set Settings for 3 photos...", "Remove 3 photos from Workbench", "Move 3 photos to Folder...", "Delete 3 photos from Disk..."], texts
    assert not next(a for a in menu.actions() if a.text().startswith("Paste")).isEnabled(), "nothing has been copied"
    got = []
    bare.remove_requested.connect(got.append); bare.move_requested.connect(got.append); bare.delete_requested.connect(got.append)
    for a in menu.actions():
        if a.text().startswith(("Remove", "Move", "Delete")): a.trigger()
    assert [names(g) for g in got] == [["d.png", "e.png", "f.png"]] * 3
    rated, flagged, pasted = [], [], []
    bare.rate_requested.connect(lambda ps, s: rated.append((names(ps), s)))
    bare.flag_requested.connect(lambda ps, f: flagged.append((names(ps), f)))
    bare.paste_requested.connect(pasted.append)
    next(a for a in menu.actions() if a.text().startswith("Rate")).menu().actions()[4].trigger()
    next(a for a in menu.actions() if a.text().startswith("Flag")).menu().actions()[1].trigger()
    assert rated == [(["d.png", "e.png", "f.png"], 5)] and flagged == [(["d.png", "e.png", "f.png"], "rejected")]
    bare.set_paste_filter(lambda: True)   # a look has been copied: the menu offers the paste to the selection
    paste = next(a for a in bare.build_selection_menu(chosen).actions() if a.text().startswith("Paste"))
    assert paste.isEnabled(); paste.trigger(); assert [names(p) for p in pasted] == [["d.png", "e.png", "f.png"]]
    # the window wires them: rating from the menu rates every photo
    fs.rate_requested.emit(chosen, 4); pump(0.3)
    assert E.get_ratings(db, chosen) == {p: 4 for p in chosen}
    fs.rate_requested.emit(chosen, 0); pump(0.3)

    # Ctrl+A selects the strip; a plain click goes back to one photo (and opens it)
    fs.select_all_visible(); assert len(fs.selected_paths()) == 6
    click(3); assert opened() == "d.png" and names(fs.selected_paths()) == ["d.png"] and win.strip_selection() == []
    # one photo selected: the keys act on the open photo as they always did
    win.run_photo_action("rating_2"); pump(0.3)
    assert E.get_ratings(db, [paths[3]]) == {paths[3]: 2}

    # a single selected photo's right-click menu is the ordinary one, and right-clicking another photo selects just it
    assert "Retake" not in " ".join(a.text() for a in fs.build_context_menu(paths[0]).actions())

    # the Workbench grid takes Shift and Ctrl-clicks too
    win.set_view("lighttable"); pump(1.5)
    grid = win._lighttable._list
    def gc(i): return grid.visualRect(grid.model().index(i, 0)).center()
    QTest.mouseClick(grid.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, gc(1)); pump(0.3)
    QTest.mouseClick(grid.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, gc(4)); pump(0.3)
    assert names(win._lighttable.selected_paths()) == ["b.png", "c.png", "d.png", "e.png"]
    QTest.mouseClick(grid.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, gc(5)); pump(0.3)
    assert names(win._lighttable.selected_paths()) == ["b.png", "c.png", "d.png", "e.png", "f.png"]
    win.close()
    print("OK")
""")


def test_selecting_several_photos_in_the_filmstrip_and_the_workbench():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC, "PHOTOEDITOR_GPU": "off"})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-3500:]
