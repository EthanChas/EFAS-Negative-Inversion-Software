"""Remove-from-Workbench and delete-from-disk through the Workbench buttons, the filmstrip menu, the File menu and the confirmation dialog. A stand-in Recycle Bin is used: nothing real is deleted."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    folder = os.path.join(work, "roll"); os.makedirs(folder)
    bin_dir = os.path.join(work, "bin"); os.makedirs(bin_dir)
    import numpy as np, cv2
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    from photoeditor.features.library import removal
    from photoeditor.features.library.index import LibraryIndex
    names = [f"img{i}.png" for i in range(5)]
    for i, n in enumerate(names):
        cv2.imwrite(os.path.join(folder, n), np.full((60, 90, 3), 40 * i + 20, np.uint8))
    open(os.path.join(folder, "img1.png.xmp"), "w").write("x")
    paths = [os.path.join(folder, n) for n in names]

    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view.removal_dialogs import DeleteConfirmDialog, RemovedPhotosDialog

    win = aw.AppWindow(); c = win.controller; lt = win._lighttable
    index = LibraryIndex(); index.refresh([folder]); index.close()
    win.open_folder(folder, prefer=paths[0])
    win._lighttable_reload_rows()
    def shown(): return sorted(os.path.basename(r["path"]) for r in lt._shown)
    assert shown() == names and win._filmstrip.paths() == paths

    def select(*idx):
        sel = lt._list.selectionModel(); sel.clearSelection()
        for i in idx:
            sel.select(lt._model.index(i), sel.SelectionFlag.Select)
        lt._on_selection()
    # nothing selected: the buttons are off
    select()
    assert not lt._remove_btn.isEnabled() and not lt._delete_btn.isEnabled()

    # --- remove from the Workbench: files stay, photos leave the grid and the filmstrip, and it survives a reload
    select(1, 2)
    assert lt._remove_btn.isEnabled() and lt._delete_btn.isEnabled()
    lt._remove_btn.click()
    assert shown() == [names[0], names[3], names[4]] and win._filmstrip.paths() == [paths[0], paths[3], paths[4]]
    assert all(os.path.exists(p) for p in paths)
    assert "Removed Photos (2)" in lt._removed_btn.text()
    win._lighttable_reload_rows(); assert len(shown()) == 3
    win._on_library_folder_selected(folder); assert win._filmstrip.paths() == [paths[0], paths[3], paths[4]]

    # --- restore from the list
    dlg = RemovedPhotosDialog(c.hidden_photos())
    assert dlg.list.count() == 2
    restored = []
    dlg.restore_requested.connect(restored.append)
    dlg.list.item(0).setSelected(True); dlg.restore_selected.click()
    assert len(restored) == 1 and len(restored[0]) == 1
    c.restore_photos(restored[0]); win._on_library_folder_selected(folder); win._lighttable_reload_rows()
    assert len(shown()) == 4 and len(c.hidden_photos()) == 1
    c.restore_photos(c.hidden_photos()); win._on_library_folder_selected(folder); win._lighttable_reload_rows()
    assert shown() == names and win._filmstrip.paths() == paths

    # --- the delete confirmation is explicit and defaults to keeping the photos
    d = DeleteConfirmDialog(paths[:3])
    assert "Delete 3 photos from your disk?" in d.heading.text() and "Recycle Bin" in d.warning.text()
    assert not d.delete_button.isEnabled() and d.cancel_button.isDefault() and not d.delete_button.isDefault()
    d.confirm_box.setChecked(True); assert d.delete_button.isEnabled()
    d.confirm_box.setChecked(False); assert not d.delete_button.isEnabled()
    one = DeleteConfirmDialog(paths[:1]); assert "Delete 1 photo from your disk?" in one.heading.text()
    many = DeleteConfirmDialog([os.path.join(folder, n) for n in names] * 1)
    assert many.names.count() == 5

    # --- declining the confirmation deletes nothing
    moved = []
    def fake_bin(p):
        moved.append(p); os.replace(p, os.path.join(bin_dir, f"{len(moved)}_" + os.path.basename(p)))
    removal.send_to_trash = fake_bin
    asked = []
    aw.confirm_delete_from_disk = lambda p, parent=None: (asked.append(list(p)), False)[1]
    select(1); lt._delete_btn.click()
    assert asked == [[paths[1]]] and not moved and all(os.path.exists(p) for p in paths)

    # --- confirming deletes the selected photos (and a sidecar), leaves the rest, and the open photo moves on
    c.open_file(paths[2]); assert c.state.image_path == paths[2]
    aw.confirm_delete_from_disk = lambda p, parent=None: True
    select(1, 2); lt._delete_btn.click()
    assert not os.path.exists(paths[1]) and not os.path.exists(paths[2]) and not os.path.exists(paths[1] + ".xmp")
    assert all(os.path.exists(paths[i]) for i in (0, 3, 4))
    assert sorted(os.listdir(bin_dir)) == ["1_img1.png.xmp", "2_img1.png", "3_img2.png.xmp", "4_img2.png"], os.listdir(bin_dir)
    assert shown() == [names[0], names[3], names[4]] and win._filmstrip.paths() == [paths[0], paths[3], paths[4]]
    assert c.state.image_path == paths[3], c.state.image_path
    assert c.hidden_photos() == []
    idx = LibraryIndex(); left = {os.path.basename(r["path"]) for r in idx.all()}; idx.close()
    assert left == {names[0], names[3], names[4]}

    # --- a failing bin leaves the photo and says so
    warned = []
    QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a[2]))
    def broken(p): raise OSError("locked")
    removal.send_to_trash = broken
    win.delete_photos([paths[4]])
    assert os.path.exists(paths[4]) and warned and "could not be deleted" in warned[-1] and shown().count(names[4]) == 1

    # --- no Recycle Bin at all: refused, nothing deleted
    def nobin(p): raise removal.TrashUnavailable("There is no Recycle Bin.")
    removal.send_to_trash = nobin
    win.delete_photos([paths[4]])
    assert os.path.exists(paths[4]) and "no Recycle Bin" in warned[-1]

    # --- the filmstrip menu and the File menu reach the same actions
    menu = win._filmstrip.build_context_menu(paths[4])
    labels = [a.text() for a in menu.actions() if a.text()]
    assert any(t.startswith("Remove") for t in labels) and any("Delete" in t and "Disk" in t for t in labels)
    got = []
    win._filmstrip.remove_requested.connect(got.append)
    [a for a in menu.actions() if a.text().startswith("Remove")][0].trigger()
    assert got == [[paths[4]]] and paths[4] not in win._filmstrip.paths()
    ctx = lt.build_context_menu(); assert any("Delete" in a.text() for a in ctx.actions())
    c.open_file(paths[0]); win._remove_open_action.trigger()
    assert paths[0] not in win._filmstrip.paths() and os.path.exists(paths[0])
    win.close()
    print("REMOVAL UI OK")
''')


def test_remove_and_delete_photos_through_the_interface():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert "REMOVAL UI OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3500:]
