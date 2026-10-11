"""The duplicate finder dialog end to end: scan, the suggested keeper, the safety check, taking extras off the Workbench, and deleting them."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r'''
    import os, shutil, sys, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    folder = os.path.join(work, "roll"); os.makedirs(folder)
    bin_dir = os.path.join(work, "bin"); os.makedirs(bin_dir)
    import numpy as np, cv2
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from photoeditor.features.settings import logic as S
    from photoeditor.features.library import removal, duplicates as D
    from photoeditor.features.library.index import LibraryIndex
    S.save({"scan_quality": False})

    def picture(seed, h=240, w=320):
        base = cv2.GaussianBlur(np.random.default_rng(seed).random((h, w, 3)).astype(np.float32), (0, 0), 12)
        base = (base - base.min()) / np.ptp(base)
        return (base * 255).astype(np.uint8)
    a = os.path.join(folder, "a.png"); cv2.imwrite(a, picture(1))
    a_copy = os.path.join(folder, "a copy.png"); shutil.copy(a, a_copy)
    a_small = os.path.join(folder, "a small.png"); cv2.imwrite(a_small, cv2.resize(picture(1), (160, 120)))
    b = os.path.join(folder, "b.png"); cv2.imwrite(b, picture(2))
    c_ = os.path.join(folder, "c.png"); cv2.imwrite(c_, picture(3))

    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view.duplicates_dialog import DuplicatesDialog
    from photoeditor.desktop.paths import thumbnail_cache_dir

    win = aw.AppWindow(); c = win.controller; lt = win._lighttable
    index = LibraryIndex(); index.refresh([folder]); index.close()
    win.open_folder(folder, prefer=a)
    c.set_rating_for(a_copy, 3)
    win._lighttable_reload_rows()
    rows = lt.all_rows(); assert len(rows) == 5
    infos = [D.Info(r["path"], int(r["size"]), int(r["width"]), int(r["height"]), int(r["rating"]), bool(r["edited"]), int(r["versions"]), len(r["tags"])) for r in rows]

    def run_dialog(mode_index):
        dlg = DuplicatesDialog(infos, thumbnail_cache_dir())
        dlg.mode.setCurrentIndex(mode_index)
        dlg.remove_requested.connect(win.remove_photos)
        dlg._scan(); dlg.wait(); app.processEvents()
        return dlg

    # identical files only: one group, the better rated copy is kept and the other is ticked
    dlg = run_dialog(0)
    assert dlg.tree.topLevelItemCount() == 1 and "Identical files" in dlg.tree.topLevelItem(0).text(0)
    assert [os.path.basename(p) for p in dlg.ticked()] == ["a.png"], dlg.ticked()
    assert "keep (suggested)" in dlg.tree.topLevelItem(0).child(0).text(4) + dlg.tree.topLevelItem(0).child(1).text(4)

    # with look-alikes: a, its copy and the resized one are one picture; b and c are not in any group
    dlg = run_dialog(1)
    groups = [[os.path.basename(dlg.tree.topLevelItem(t).child(k).data(0, Qt.ItemDataRole.UserRole)) for k in range(dlg.tree.topLevelItem(t).childCount())] for t in range(dlg.tree.topLevelItemCount())]
    assert any({"a.png", "a copy.png", "a small.png"} <= set(g) for g in groups) or any(set(g) == {"a.png", "a copy.png"} for g in groups), groups
    assert not any("b.png" in g or "c.png" in g for g in groups)
    assert "could go" in dlg.summary.text()

    # ticking a whole group is refused
    dlg.tree.blockSignals(True)
    for t in range(dlg.tree.topLevelItemCount()):
        for k in range(dlg.tree.topLevelItem(t).childCount()):
            dlg.tree.topLevelItem(t).child(k).setCheckState(0, Qt.CheckState.Checked)
    dlg.tree.blockSignals(False)
    warned = []
    QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a[2]))
    dlg._remove(); dlg._delete()
    assert len(warned) == 2 and "Every photo in at least one group is ticked" in warned[0] and len(lt.all_rows()) == 5

    # the suggestion, then remove the ticked extras from the Workbench: files stay, the keeper stays
    dlg.tick_extras()
    ticked = [os.path.basename(p) for p in dlg.ticked()]
    assert "a copy.png" not in ticked and ticked, ticked
    dlg._remove()
    assert all(os.path.exists(p) for p in (a, a_copy, a_small, b, c_))
    left = sorted(os.path.basename(r["path"]) for r in lt.all_rows())
    assert "a copy.png" in left and len(left) == 5 - len(ticked), left
    assert dlg.tree.topLevelItemCount() == 0 or all(dlg.tree.topLevelItem(t).childCount() >= 2 for t in range(dlg.tree.topLevelItemCount()))
    win.controller.restore_photos(c.hidden_photos()); win._lighttable_reload_rows()
    assert len(lt.all_rows()) == 5

    # delete the extras from disk through the usual confirmation (stand-in bin)
    moved = []
    def fake_bin(p):
        moved.append(p); os.replace(p, os.path.join(bin_dir, f"{len(moved)}_" + os.path.basename(p)))
    removal.send_to_trash = fake_bin
    asked = []
    aw.confirm_delete_from_disk = lambda p, parent=None: (asked.append(list(p)), True)[1]
    infos[:] = [D.Info(r["path"], int(r["size"]), int(r["width"]), int(r["height"]), int(r["rating"]), bool(r["edited"]), 1, 0) for r in lt.all_rows()]
    dlg = DuplicatesDialog(infos, thumbnail_cache_dir()); dlg.mode.setCurrentIndex(0)
    dlg.delete_requested.connect(lambda ps: (win.delete_photos(ps), dlg.drop([p for p in ps if not os.path.exists(p)])))
    dlg._scan(); dlg.wait(); app.processEvents()
    assert [os.path.basename(p) for p in dlg.ticked()] == ["a.png"]
    dlg._delete()
    assert asked == [[a]] and not os.path.exists(a) and os.path.exists(a_copy) and os.path.exists(b)
    assert dlg.tree.topLevelItemCount() == 0
    win.close()
    print("DUPLICATES UI OK")
''')


def test_duplicate_finder_through_the_interface():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert "DUPLICATES UI OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3500:]
