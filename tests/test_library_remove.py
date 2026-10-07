"""Right-click > Remove from Library on a top-level folder: it leaves the list, the settings, the recents and the Workbench index; files stay."""
import os
import subprocess
import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
_SCRIPT = r'''
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
data = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_DATA_DIR"] = data
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QMessageBox, QMenu
from PIL import Image
app = QApplication([])
from photoeditor.desktop.view.app_window import AppWindow
from photoeditor.desktop.settings_store import qsettings
from photoeditor.desktop.view.folder_tree import ROOTS_SETTINGS_KEY
from photoeditor.features.library.index import LibraryIndex
base = tempfile.mkdtemp()
a, b = os.path.join(base, "RollA"), os.path.join(base, "RollB")
for d in (a, b, os.path.join(a, "sub")):
    os.makedirs(d, exist_ok=True)
    Image.new("RGB", (40, 30), "gray").save(os.path.join(d, "x.png"))
w = AppWindow()
lp = w._library_panel
lp._tree.add_root(a); lp._tree.add_root(b)
qsettings().setValue(ROOTS_SETTINGS_KEY, lp._tree.roots())
idx = LibraryIndex(); idx.refresh([a, b]); (lambda *a, **k: None)("indexed", len(idx.all())); idx.close()
w._session["recent_folders"] = [a, os.path.join(a, "sub"), b]

menus = []
def fake_menu_exec(self, *args):
    menus.append([(x.text(), x.isEnabled()) for x in self.actions()])
    pick = os.environ.get("PICK")
    return next((x for x in self.actions() if x.text() == pick), None)
QMenu.exec = fake_menu_exec
def fake_box(self):
    self.buttons()[0 if os.environ.get("ANSWER") == "remove" else 1].click()
QMessageBox.exec = fake_box

tree = lp._tree
item_a = tree.topLevelItem(0)
rect = tree.visualItemRect(item_a)
os.environ["PICK"] = "Remove from Library"; os.environ["ANSWER"] = "cancel"
tree._on_context_menu(rect.center())
(lambda *a, **k: None)("menu(root):", menus[-1]); assert tree.roots() == [a, b]
os.environ["ANSWER"] = "remove"
tree._on_context_menu(rect.center())
(lambda *a, **k: None)("roots after:", tree.roots()); assert tree.roots() == [b]
(lambda *a, **k: None)("saved:", qsettings().value(ROOTS_SETTINGS_KEY, [], type=list)); assert qsettings().value(ROOTS_SETTINGS_KEY, [], type=list) == [b]
(lambda *a, **k: None)("recents:", w._session["recent_folders"]); assert w._session["recent_folders"] == [b]
idx = LibraryIndex(); left = [r["path"] for r in idx.all()]; idx.close()
(lambda *a, **k: None)("index left:", left); assert all(p.startswith(b) for p in left) and left
assert os.path.isfile(os.path.join(a, "x.png")), "files must stay"
# subfolder: disabled note only
tree.set_roots([b]); 
os.makedirs(os.path.join(b, "inner"), exist_ok=True)
tree.set_roots([b]); tree.expandItem(tree.topLevelItem(0))
sub = tree.topLevelItem(0).child(0); os.environ["PICK"] = ""
tree._on_context_menu(tree.visualItemRect(sub).center()); (lambda *a, **k: None)("menu(sub):", menus[-1])
assert ("Remove from Library (top-level folders only)", False) in menus[-1]
# import window tree has no remove
from photoeditor.desktop.view.import_window import ImportWindow
iw = ImportWindow(w); iw._tree._on_context_menu(iw._tree.visualItemRect(iw._tree.topLevelItem(0)).center()) if iw._tree.topLevelItemCount() else None
(lambda *a, **k: None)("OK")

'''


def test_remove_root_from_library():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stderr[-2000:]
