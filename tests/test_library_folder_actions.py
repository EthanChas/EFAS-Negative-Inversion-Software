"""The Library lists' folder commands in the window: New Folder, Rename Folder, Delete Folder (to a stand-in Recycle Bin: nothing real is deleted), and Remove from Library on a folder
that is not a root, with Bring Back Removed Folders. Everything that remembers a folder must follow it."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r'''
    import os, shutil, sys, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    data = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_DATA_DIR"] = data
    work = tempfile.mkdtemp()
    bin_dir = os.path.join(work, "bin"); os.makedirs(bin_dir)
    lib = os.path.join(work, "Lib")
    import numpy as np, cv2
    from PyQt6.QtCore import QPointF
    from PyQt6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox, QMenu
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    for rel in ("RollA/a.png", "RollA/b.png", "RollA/sub/c.png", "RollB/d.png"):
        p = os.path.join(lib, *rel.split("/")); os.makedirs(os.path.dirname(p), exist_ok=True)
        cv2.imwrite(p, np.full((40, 60, 3), 90, np.uint8))
    rollA, rollB = os.path.join(lib, "RollA"), os.path.join(lib, "RollB")
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view import library_folder_actions as lfa
    from photoeditor.desktop.settings_store import qsettings
    from photoeditor.desktop.view.folder_tree import ROOTS_SETTINGS_KEY, HIDDEN_SETTINGS_KEY
    from photoeditor.features.library import folders as folder_ops
    from photoeditor.features.library.index import LibraryIndex
    from photoeditor.features.persistence import edit_store
    from photoeditor.features import session as session_store

    # a stand-in Recycle Bin and stand-in dialogs
    trashed = []
    def fake_trash(path):
        trashed.append(path); shutil.move(path, os.path.join(bin_dir, os.path.basename(path)))
    folder_ops.send_to_trash = fake_trash
    asked = {"name": "", "ok": True}
    QInputDialog.getText = staticmethod(lambda *a, **k: (asked["name"], asked["ok"]))
    warnings = []
    QMessageBox.warning = staticmethod(lambda parent, title, text, *a, **k: warnings.append((title, text)))
    answer = {"remove": True}
    def fake_box(self):
        self.buttons()[0 if answer["remove"] else 1].click()
    QMessageBox.exec = fake_box
    confirm = {"yes": True, "seen": []}
    lfa.confirm_delete_folder = lambda folder, summary, hot, parent=None: (confirm["seen"].append((folder, summary.photos, hot)), confirm["yes"])[1]

    win = aw.AppWindow(); c = win.controller
    refreshes = []
    win.lighttable_refresh = lambda force=False: refreshes.append(force)
    lp, wp = win._library_panel, win._lighttable.library_panel
    qsettings().setValue(ROOTS_SETTINGS_KEY, [lib]); qsettings().sync()
    lp.reload_roots(); wp.reload_roots()
    index = LibraryIndex(); index.refresh([lib]); assert len(index.all()) == 4; index.close()

    norm = os.path.normcase
    def names_in(panel, folder):
        """The names of the folders shown inside `folder` in a panel's tree (opening it)."""
        tree = panel._tree
        assert tree.reveal(folder), folder
        item = tree.currentItem(); tree.expandItem(item)
        return sorted(item.child(i).text(0) for i in range(item.childCount()) if item.child(i).data(0, 0x100) != "__loading__")
    def open_names(panel):
        return sorted(os.path.basename(f) for f in panel._tree.expanded_folders())
    def have(path, panel=lp):
        tree = panel._tree
        return tree.reveal(path)

    # something the folders must keep: ratings, tags, a hotstack mark, a recent folder, an open photo
    a, b, csub, d = (os.path.join(rollA, "a.png"), os.path.join(rollA, "b.png"), os.path.join(rollA, "sub", "c.png"), os.path.join(rollB, "d.png"))
    for p in (a, b, csub, d):
        edit_store.set_rating(c._db, p, 4); edit_store.add_tags(c._db, [p], ["keeper"])
    S.save({"hotstack_folders": [os.path.join(rollA, "sub")]}); win._apply_hotstack()
    win._session["recent_folders"] = [rollA, rollB]; win._session["last_by_folder"] = {rollA: a}
    win.open_folder(rollA, prefer=a)
    assert norm(c.state.image_path) == norm(a)

    # --- the menu of a folder inside a root: the new commands, in order
    menus = []
    def fake_exec(self, *args):
        menus.append([(x.text(), x.isEnabled()) for x in self.actions() if not x.isSeparator()])
    QMenu.exec = fake_exec
    tree = lp._tree
    assert have(rollA); lp._tree.expandItem(lp._tree.topLevelItem(0))
    item = tree.currentItem(); menu = tree.build_context_menu(item)
    texts = [x.text() for x in menu.actions() if not x.isSeparator()]
    assert texts == ["Mark as Hotstack", "New Folder...", "Rename Folder...", "Move Folder to...", "Show in File Explorer", "Remove from Library", "Delete Folder..."], texts
    assert tree.build_context_menu(None) is None, "nothing to bring back yet"

    # --- New Folder
    asked.update(name="Scans 2024", ok=True)
    tree.new_folder_requested.emit(rollB)
    made = os.path.join(rollB, "Scans 2024")
    assert os.path.isdir(made) and not warnings
    assert names_in(lp, rollB) == ["Scans 2024"] and names_in(wp, rollB) == ["Scans 2024"], "both lists show it"
    asked.update(name="a/b", ok=True)
    tree.new_folder_requested.emit(rollB)
    assert warnings and "/" in warnings[-1][1] and os.listdir(rollB).count("a") == 0 and sorted(os.listdir(rollB)) == ["Scans 2024", "d.png"], warnings
    asked.update(name="Scans 2024", ok=True); n = len(warnings)
    tree.new_folder_requested.emit(rollB)
    assert len(warnings) == n + 1 and "already" in warnings[-1][1]
    asked.update(name="Never", ok=False); before = sorted(os.listdir(rollB))
    tree.new_folder_requested.emit(rollB)
    assert sorted(os.listdir(rollB)) == before, "Cancel makes nothing"

    # --- Rename Folder: the folder, its photos' edits, the index, the settings, the lists - and the open photo
    assert norm(c.state.image_path) == norm(a)
    asked.update(name="RollB", ok=True); n = len(warnings)
    tree.rename_folder_requested.emit(rollA)
    assert len(warnings) == n + 1 and "already" in warnings[-1][1] and os.path.isdir(rollA), "never over another folder"
    asked.update(name="Fuji 400", ok=True)
    fuji = os.path.join(lib, "Fuji 400")
    names_in(lp, rollA)   # opens it
    edit_store.set_folder_roll(c._db, edit_store.folder_key(rollA, False), {"film": "Fuji"})
    tree.rename_folder_requested.emit(rollA)
    assert os.path.isdir(fuji) and not os.path.exists(rollA), "renamed on disk"
    fa, fb, fc = (os.path.join(fuji, "a.png"), os.path.join(fuji, "b.png"), os.path.join(fuji, "sub", "c.png"))
    for p in (fa, fb, fc):
        assert edit_store.get_rating(c._db, p) == 4 and edit_store.get_tags(c._db, [p])[p] == ["keeper"], p
    assert edit_store.get_rating(c._db, a) == 0, "nothing left under the old name"
    assert edit_store.get_folder_roll(c._db, edit_store.folder_key(fuji, False)) == {"film": "Fuji"}
    index = LibraryIndex(); paths = sorted(r["path"] for r in index.all()); index.close()
    assert paths == sorted([fa, fb, fc, d]), paths
    assert [norm(f) for f in win.hotstack_folders()] == [norm(os.path.join(fuji, "sub"))], "the hotstack mark follows"
    assert [norm(f) for f in win._session["recent_folders"]] == [norm(fuji), norm(rollB)] and norm(win._session["last_by_folder"][fuji]) == norm(fa)
    assert norm(win._filmstrip_folder) == norm(fuji) and [norm(p) for p in win._filmstrip.paths()] == [norm(fa), norm(fb)]
    assert norm(c.state.image_path) == norm(fa), "the photo that was open is open at its new place"
    assert norm(fuji) in [norm(x) for x in lp._tree.expanded_folders()], "the folder that was open is still open, under its new name"
    for panel in (lp, wp):
        assert names_in(panel, lib) == ["Fuji 400", "RollB"], names_in(panel, lib)
    assert "Fuji 400" in win._coord_label.text()
    # a root can be renamed too: the saved list follows
    asked.update(name="Archive", ok=True)
    archive = os.path.join(work, "Archive")
    tree.rename_folder_requested.emit(lib)
    assert os.path.isdir(archive) and not os.path.exists(lib)
    saved = qsettings().value(ROOTS_SETTINGS_KEY, [], type=list)
    assert [norm(x) for x in saved] == [norm(archive)] and [norm(x) for x in lp.roots()] == [norm(archive)] and [norm(x) for x in wp.roots()] == [norm(archive)]
    lib, fuji, rollB, d = archive, os.path.join(archive, "Fuji 400"), os.path.join(archive, "RollB"), os.path.join(archive, "RollB", "d.png")
    fa = os.path.join(fuji, "a.png"); fc = os.path.join(fuji, "sub", "c.png")
    assert edit_store.get_rating(c._db, d) == 4 and edit_store.get_rating(c._db, fa) == 4 and norm(c.state.image_path) == norm(fa)

    # --- Remove from Library on a folder that is not a root, and Bring Back Removed Folders
    sub = os.path.join(fuji, "sub")
    answer["remove"] = False
    tree.hide_folder_requested.emit(sub)
    assert qsettings().value(HIDDEN_SETTINGS_KEY, [], type=list) == [], "Cancel keeps it"
    answer["remove"] = True
    tree.hide_folder_requested.emit(sub)
    hidden = qsettings().value(HIDDEN_SETTINGS_KEY, [], type=list)
    assert [norm(x) for x in hidden] == [norm(sub)], hidden
    assert os.path.isfile(fc), "the files stay"
    for panel in (lp, wp):
        assert names_in(panel, fuji) == [], "gone from both lists"
    index = LibraryIndex(); left = sorted(r["path"] for r in index.all()); index.close()
    assert fc not in left and fa in left, left
    assert win.hotstack_folders() == [], "a hotstack mark inside it goes"
    assert edit_store.get_rating(c._db, fc) == 4, "its edits stay"
    index = LibraryIndex(); res = index.refresh([lib], excluded=lp.hidden_folders()); left = [r["path"] for r in index.all()]; index.close()
    assert fc not in left and res[0] == 0, "the next scan leaves it out"
    assert win.lighttable_roots()
    # the way back: the item menu and the empty-space menu both offer it
    have(fuji); item = lp._tree.currentItem()
    texts = [x.text() for x in lp._tree.build_context_menu(item).actions() if not x.isSeparator()]
    assert texts[-1] == "Bring Back Removed Folders (1)", texts
    assert [x.text() for x in lp._tree.build_context_menu(None).actions()] == ["Bring Back Removed Folders (1)"]
    lp._tree.restore_hidden_requested.emit()
    assert qsettings().value(HIDDEN_SETTINGS_KEY, [], type=list) == [] and refreshes, "the Workbench reads the folder again"
    for panel in (lp, wp):
        assert names_in(panel, fuji) == ["sub"], "back in both lists"
    index = LibraryIndex(); index.refresh([lib]); assert fc in [r["path"] for r in index.all()]; index.close()

    # --- Move Folder: from the menu (a folder picker) and by a drop; Move to Folder for photos
    picked = {"dir": ""}
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: picked["dir"])
    texts = [x.text() for x in lp._tree.build_context_menu(lp._tree.topLevelItem(0)).actions() if not x.isSeparator()]
    assert "Move Folder to..." in texts and texts.index("Move Folder to...") == texts.index("Rename Folder...") + 1, texts
    picked["dir"] = fuji
    tree.move_folder_requested.emit(rollB, "")
    moved_b = os.path.join(fuji, "RollB")
    assert os.path.isdir(moved_b) and not os.path.exists(rollB) and os.path.isfile(os.path.join(moved_b, "d.png"))
    assert edit_store.get_rating(c._db, os.path.join(moved_b, "d.png")) == 4 and edit_store.get_rating(c._db, d) == 0, "the edits went with it"
    index = LibraryIndex(); paths = sorted(r["path"] for r in index.all()); index.close()
    assert os.path.join(moved_b, "d.png") in paths and d not in paths, paths
    for panel in (lp, wp):
        assert names_in(panel, fuji) == ["RollB", "sub"], names_in(panel, fuji)
    assert "Moved" in win._coord_label.text() and "RollB" in win._coord_label.text()
    n = len(warnings)
    tree.move_folder_requested.emit(fuji, moved_b)
    assert len(warnings) == n + 1 and "itself" in warnings[-1][1], "not into itself"
    tree.move_folder_requested.emit(moved_b, fuji)
    assert "already" in warnings[-1][1], "not where it is already"
    os.makedirs(os.path.join(lib, "RollB"))
    tree.move_folder_requested.emit(moved_b, lib)
    assert "already" in warnings[-1][1] and os.path.isdir(moved_b), "never over another folder"
    os.rmdir(os.path.join(lib, "RollB"))
    # a drop: the dragged row is the current one, the row under the cursor is where it goes (asked first)
    class Drop:
        def __init__(self, point): self.point, self.ignored = point, False
        def position(self): return QPointF(self.point)
        def ignore(self): self.ignored = True
    tree.reveal(moved_b); tree.reveal(lib)
    tree.setCurrentItem(tree.currentItem())
    assert tree.reveal(moved_b)
    root_item = tree.topLevelItem(0)
    answer["remove"] = False
    event = Drop(tree.visualItemRect(root_item).center())
    tree.dropEvent(event)
    assert event.ignored and os.path.isdir(moved_b), "Cancel keeps it where it is"
    answer["remove"] = True
    tree.reveal(moved_b)
    event = Drop(tree.visualItemRect(root_item).center())
    tree.dropEvent(event)
    assert event.ignored and os.path.isdir(os.path.join(lib, "RollB")) and not os.path.exists(moved_b), "a drop moves the folder into the one it landed on"
    assert edit_store.get_rating(c._db, os.path.join(lib, "RollB", "d.png")) == 4
    root_item = tree.topLevelItem(0); tree.setCurrentItem(root_item)   # the list was rebuilt
    event = Drop(tree.visualItemRect(root_item).center())
    n = len(warnings); tree.dropEvent(event)   # the root onto itself: nothing
    assert len(warnings) == n and os.path.isdir(lib)
    # photos: into a folder, a taken name is never overwritten, the open photo is reopened
    rollB = os.path.join(lib, "RollB"); d = os.path.join(rollB, "d.png")
    cv2.imwrite(os.path.join(fuji, "d.png"), np.full((40, 60, 3), 200, np.uint8))
    picked["dir"] = fuji
    win._folder_actions.move_photos([d])
    assert os.path.isfile(os.path.join(fuji, "d.png")) and os.path.isfile(os.path.join(fuji, "d_1.png")) and not os.path.exists(d), "the photo that was there is kept"
    assert edit_store.get_rating(c._db, os.path.join(fuji, "d_1.png")) == 4 and edit_store.get_rating(c._db, d) == 0
    index = LibraryIndex(); paths = [r["path"] for r in index.all()]; index.close()
    assert os.path.join(fuji, "d_1.png") in paths and d not in paths
    assert "Moved 1 photo" in win._coord_label.text()
    picked["dir"] = rollB
    win._folder_actions.move_photos([fa])   # the photo that is open
    new_fa = os.path.join(rollB, "a.png")
    assert os.path.isfile(new_fa) and not os.path.exists(fa) and norm(c.state.image_path) == norm(new_fa), c.state.image_path
    assert edit_store.get_rating(c._db, new_fa) == 4
    picked["dir"] = fuji
    win._folder_actions.move_photos([new_fa, os.path.join(rollB, "gone.png")])   # a file that is not there is left out
    assert os.path.isfile(fa) and norm(c.state.image_path) == norm(fa) and edit_store.get_rating(c._db, fa) == 4
    picked["dir"] = fuji; win._folder_actions.move_photos([fa]); assert "already" in win._coord_label.text(), "in that folder already"
    picked["dir"] = ""; win._folder_actions.move_photos([fa]); assert os.path.isfile(fa), "Cancel moves nothing"
    # the buttons and menus offer it
    assert win._lighttable._move_btn.text() == "Move to Folder..." and not win._lighttable._move_btn.isEnabled()
    assert "Move a.png to Folder..." in [x.text() for x in win._filmstrip.build_context_menu(fa).actions()]
    rollB = os.path.join(lib, "RollB")

    # --- Delete Folder: a photo that is open stops it; Cancel keeps it; data folder is protected
    n = len(warnings)
    tree.delete_folder_requested.emit(fuji)
    assert len(warnings) == n + 1 and "open in the editor" in warnings[-1][1] and os.path.isdir(fuji) and not confirm["seen"], "asked nothing, deleted nothing"
    tree.delete_folder_requested.emit(data)
    assert "own data" in warnings[-1][1] and os.path.isdir(data)
    cv2.imwrite(os.path.join(rollB, "e.png"), np.full((40, 60, 3), 60, np.uint8)); edit_store.set_rating(c._db, os.path.join(rollB, "e.png"), 2)
    index = LibraryIndex(); index.refresh([lib]); index.close()
    confirm["yes"] = False
    tree.delete_folder_requested.emit(rollB)
    assert confirm["seen"] == [(rollB, 1, False)] and os.path.isfile(os.path.join(rollB, "e.png")) and not trashed, confirm["seen"]
    confirm["yes"] = True
    tree.delete_folder_requested.emit(rollB)
    assert trashed == [rollB] and not os.path.exists(rollB) and os.path.isfile(os.path.join(bin_dir, "RollB", "e.png")), "to the (stand-in) Recycle Bin"
    index = LibraryIndex(); left = sorted(r["path"] for r in index.all()); index.close()
    assert os.path.join(rollB, "e.png") not in left and fa in left
    assert edit_store.get_rating(c._db, os.path.join(rollB, "e.png")) == 2, "the edits are kept, so a restored photo keeps its look"
    for panel in (lp, wp):
        assert names_in(panel, lib) == ["Fuji 400"], names_in(panel, lib)
    assert "RollB" in win._coord_label.text() and "Recycle Bin" in win._coord_label.text()
    assert [norm(f) for f in win._session["recent_folders"]] == [norm(fuji)]
    # a folder that is a root and is deleted leaves the list
    other_root = os.path.join(work, "Other"); os.makedirs(other_root); cv2.imwrite(os.path.join(other_root, "z.png"), np.full((10, 10, 3), 5, np.uint8))
    lp._tree.add_root(other_root); qsettings().setValue(ROOTS_SETTINGS_KEY, lp._tree.roots()); qsettings().sync(); wp.reload_roots()
    tree.delete_folder_requested.emit(other_root)
    assert not os.path.exists(other_root) and [norm(x) for x in lp.roots()] == [norm(lib)] and [norm(x) for x in wp.roots()] == [norm(lib)]
    assert [norm(x) for x in qsettings().value(ROOTS_SETTINGS_KEY, [], type=list)] == [norm(lib)]
    # a Recycle Bin that cannot be used: nothing is deleted
    def no_bin(path): raise folder_ops.TrashUnavailable("There is no Recycle Bin here.")
    folder_ops.send_to_trash = no_bin
    keep = os.path.join(lib, "Keep"); os.makedirs(keep)
    lp.rebuild(); n = len(warnings)
    tree.delete_folder_requested.emit(keep)
    assert os.path.isdir(keep) and "no Recycle Bin" in warnings[-1][1], warnings[-1]
    assert len(warnings) == n + 1

    # --- a folder that was taken off the list and is then added again on purpose is not hidden any more
    tree.hide_folder_requested.emit(sub)
    assert [norm(x) for x in lp.hidden_folders()] == [norm(sub)]
    picked["dir"] = sub
    lp._add_root_folder()
    assert lp.hidden_folders() == [] and any(norm(r) == norm(sub) for r in lp.roots()) and any(norm(r) == norm(sub) for r in wp.roots())

    # --- the confirmation is explicit and defaults to keeping the folder
    from photoeditor.desktop.view.removal_dialogs import DeleteFolderDialog
    dlg = DeleteFolderDialog(fuji, folder_ops.summarise(fuji), True)
    assert "Fuji 400" in dlg.heading.text() and "Recycle Bin" in dlg.warning.text() and "hotstack" in dlg.notes.text()
    assert "Photos in it:" in dlg.details.text() and "Folders in it: 1" in dlg.details.text()
    assert not dlg.delete_button.isEnabled() and dlg.cancel_button.isDefault() and not dlg.delete_button.isDefault()
    dlg.confirm_box.setChecked(True); assert dlg.delete_button.isEnabled()
    dlg.confirm_box.setChecked(False); assert not dlg.delete_button.isEnabled()

    # --- the Import window's list has none of this
    from photoeditor.desktop.view.import_window import ImportWindow
    iw = ImportWindow(win)
    if iw._tree.topLevelItemCount():
        m = iw._tree.build_context_menu(iw._tree.topLevelItem(0))
        assert not [x.text() for x in m.actions() if "Folder" in x.text() or "Remove" in x.text()]
    print("OK")
''')


def test_library_folder_commands_in_the_window():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0 and "OK" in done.stdout, (done.stdout[-1500:], done.stderr[-3000:])
