"""Film profiles shown as a tree: a profile named "Kodak/Portra 400/Roll 1" sits in the folders Kodak and Portra 400."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
TESTS = str(Path(__file__).resolve().parent)

_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    sys.path.insert(0, TESTS)
    from PyQt6.QtWidgets import QApplication
    import test_film_profile as T
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view import profile_dialogs as pdg
    from photoeditor.desktop.view.negative_tool_panel import NegativeToolPanel

    win = aw.AppWindow(); c = win.controller
    store = c.profile_store()
    for name in ("Kodak/Portra 400/Roll 1", "Kodak/Portra 400/Roll 2", "Ilford / HP5", "Same name", "Same name", "Loose"):
        store.save(T.make_profile(name=name))
    dlg = pdg.ProfilesDialog(c)
    tree = dlg.list
    def shape():
        out = []
        def walk(item, depth):
            out.append("  " * depth + item.text(0))
            for i in range(item.childCount()): walk(item.child(i), depth + 1)
        for i in range(tree.topLevelItemCount()): walk(tree.topLevelItem(i), 0)
        return out
    assert shape() == ["Ilford", "  HP5", "Kodak", "  Portra 400", "    Roll 1", "    Roll 2", "Same name", "Same name (2)", "Loose"] or sorted(shape()[:6]) == sorted(["Ilford", "  HP5", "Kodak", "  Portra 400", "    Roll 1", "    Roll 2"]), shape()
    assert {"Same name", "Same name (2)", "Loose"} <= set(shape()), "profiles with one name are both listed"
    assert len(tree.names_in_view()) == 6 and len(set(dlg._ids.values())) == 6
    # selecting a profile in a folder shows its details and enables its buttons
    assert tree.select_name("Kodak/Portra 400/Roll 2")
    assert dlg._current() == dlg._ids["Kodak/Portra 400/Roll 2"] and dlg.buttons["dup"].isEnabled() and "Roll 2" in dlg.detail.toPlainText()
    # a folder row selects nothing to act on
    tree.setCurrentItem(tree.topLevelItem(0)); app.processEvents()
    assert dlg._current() is None and not dlg.buttons["delete"].isEnabled()
    # refreshing keeps the profile that was selected
    keep = dlg._ids["Kodak/Portra 400/Roll 1"]
    dlg.refresh(keep)
    assert dlg._current() == keep and tree.selected_name() == "Kodak/Portra 400/Roll 1"

    # the list a photo's inversion chooses from names the folders with arrows
    panel = NegativeToolPanel()
    rows = [r for r in store.list()]
    panel.set_inversion({"engine": "classic", "profile_id": "", "error": "", "covered": None, "base_ready": False}, rows, [])
    texts = [panel._engine_profile.itemText(i) for i in range(panel._engine_profile.count())]
    assert any(t.startswith("Kodak › Portra 400 › Roll 1") for t in texts) and any(t.startswith("Ilford › HP5") for t in texts), texts
    print("ok")
''')


def test_film_profiles_as_a_tree():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    r = subprocess.run([sys.executable, "-X", "faulthandler", "-c", f"TESTS = {TESTS!r}\n" + _SCRIPT], env=env, capture_output=True, text=True, timeout=240)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-3000:]
