"""Preset folders: folders made on purpose (they stay when empty), nested folders, removing a folder and keeping what is in it, moving and dragging presets and folders,
duplicating, and the order inside folders - the logic, the store, and the Presets panel in the window."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from photoeditor.features.presettree import logic as t

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_folders_made_on_purpose_are_in_the_tree_even_when_empty():
    names = ["Film/B&W/Soft", "Top"]
    nodes = t.build(names, ["Film/Colour", "Empty/Inner", "film/b&w"])
    shape = []

    def walk(items, depth=0):
        for n in items:
            shape.append("  " * depth + n.label + ("/" if n.is_folder else ""))
            walk(n.children, depth + 1)

    walk(nodes)
    assert shape == ["Empty/", "  Inner/", "Film/", "  B&W/", "    Soft", "  Colour/", "Top"], shape
    assert t.folder_paths(names, ["Film/Colour", "Empty/Inner"]) == ["Empty", "Empty/Inner", "Film", "Film/B&W", "Film/Colour"], "every folder, with the ones above it"
    assert t.flatten(t.build(names)) == ["Film/B&W/Soft", "Top"], "no folders given: as before"


def test_the_order_inside_folders():
    names = ["Zed", "alpha", "Mid", "B/y", "B/Z", "A/q"]
    assert t.flatten(t.build(names)) == ["A/q", "B/y", "B/Z", "Zed", "alpha", "Mid"], "made: folders A to Z, presets as they were made"
    assert t.flatten(t.build(names, sort="az")) == ["A/q", "B/y", "B/Z", "alpha", "Mid", "Zed"]
    assert t.flatten(t.build(names, sort="za")) == ["B/Z", "B/y", "A/q", "Zed", "Mid", "alpha"], "Z to A turns folders round too"
    assert t.SORTS == ("made", "az", "za")


def test_removing_a_folder_keeps_what_is_in_it_and_never_replaces_a_preset():
    names = ["Film/B&W/Soft", "Film/B&W/Hard", "Film/Colour/Warm", "Film/Top", "Top"]
    moves, folder_moves = t.dissolve(names, "Film", ["Film/Spare", "Elsewhere"])
    assert moves == {"Film/B&W/Soft": "B&W/Soft", "Film/B&W/Hard": "B&W/Hard", "Film/Colour/Warm": "Colour/Warm", "Film/Top": "Top copy"}, "everything moves up one level; a name that is taken gets copy"
    assert folder_moves == {"Film/Spare": "Spare"}, "the folders made on purpose inside move up too, and the others are left alone"
    moves, _ = t.dissolve(names, "Film/B&W")
    assert moves == {"Film/B&W/Soft": "Film/Soft", "Film/B&W/Hard": "Film/Hard"}, "into the folder above, not the top"
    moves, _ = t.dissolve(["A/x", "A/B/x", "x"], "A")
    assert moves == {"A/x": "x copy", "A/B/x": "B/x"} and len(set(moves.values())) == 2
    assert t.dissolve(["A/x"], "Nothing")[0] == {}


def test_helpers_for_moving_and_copying():
    assert t.move_into("Film/B&W/Soft", "Colour") == "Colour/Soft" and t.move_into("Film/Soft", "") == "Soft"
    assert t.is_inside("Film/B&W", "film") and t.is_inside("Film", "Film") and not t.is_inside("Filmore", "Film") and not t.is_inside("A", "")
    assert t.unique_name("X", set()) == "X" and t.unique_name("X", {"x"}) == "X copy" and t.unique_name("X", {"x", "x copy"}) == "X copy 2"
    assert t.empty_folders(["A/x"], ["A", "B", "B/C"]) == ["B", "B/C"], "a folder with a preset beneath it is not empty"
    assert t.empty_folders([], []) == []


def test_the_store_keeps_folders_made_on_purpose(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    from photoeditor.features.lookpresets import store

    assert store.folders() == [] and store.add_folder("  Film /  B&W ") == "Film/B&W"
    assert store.folders() == ["Film/B&W"] and store.add_folder("film/b&w") is None, "there is already one, whatever the case"
    assert store.add_folder("") is None and store.add_folder("/ /") is None
    store.save_preset("Film/Soft", {"contrast": 0.1})
    assert store.add_folder("Film") is None, "a folder a preset name runs through exists already"
    assert store.folders() == ["Film/B&W"], "saving a preset leaves the folders alone"
    store.replace_preset("Film/Soft", "Film/Softer", {"contrast": 0.2}); store.delete_preset("Film/Softer")
    assert store.folders() == ["Film/B&W"] and store.names() == []
    store.add_folder("Other")
    store.rename_folder_records("Film", "Movies")
    assert store.folders() == ["Movies/B&W", "Other"]
    store.remove_folder_records("Movies")
    assert store.folders() == ["Other"]
    store.add_folder("Used"); store.save_preset("Used/x", {"a": 1})
    assert store.forget_empty_folders() == 1 and store.folders() == ["Used"], "only the empty one goes"
    (tmp_path / "look-presets.json").write_text('{"presets": [{"name": "A/x", "look": {}}]}', encoding="utf-8")
    assert store.folders() == [] and store.names() == ["A/x"], "a file from before folders were kept still loads"
    (tmp_path / "look-presets.json").write_text('{"presets": [], "folders": ["A", 5, "a", ""]}', encoding="utf-8")
    assert store.folders() == ["A"]


_SCRIPT = textwrap.dedent(r'''
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_GPU"] = "off"; os.environ["PHOTOEDITOR_AUDIO"] = "off"
    from PyQt6.QtCore import QPoint, QPointF
    from PyQt6.QtWidgets import QApplication, QInputDialog, QMenu, QMessageBox
    app = QApplication([])
    from photoeditor.features.lookpresets import store
    from photoeditor.features.presettree import logic as t
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 1000); win.show()
    def pump(s):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(1.0)
    c, panel = win.controller, win._presets_panel
    panel.set_expanded(True); pump(0.5)
    tree = panel._tree
    notes = []; c.notice.connect(notes.append)
    asked = {"text": [], "item": [], "yes": True}; info = []
    QInputDialog.getText = staticmethod(lambda parent, title, prompt, **kw: (asked["text"].pop(0), True))
    QInputDialog.getItem = staticmethod(lambda parent, title, label, items, current=0, editable=True: (asked["item"].pop(0), True))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes if asked["yes"] else QMessageBox.StandardButton.No)
    QMessageBox.information = staticmethod(lambda *a, **k: info.append(a[2]))
    menus = []
    QMenu.exec = lambda self, *a: menus.append([x.text() for x in self.actions() if x.text()])
    def shape():
        out = []
        def walk(item, depth):
            out.append(("  " * depth) + item.text(0))
            for i in range(item.childCount()): walk(item.child(i), depth + 1)
        for i in range(tree.topLevelItemCount()): walk(tree.topLevelItem(i), 0)
        return out
    def row(path):
        found = []
        def walk(item):
            if item.data(0, 256 + 1) == path or item.data(0, 256) == path: found.append(item)
            for i in range(item.childCount()): walk(item.child(i))
        for i in range(tree.topLevelItemCount()): walk(tree.topLevelItem(i))
        return found[0]
    def refresh(): c.look_presets_changed.emit(""); tree.expandAll(); app.processEvents()
    class Drop:
        def __init__(self, point): self.point = point
        def position(self): return QPointF(self.point)
        def ignore(self): pass
    def drop(source_row, target_row=None):
        tree.setCurrentItem(source_row)
        if target_row is not None:   # the list is a few rows tall: bring the target into view, then drop on it
            tree.scrollToItem(target_row); app.processEvents()
        point = tree.visualItemRect(target_row).center() if target_row is not None else QPoint(-5, -5)   # outside every row: empty space
        assert target_row is None or tree.itemAt(point) is target_row
        tree.dropEvent(Drop(point)); tree.expandAll(); app.processEvents()

    assert shape() == ["No presets yet."] and store.folders() == []

    # a new folder, and one inside it: they stay while empty
    asked["text"] = ["Film"]; panel._new_folder(""); tree.expandAll()
    assert store.folders() == ["Film"] and shape() == ["Film"] and "Made the folder 'Film'" in notes[-1]
    tree.setCurrentItem(row("Film")); asked["text"] = ["Film/B&W"]; panel._new_folder("Film")
    assert store.folders() == ["Film", "Film/B&W"] and shape() == ["Film", "  B&W"], shape()
    asked["text"] = ["film/b&w"]; panel._new_folder("")
    assert info and "already a folder" in info[-1] and store.folders() == ["Film", "Film/B&W"], "a folder that exists is not made again"

    # presets go in them; the Organise menu knows what is selected
    for name in ("Film/B&W/Soft", "Film/B&W/Hard", "Top"):
        store.save_preset(name, {"contrast": 0.1})
    refresh()
    assert shape() == ["Film", "  B&W", "    Soft", "    Hard", "Top"], shape()
    tree.setCurrentItem(row("Film/B&W")); panel._fill_organise_menu()
    organise = {a.text(): a.isEnabled() for a in panel._organise_menu.actions() if a.text()}
    assert organise["New Folder..."] and organise["New Subfolder in the Selected Folder..."] and organise["Remove Folder, Keep Its Presets..."] and organise["Delete Folder and Its Presets..."]
    assert organise["Move Selected to..."] and not organise["Duplicate Selected"] and not organise["Remove Empty Folders"] and organise["Open All Folders"]
    tree.setCurrentItem(row("Top")); panel._fill_organise_menu()
    organise = {a.text(): a.isEnabled() for a in panel._organise_menu.actions() if a.text()}
    assert organise["Duplicate Selected"] and not organise["New Subfolder in the Selected Folder..."] and not organise["Remove Folder, Keep Its Presets..."]

    # move: the Move to... list
    tree.setCurrentItem(row("Top")); asked["item"] = [t.display("Film/B&W")]; panel._move_selected()
    assert "Film/B&W/Top" in store.names() and "Top" not in store.names() and "Moved the preset" in notes[-1]
    # drag and drop: onto empty space (the top level), onto a folder, onto a preset (its folder)
    drop(row("Film/B&W/Top"))
    assert "Top" in store.names() and "Film/B&W/Top" not in store.names(), "dropped on empty space: the top level"
    drop(row("Top"), row("Film"))
    assert "Film/Top" in store.names(), "dropped on a folder"
    drop(row("Film/Top"), row("Film/B&W/Soft"))
    assert "Film/B&W/Top" in store.names(), "dropped on a preset: the folder it is in"
    drop(row("Film/B&W/Top"), row("Film"))
    assert "Film/Top" in store.names()
    store.save_preset("Top", {"contrast": 0.3}); refresh()
    drop(row("Top"), row("Film"))
    assert "Top" in store.names() and "already a preset" in notes[-1], "a drop never replaces a preset that is there"
    # a folder dropped on another folder, and never on itself or what is inside it
    asked["text"] = ["Side"]; panel._new_folder(""); store.save_preset("Side/s", {"a": 1}); refresh()
    drop(row("Side"), row("Film"))
    assert "Film/Side/s" in store.names() and "Side/s" not in store.names()
    before = list(store.names()); drop(row("Film"), row("Film/Side")); assert store.names() == before and "into itself" not in "".join(info), "a folder is not put inside itself"
    drop(row("Film/Side"))
    assert "Side/s" in store.names(), "a folder dropped on empty space goes to the top level"

    # remove a folder but keep its presets (they move up; a name that is taken gets copy), and remove one with nothing in it
    store.save_preset("Film/B&W/Top", {"contrast": 0.5}); refresh()
    asked["yes"] = False; panel._remove_folder("Film/B&W")
    assert "Film/B&W/Soft" in store.names(), "answering No removes nothing"
    asked["yes"] = True; panel._remove_folder("Film/B&W")
    names = store.names()
    assert {"Film/Soft", "Film/Hard", "Film/Top copy", "Film/Top"} <= set(names) and not any(n.startswith("Film/B&W") for n in names), names
    assert "Film/B&W" not in store.folders() and "moved up into Film" in notes[-1] and "Removed the folder 'Film/B&W'" in notes[-1]
    asked["text"] = ["Empty/Inner"]; panel._new_folder(""); refresh()
    asked["yes"] = False; panel._delete_folder("Empty/Inner")
    assert "Empty/Inner" not in store.folders(), "an empty folder is deleted without asking"
    asked["text"] = ["Gone"]; panel._new_folder(""); asked["yes"] = False; panel._remove_folder("Gone")
    assert "Gone" not in store.folders(), "and so is removing one with nothing in it"

    # delete a folder with presets: asks, and takes the folder with it
    asked["yes"] = False; panel._delete_folder("Film"); assert "Film/Soft" in store.names()
    asked["yes"] = True; panel._delete_folder("Film")
    assert not any(n.startswith("Film/") for n in store.names()) and "Film" not in [f.split("/")[0] for f in store.folders()]
    assert "Top" in store.names() and "Side/s" in store.names()

    # empty folders, in the Organise menu
    asked["text"] = ["Spare/One"]; panel._new_folder(""); asked["text"] = ["Spare/Two"]; panel._new_folder(""); asked["text"] = ["Used"]; panel._new_folder(""); store.save_preset("Used/u", {"a": 1}); refresh()
    panel._fill_organise_menu()
    labels = [a.text() for a in panel._organise_menu.actions()]
    assert "Remove Empty Folders (2)" in labels, labels
    next(a for a in panel._organise_menu.actions() if a.text() == "Remove Empty Folders (2)").trigger()
    assert sorted(store.folders()) == ["Side", "Used"], store.folders()   # Side and Used have presets in them, so they stay; the two Spare folders were empty
    assert "Removed 2 empty folders" in notes[-1] and "Spare" not in "".join(shape())

    # rename an empty folder, move a folder through the controller, duplicate
    asked["text"] = ["Old/Inside"]; panel._new_folder(""); assert c.rename_look_folder("Old", "New") == 0 and "New/Inside" in store.folders() and "Old/Inside" not in store.folders()
    c.remove_empty_look_folders(); refresh()
    assert c.move_look_folder("Side", "Used") == 1 and "Used/Side/s" in store.names()
    assert c.move_look_folder("Used", "Used/Side") == 0 and "into itself" in notes[-1]
    tree.setCurrentItem(row("Used/u")); panel._duplicate()
    assert "Used/u copy" in store.names() and panel.selected() == "Used/u copy", "the copy is selected"
    tree.setCurrentItem(row("Used/u")); panel._duplicate()
    assert {"Used/u copy", "Used/u copy 2"} <= set(store.names()) and store.get("Used/u copy") == {"a": 1} and "Duplicated 'Used/u'" in notes[-1]

    # the order inside folders is kept in the settings
    for n in list(store.names()): store.delete_preset(n)
    store.set_folders([])
    for n in ("Zed", "alpha", "Mid", "F/b", "F/A"): store.save_preset(n, {"a": 1})
    refresh()
    assert shape() == ["F", "  b", "  A", "Zed", "alpha", "Mid"], shape()
    panel._fill_organise_menu()
    order = next(a for a in panel._organise_menu.actions() if a.text() == "Order Inside Folders").menu()
    assert [(a.text(), a.isChecked()) for a in order.actions()] == [("In the order made", True), ("A to Z", False), ("Z to A", False)]
    next(a for a in order.actions() if a.text() == "A to Z").trigger()
    assert shape() == ["F", "  A", "  b", "alpha", "Mid", "Zed"] and S.load()["preset_sort"] == "az" and panel.sort_mode() == "az"
    panel._choose_sort("za"); assert shape() == ["F", "  b", "  A", "Zed", "Mid", "alpha"] and S.load()["preset_sort"] == "za"
    panel._choose_sort("made"); assert shape() == ["F", "  b", "  A", "Zed", "alpha", "Mid"]
    S.save({"preset_sort": "sideways"}); assert S.load()["preset_sort"] in ("made", "az", "za"), "a setting that is not one of the three is ignored"

    # a search hides the empty folders and turns the drag off; clearing brings them back
    store.add_folder("Empty"); refresh()
    assert "Empty" in shape(); panel.search("zed"); assert shape() == ["Zed"] and not tree.dragEnabled()
    panel.search(""); assert "Empty" in shape() and tree.dragEnabled()

    # the right-click menus, including empty space, and the built-in list
    menus.clear()
    panel._context_menu("root", "", None); panel._context_menu("folder", "F", None); panel._context_menu("preset", "F/b", None)
    assert menus[0] == ["New Folder...", "Open All Folders", "Close All Folders"], menus[0]
    assert menus[1][1] == "New Subfolder..." and "Remove Folder, Keep Its Presets..." in menus[1] and "Move Folder to..." in menus[1]
    assert menus[2] == ["Apply", "Rename or Move...", "Move to...", "Duplicate", "Delete"]
    seen_root = []; tree.context_requested.connect(lambda kind, target, where: seen_root.append((kind, target)))
    tree._on_context(QPoint(-5, -5)); assert seen_root[-1] == ("root", "")
    panel.show_builtin(True); menus.clear()
    assert not tree.dragEnabled(), "the built-in list cannot be reorganised"
    panel._context_menu("folder", "Scanners (EFAS Original)", None); panel._context_menu("root", "", None)
    assert menus[0] == ["Open All Folders Below", "Copy Folder to My Presets"] and menus[1] == ["Open All Folders", "Close All Folders"], menus
    panel._fill_organise_menu(); texts = [a.text() for a in panel._organise_menu.actions() if a.text()]
    assert texts[0] == "Copy Folder to My Presets" and "New Folder..." not in texts and "Order Inside Folders" in texts

    # copy a built-in folder to My Presets, keeping the folders and never replacing anything
    for n in list(store.names()): store.delete_preset(n)
    refresh(); panel.copy_builtin_folder_requested.emit("Scanners (EFAS Original)"); pump(0.2)
    assert not panel.showing_builtin() and sorted(store.names()) == sorted(["Scanners (EFAS Original)/Frontier 100", "Scanners (EFAS Original)/Crystal 100", "Scanners (EFAS Original)/Pakon (Clean and Rich)", "Scanners (EFAS Original)/Noritsu (Green Shadows)"])
    assert "Copied 4 presets" in notes[-1]
    assert c.copy_builtin_folder("Scanners (EFAS Original)") == 4 and len(store.names()) == 8 and "Scanners (EFAS Original)/Frontier 100 copy" in store.names()
    print("OK")
''')


def test_the_presets_panel_organises_folders_in_the_window():
    out = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-3000:]
