"""The Tagging panel on the left of the editor and the Workbench, in the running app."""
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r'''
    import os, sys, time, faulthandler
    faulthandler.enable()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    import numpy as np, cv2
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QInputDialog, QMenu, QMessageBox
    from photoeditor.features.settings import logic as S
    from photoeditor.features.tags import tagging as G
    S.save({"scan_quality": False})
    DATA = os.environ["PHOTOEDITOR_DATA_DIR"]
    folder = os.path.join(DATA, "photos"); os.makedirs(folder)
    rng = np.random.default_rng(1)
    paths = []
    for name in ("a.png", "b.png", "c.png"):
        img = cv2.GaussianBlur(rng.random((200, 300, 3)).astype(np.float32), (0, 0), 15)
        p = os.path.join(folder, name); cv2.imwrite(p, (60 + 140 * (img - img.min()) / np.ptp(img)).astype(np.uint8)); paths.append(p)
    A, B, C = paths
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); win.show(); app.processEvents()
    win.open_folder(folder, prefer=A)
    def pump(cond=lambda: False, secs=15.0):
        end = time.time() + secs
        while time.time() < end:
            app.processEvents()
            if cond(): return True
            time.sleep(0.01)
        return cond()
    c = win.controller
    assert pump(lambda: c.state.image_rgb is not None); pump(secs=0.3)
    P = win._tagging_panel
    W = win._lighttable.tagging
    assert P is not W and P.windowTitle() is not None
    attached = lambda panel: [panel._attached.item(i).text() for i in range(panel._attached.count())]
    listed = lambda panel: [panel._list.item(i).text() for i in range(panel._list.count())]

    # ---- attached tags of the open photo, and the dictionary
    c.set_tags_for([A], add=["People/Family", "Holiday"])
    c.set_tags_for([B], add=["People/Family", "People/Friends"])
    pump(secs=0.2)
    assert attached(P) == ["Holiday", "People › Family"], attached(P)
    assert "Holiday" in P._hint.text() or P._hint.text().startswith("Tags for this photo")
    texts = listed(P)
    assert any(t.startswith("✓ Holiday") and t.endswith("(1)") for t in texts), texts
    assert any(t.startswith("✓ People › Family") and t.endswith("(2)") for t in texts), texts
    assert any(t.strip().startswith("People › Friends") and not t.startswith("✓") for t in texts)

    # ---- the entry box filters; Enter attaches the best match
    P._entry.setText("friend")
    assert [t.strip().split("   ")[0] for t in listed(P)] == ["People › Friends"], listed(P)
    QTest.keyClick(P._entry, Qt.Key.Key_Return)
    pump(secs=0.2)
    assert "People/Friends" in c.photo_tags(A) and P._entry.text() == ""
    # nothing fits: Enter makes the tag and attaches it
    P._entry.setText("Brand/New thing")
    assert listed(P) == []
    QTest.keyClick(P._entry, Qt.Key.Key_Return)
    pump(secs=0.2)
    assert "Brand/New thing" in c.photo_tags(A), c.photo_tags(A)
    # New makes exactly what is typed, even when something fuzzy would match
    P._entry.setText("fam")
    P._new_btn.click(); pump(secs=0.2)
    assert "fam" in c.photo_tags(A) and "fam" in c.tag_usage()

    # ---- double-click attaches from the dictionary and detaches from the attached list
    P._entry.setText("")
    item = next(P._list.item(i) for i in range(P._list.count()) if P._list.item(i).data(256) == "People/Family")
    P.attach_requested.emit([item.data(256)])
    P._attached.itemDoubleClicked.emit(next(P._attached.item(i) for i in range(P._attached.count()) if P._attached.item(i).data(256) == "fam"))
    pump(secs=0.2)
    assert "fam" not in c.photo_tags(A), "double-click on an attached tag detaches it"
    assert "fam" in c.tag_usage() or "fam" in dict(P._dictionary), "the tag is still in the dictionary"
    P._list.itemDoubleClicked.emit(next(P._list.item(i) for i in range(P._list.count()) if P._list.item(i).data(256) == "fam"))
    pump(secs=0.2)
    assert "fam" in c.photo_tags(A), "double-click on a dictionary tag attaches it"

    # ---- tree view
    P._tree_btn.setChecked(True)
    assert P._tree_btn.text() == "Tree" and P._stack.currentWidget() is P._tree
    top = [P._tree.topLevelItem(i) for i in range(P._tree.topLevelItemCount())]
    names = [t.text(0).strip().split("   ")[0].lstrip("✓– ") for t in top]
    assert "People" in names and "Holiday" in names, names
    people = next(t for t in top if t.data(0, 256) == "People")
    assert people.data(0, 257) is False and people.font(0).italic(), "People is only a level: a free node"
    assert people.childCount() >= 2
    fam = next(people.child(i) for i in range(people.childCount()) if people.child(i).data(0, 256) == "People/Family")
    assert fam.data(0, 257) is True and fam.text(0).startswith("✓ Family")
    P._on_tree_double_click(people, 0)
    assert people.isExpanded(), "double-clicking a free node opens it"
    P._tree.setCurrentItem(fam); fam.setSelected(True)
    assert P._selected_dictionary() == ["People/Family"]
    P._entry.setText("gran")
    assert P._tree.topLevelItemCount() == 0
    P._entry.setText("fri")
    assert P._tree.topLevelItemCount() == 1 and P._tree.topLevelItem(0).isExpanded(), "a filter opens the tree to what fits"
    P._entry.setText("")
    P._tree_btn.setChecked(False)

    # ---- Workbench: several photos selected - counts and check / dash marks
    win.set_view("lighttable"); pump(secs=0.3)
    win._lighttable.selected_paths = lambda: [A, B]
    win._refresh_tagging()
    assert attached(W)[0].endswith("(2/2)") or any("People › Family  (2/2)" == t for t in attached(W)), attached(W)
    assert "People › Family  (2/2)" in attached(W) and "People › Friends  (2/2)" in attached(W) and "Holiday  (1/2)" in attached(W), attached(W)
    marks = {t.strip()[2:].split("   ")[0].strip(): t[0] for t in listed(W) if t.startswith(("✓", "–"))}
    assert marks.get("People › Family") == "✓" and marks.get("Holiday") == "–", marks
    # sort and leaf-only toggles
    W._sort_btn.setChecked(True)
    assert W._sort_btn.text() == "Sort: count" and attached(W)[-1].startswith("Holiday")
    W._leaf_btn.setChecked(True)
    assert "Family  (2/2)" in attached(W), attached(W)
    W._sort_btn.setChecked(False); W._leaf_btn.setChecked(False)
    # attaching in the Workbench goes to the whole selection
    W.attach_requested.emit(["Status/Keeper"])
    pump(secs=0.2)
    assert "Status/Keeper" in c.photo_tags(A) and "Status/Keeper" in c.photo_tags(B) and "Status/Keeper" not in c.photo_tags(C)
    W.detach_requested.emit(["Status/Keeper"])
    pump(secs=0.2)
    assert "Status/Keeper" not in c.photo_tags(A) and "Status/Keeper" not in c.photo_tags(B)
    # nothing selected: New only joins the dictionary, nothing is attached, Attach is off
    win._lighttable.selected_paths = lambda: []
    win._refresh_tagging()
    assert not W._attach_btn.isEnabled() and "pick one" in W._hint.text() or "No photo" in W._hint.text()
    W._entry.setText("Only in dictionary"); W._new_btn.click(); pump(secs=0.2)
    assert c.tagging_data([])[1].get("Only in dictionary") == 0 and not any("Only in dictionary" in c.photo_tags(p) for p in paths)
    assert any("Only in dictionary" in t for t in listed(W)) and any("Only in dictionary" in t for t in listed(P)), "both panels show it"
    W._entry.setText("")

    # ---- suggestions: tags that go with the attached ones
    c.set_tags_for([C], add=["Holiday", "Beach"])
    win._lighttable.selected_paths = lambda: [C]
    win._refresh_tagging()
    W._suggest_btn.setChecked(True)
    suggested = [t.strip().lstrip("✓– ").split("   ")[0] for t in listed(W)]
    assert "People › Family" in suggested and "Holiday" not in suggested and "Beach" not in suggested, suggested
    W._suggest_btn.setChecked(False)

    # ---- right-click: edit name, change path, delete, find, collection
    chosen = {}
    QMenu.exec = lambda self, *a: next(x for x in self.actions() if x.text() == chosen["action"])
    QMessageBox.exec = lambda self: QMessageBox.StandardButton.Yes
    win._lighttable.selected_paths = lambda: [A]
    win._refresh_tagging()
    W._entry.setText("")
    row = next(i for i in range(W._list.count()) if W._list.item(i).data(256) == "Holiday")
    W._list.itemAt = lambda pos: W._list.item(row)
    QInputDialog.getText = staticmethod(lambda *a, **k: ("Vacation", True))
    chosen["action"] = "Edit name..."
    W._dictionary_menu(W._list, QPoint(3, 3)); pump(secs=0.3)
    assert "Vacation" in c.photo_tags(A) and "Holiday" not in c.photo_tags(A) and "Vacation" in c.photo_tags(C)
    # xmp sidecars follow the change
    from photoeditor.features.xmp import logic as xmp
    assert "Vacation" in xmp.read_tags(A) and "Vacation" in xmp.read_tags(C) and "Holiday" not in xmp.read_tags(C)
    row = next(i for i in range(W._list.count()) if W._list.item(i).data(256) == "People/Family")
    W._list.itemAt = lambda pos: W._list.item(row)
    QInputDialog.getText = staticmethod(lambda *a, **k: ("Humans/Relatives", True))
    chosen["action"] = "Change path..."
    W._dictionary_menu(W._list, QPoint(3, 3)); pump(secs=0.3)
    assert "Humans/Relatives" in c.photo_tags(A) and "People/Family" not in c.photo_tags(A)
    assert "Humans/Relatives" in xmp.read_tags(B)
    # cancelling a dialog changes nothing
    QInputDialog.getText = staticmethod(lambda *a, **k: ("whatever", False))
    row = next(i for i in range(W._list.count()) if W._list.item(i).data(256) == "Humans/Relatives")
    W._list.itemAt = lambda pos: W._list.item(row)
    W._dictionary_menu(W._list, QPoint(3, 3)); pump(secs=0.2)
    assert "Humans/Relatives" in c.photo_tags(A)
    # delete: asks first
    asked = []
    QMessageBox.exec = lambda self: (asked.append(self.text()), QMessageBox.StandardButton.No)[1]
    chosen["action"] = "Delete tag"
    W._dictionary_menu(W._list, QPoint(3, 3)); pump(secs=0.2)
    assert asked and "Humans" in asked[0] and "Humans/Relatives" in c.photo_tags(A), "declined: nothing deleted"
    QMessageBox.exec = lambda self: QMessageBox.StandardButton.Yes
    W._dictionary_menu(W._list, QPoint(3, 3)); pump(secs=0.3)
    assert "Humans/Relatives" not in c.photo_tags(A) and "Humans/Relatives" not in c.photo_tags(B) and "Humans/Relatives" not in c.tagging_data([])[1]
    # delete a node with everything inside
    c.set_tags_for([A], add=["Zoo/Cats/Tabby", "Zoo/Dogs"])
    pump(secs=0.2)
    W._tree_btn.setChecked(True)
    zoo = next(W._tree.topLevelItem(i) for i in range(W._tree.topLevelItemCount()) if W._tree.topLevelItem(i).data(0, 256) == "Zoo")
    W._tree.itemAt = lambda pos: zoo
    chosen["action"] = "Delete node (and everything inside)"
    W._dictionary_menu(W._tree, QPoint(3, 3)); pump(secs=0.3)
    assert not any(t.startswith("Zoo") for t in c.photo_tags(A)) and not any(t.startswith("Zoo") for t in c.tagging_data([])[1])
    W._tree_btn.setChecked(False)
    # find in the dictionary and the collection
    chosen["action"] = "Find in the dictionary"
    W._attached.itemAt = lambda pos: W._attached.item(0)
    win._lighttable.selected_paths = lambda: [A]
    win._refresh_tagging()
    first_tag = W._attached.item(0).data(256)
    W._attached_menu(QPoint(3, 3))
    assert W._entry.text() == first_tag
    W._entry.setText("")
    chosen["action"] = "Show photos with this tag"
    W._attached_menu(QPoint(3, 3)); pump(secs=0.3)
    assert win.lighttable_active() and win._lighttable._tag.currentData() == first_tag, win._lighttable._tag.currentData()
    shown = win._lighttable._shown if hasattr(win._lighttable, "_shown") else []
    assert all(first_tag in r.get("tags", ()) or any(t.casefold().startswith(first_tag.casefold() + "/") for t in r.get("tags", ())) for r in shown) and shown, "only the tagged photos are listed"
    win._lighttable.set_filter_state({})
    win.set_view("editor")

    # ---- keyword files
    c.set_tags_for([A], add=["Places/France/Paris"])
    out = os.path.join(DATA, "tags.txt")
    win._export_tags(out)
    text = open(out, encoding="utf-8").read()
    assert "Places\n\tFrance\n\t\tParis\n" in text.replace("\r\n", "\n"), text
    n = c.import_tags("Gear\n\tCameras\n\t\tPentax\n\tLenses\n")
    assert n == 4
    d = c.tagging_data([])[1]
    assert d.get("Gear/Cameras/Pentax") == 0 and d.get("Gear") == 0 and "Gear/Lenses" in d
    assert "Gear/Cameras/Pentax" in c.tag_usage() and c.tag_usage().get("Gear/Cameras") == 0, "the quick tag bar knows the imported ones"
    P.set_expanded(True)
    print("TAGGING UI OK"); sys.stdout.flush(); os._exit(0)
''')


def test_tagging_panel_in_editor_and_workbench():
    data = tempfile.mkdtemp()
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""), PHOTOEDITOR_DATA_DIR=data)
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=600)
    assert "TAGGING UI OK" in done.stdout, done.stdout[-1500:] + done.stderr[-4000:]
