"""Presets as a tree (folders by slashes) with My Presets and Built-in Presets buttons, and the built-in Lab Scanners presets."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from photoeditor.features.lookpresets import builtin

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_the_builtin_presets_include_the_lab_scanner_looks():
    names = builtin.names()
    assert {"Lab Scanners/Frontier 100", "Lab Scanners/Crystal 100", "Lab Scanners/Noritsu (Green Shadows)"} <= set(names)
    frontier = builtin.get("lab scanners / FRONTIER 100")
    assert frontier is not None and frontier["saturation"] > 0 and frontier["print_toe"] > 0, "found without regard to case or spacing"
    assert builtin.get("Lab Scanners/Crystal 100")["print_toe"] < 0, "Crystal has the deeper blacks"
    assert builtin.get("Lab Scanners/Noritsu (Green Shadows)")["tint"] < 0, "a faint green in the shadows"
    assert "Frontier" in builtin.description("Lab Scanners/Frontier 100") and builtin.get("nope") is None and builtin.description("nope") == ""


def test_every_builtin_look_uses_only_fields_a_look_can_hold():
    import json

    from photoeditor.features.lookpresets.modules import LOOK_KEYS

    raw = json.loads((builtin.PRESET_DIR / "lab-scanners.json").read_text(encoding="utf-8"))
    for item in raw["presets"]:
        assert item["description"] and set(item["look"]) <= set(LOOK_KEYS), (item["name"], set(item["look"]) - set(LOOK_KEYS))


def test_my_presets_keep_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    from photoeditor.features.lookpresets import store

    assert store.save_preset("  B&W /  Number   1 ", {"contrast": 0.1}) == "B&W/Number 1"
    assert store.names() == ["B&W/Number 1"] and store.get("b&w/number 1") == {"contrast": 0.1}
    assert store.replace_preset("B&W/Number 1", "Film/B&W/Number 1", {"contrast": 0.2}) == "Film/B&W/Number 1"
    assert store.delete_preset("film/b&w/number 1") and store.names() == []


_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QInputDialog
    from photoeditor.features.settings import logic as S
    from photoeditor.features.lookpresets import store
    S.save({"scan_quality": False})
    p = os.path.join(work, "a.png")
    cv2.imwrite(p, np.random.default_rng(0).integers(60, 200, (200, 300, 3), dtype=np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.show(); win.resize(1500, 900); win.open_folder(work, prefer=p)
    c = win.controller
    def pump(s):
        end = time.time() + s
        while time.time() < end:
            app.processEvents(); time.sleep(0.01)
    pump(1.5)
    panel = win._presets_panel
    tree = panel._tree
    def shape(widget=None):
        out = []
        def walk(item, depth):
            out.append(("  " * depth) + item.text(0))
            for i in range(item.childCount()): walk(item.child(i), depth + 1)
        for i in range(tree.topLevelItemCount()): walk(tree.topLevelItem(i), 0)
        return out

    # two buttons; My Presets first (empty), Built-in Presets are the ones that come with EFAS
    assert panel._mine_btn.text() == "My Presets" and panel._builtin_btn.text() == "Built-in Presets"
    assert panel._mine_btn.isChecked() and not panel.showing_builtin() and shape() == ["No presets yet."]
    assert panel._save_btn.isVisibleTo(panel) and not panel._copy_btn.isVisibleTo(panel)
    panel._builtin_btn.click(); pump(0.1)
    assert panel.showing_builtin() and not panel._mine_btn.isChecked()
    assert shape() == ["Film Stocks", "  Cinestill", "    Cinestill", "  Fuji", "    Superia", "  Kodak", "    Gold", "    Portra", "    Portra Airy",
                       "Lab Scanners", "  Frontier 100", "  Crystal 100", "  Pakon (Clean and Rich)", "  Noritsu (Green Shadows)"], shape()
    assert not panel._save_btn.isVisibleTo(panel) and not panel._delete_btn.isVisibleTo(panel) and panel._copy_btn.isVisibleTo(panel), "built-ins are read-only"

    # select a built-in: its description shows; applying it sets the slider values as one undoable step
    folder = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount()) if tree.topLevelItem(i).text(0) == "Lab Scanners")
    assert folder.isExpanded()
    item = folder.child(0)
    tree.setCurrentItem(item); pump(0.1)
    assert panel.selected() == "Lab Scanners/Frontier 100" and "Frontier" in panel._note.text() and not panel._note.isHidden()
    steps = len(c.state.history)
    panel._apply_btn.click(); pump(0.9)
    s = c.state
    assert abs(s.saturation - 0.10) < 1e-6 and abs(s.shadows + 0.24) < 1e-6 and abs(s.print_toe - 0.11) < 1e-6 and abs(s.temperature - 0.072) < 1e-6
    assert len(s.history) == steps + 1 and "built-in preset 'Lab Scanners/Frontier 100'" in s.history[-1].description
    c.undo(); pump(0.5)
    assert c.state.saturation == 0.0 and c.state.print_toe == 0.0
    # double-click applies too, and hovering a built-in previews it without applying
    shown = []
    real = win._image_view.update_pixels
    win._image_view.update_pixels = lambda px: (shown.append(px.copy()), real(px))[1]
    panel._tree.hovered.emit("Lab Scanners/Crystal 100"); pump(0.6)
    assert shown and win._preset_previewing and c.state.print_toe == 0.0, "previewed, not applied"
    panel._tree.hover_left.emit(); pump(0.2)
    assert not win._preset_previewing
    panel._tree.activated_name.emit("Lab Scanners/Noritsu (Green Shadows)"); pump(0.9)
    assert abs(c.state.tint + 0.05) < 1e-6
    c.undo(); pump(0.5)

    # copy a built-in to My Presets: it lands in the same folder, and the list switches to it
    tree.setCurrentItem(folder.child(1)); pump(0.1)
    panel._copy_btn.click(); pump(0.3)
    assert not panel.showing_builtin() and store.names() == ["Lab Scanners/Crystal 100"] and panel.selected() == "Lab Scanners/Crystal 100"
    assert shape() == ["Lab Scanners", "  Crystal 100"]
    # copying again never replaces what is there
    c.copy_builtin_preset("Lab Scanners/Crystal 100"); c.copy_builtin_preset("Lab Scanners/Crystal 100"); pump(0.2)
    assert store.names() == ["Lab Scanners/Crystal 100", "Lab Scanners/Crystal 100 copy", "Lab Scanners/Crystal 100 copy 2"], store.names()

    # saving with a slash makes a folder; a folder you were in is offered as the start of the name
    asked = []
    QInputDialog.getText = staticmethod(lambda parent, title, prompt, **kw: (asked.append(kw.get("text", "")), (answers.pop(0), True))[1])
    answers = ["B&W/Number 1"]
    panel._save(); pump(0.3)
    assert asked == ["Lab Scanners/"], "the folder of the selected preset starts the name"
    assert "B&W/Number 1" in store.names() and panel.selected() == "B&W/Number 1"
    assert shape()[0] == "B&W" and shape()[1] == "  Number 1", shape()
    answers = ["B&W/Number 2"]; asked.clear()
    panel._save("B&W"); pump(0.3)
    assert asked == ["B&W/"] and "B&W/Number 2" in store.names()

    # right-click: folders and presets get their own menus
    menus = []
    QMenu.exec = lambda self, *a: menus.append([x.text() for x in self.actions() if x.text()])
    panel._context_menu("folder", "B&W", None); panel._context_menu("preset", "B&W/Number 1", None)
    assert menus[0] == ["Save Current Look Here...", "Rename Folder...", "Delete Folder and Its Presets..."], menus[0]
    assert menus[1] == ["Apply", "Rename or Move...", "Delete"], menus[1]

    # rename or move a preset, rename a whole folder, refuse a clash, delete a folder
    answers = ["Film/B&W/Number One"]
    panel._rename("B&W/Number 1"); pump(0.2)
    assert "Film/B&W/Number One" in store.names() and "B&W/Number 1" not in store.names()
    answers = ["Mono"]
    panel._rename_folder("B&W"); pump(0.2)
    assert "Mono/Number 2" in store.names() and "B&W/Number 2" not in store.names()
    assert c.rename_look_folder("Mono", "Lab Scanners") == 1 and "Lab Scanners/Number 2" in store.names(), "a folder can be moved into another"
    store.save_preset("Z/x", {"contrast": 0.1}); store.save_preset("Y/x", {"contrast": 0.2})
    assert c.rename_look_folder("Z", "Y") == 0 and "Z/x" in store.names() and "Y/x" in store.names(), "a name that is taken stops the rename"
    n = c.delete_look_folder("Lab Scanners")
    assert n == 4 and not any(x.startswith("Lab Scanners/") for x in store.names()) and "Y/x" in store.names()
    pump(0.2)
    assert shape()[0] == "Film" and "Y" in shape() and "Z" in shape()
    print("ok")
''')


def test_preset_tree_and_built_in_presets_in_the_window():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    r = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-2500:] + r.stderr[-3500:]
