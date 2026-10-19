"""Sharing presets in the window: the Export and Import buttons of the Presets panel, the right-click menus, the module header's menu, and what the person is asked and told."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r"""
    import json, os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp()
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False, "advanced_mode": False})
    from PyQt6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view import preset_sharing as PS
    from photoeditor.features.lookpresets import module_store, share, store
    win = aw.AppWindow(); win.show()
    panel = win._presets_panel; c = win.controller
    def pump(s):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(0.5)

    look = {"exposure_ev": 0.5, "saturation": -0.2, "film_type": "c41", "marks": {"text": "(c) Me", "logo": r"\\server\share\logo.svg"}, "metering": {"film": "user:mine.json", "grade": 0.1}}
    store.save_preset("Film/Warm", look); store.save_preset("Film/B&W/Soft", {"contrast": 0.3}); store.save_preset("Top", {"saturation": 0.4})
    store.set_folders(["Film/Spare"]); module_store.save_preset("exposure", "Push a stop", {"exposure_ev": 1.0}); module_store.save_preset("color", "Vivid", {"saturation": 0.5})
    c.look_presets_changed.emit("")
    pump(0.2)

    shown = []; told = []
    QMenu.exec = lambda self, *a, **k: shown.append([x.text() for x in self.actions()])
    QMessageBox.warning = staticmethod(lambda *a, **k: told.append(("warning", a[2])))
    QMessageBox.information = staticmethod(lambda *a, **k: told.append(("info", a[2])))
    asked = []
    def choose(policy):
        PS.ask_import = lambda parent, pack, conflicts, name: (asked.append((pack.describe(), conflicts, name)), policy)[1]
    def file_for_save(path): QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (path, ""))
    def file_for_open(path): QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (path, ""))
    def entry(menu, text): return next(a for a in menu.actions() if a.text() == text)

    # the buttons and menus: Export and Import are there for My Presets (not for the built-in list); the Export menu offers what is selected, and everything
    assert panel._export_btn.isVisible() and panel._import_btn.isVisible()
    panel._tree.select_name("Film/Warm"); pump(0.1)
    panel._fill_export_menu()
    assert [a.text() for a in panel._export_menu.actions()] == ["Export the Selected Preset...", "Export All My Presets and Module Presets..."]
    panel._context_menu("preset", "Film/Warm", None); assert "Export Preset..." in shown[-1], shown[-1]
    panel._context_menu("folder", "Film", None); assert "Export Folder..." in shown[-1], shown[-1]
    panel._context_menu("", "", None); assert "Import Presets..." in shown[-1], shown[-1]
    panel.show_builtin(True); pump(0.1)
    assert not panel._export_btn.isVisible() and panel._import_btn.isVisible(), "built-in presets are EFAS's own: nothing to export, but a file can still be imported"
    panel.show_builtin(False); pump(0.1)

    # export one preset
    one = os.path.join(work, "one")      # no extension typed: the right one is added
    file_for_save(one)
    entry(panel._export_menu, "Export the Selected Preset...").trigger(); pump(0.1)
    assert os.path.isfile(one + ".efaspresets"), os.listdir(work)
    text = open(one + ".efaspresets", encoding="utf-8").read()
    data = json.loads(text)
    assert data["format"] == "efas-presets" and [p["name"] for p in data["look_presets"]] == ["Film/Warm"] and "module_presets" not in data
    assert "server" not in text and "user:" not in text, "no path of a computer, no film profile of the sender's own"
    assert data["look_presets"][0]["look"]["marks"] == {"text": "(c) Me"} and data["look_presets"][0]["look"]["metering"]["film"] == "generic"
    assert told and told[-1][0] == "info" and "logo" in told[-1][1] and "film profile" in told[-1][1] and "watermark" in told[-1][1], told

    # export a folder (with what is in it, folders inside, and the empty folder that was made on purpose)
    told.clear(); folder_file = os.path.join(work, "film.efaspresets"); file_for_save(folder_file)
    assert PS.PresetSharing.export_presets(win._preset_sharing, panel, "folder", "Film")
    data = json.load(open(folder_file, encoding="utf-8"))
    assert sorted(p["name"] for p in data["look_presets"]) == ["Film/B&W/Soft", "Film/Warm"] and data["folders"] == ["Film/Spare"]

    # export everything: looks, folders and the module presets
    allfile = os.path.join(work, "all.efaspresets"); file_for_save(allfile)
    entry(panel._export_menu, "Export All My Presets and Module Presets...").trigger(); pump(0.1)
    data = json.load(open(allfile, encoding="utf-8"))
    assert len(data["look_presets"]) == 3 and sorted(data["module_presets"]) == ["color", "exposure"]

    # one module's presets, from the module header's menu
    modfile = os.path.join(work, "exposure.efaspresets"); file_for_save(modfile)
    assert win._preset_sharing.export_presets(panel, "module", "exposure")
    data = json.load(open(modfile, encoding="utf-8"))
    assert data["look_presets"] == [] and list(data["module_presets"]) == ["exposure"]
    assert os.path.basename(PS.PresetSharing._default_name(win._preset_sharing, "module", "exposure")) == "Exposure presets.efaspresets"
    # (and nothing to export: nothing is asked)
    module_store.delete_preset("color", "Vivid"); file_for_save(os.path.join(work, "nothing.efaspresets"))
    assert not win._preset_sharing.export_presets(panel, "module", "color") and not os.path.exists(os.path.join(work, "nothing.efaspresets"))

    # the menu in a module's header has the two entries
    shown.clear()
    exposure_panel = win._module_menus._panels.get("exposure")
    assert exposure_panel is not None
    win._module_menus._show_menu(exposure_panel, "exposure")
    assert "Export this module's presets..." in shown[-1] and "Import presets..." in shown[-1], shown[-1]

    # import into a library that has none of it: everything arrives, the list refreshes, the module menu is told
    for n in store.names(): store.delete_preset(n)
    store.set_folders([]); module_store.delete_preset("exposure", "Push a stop")
    changed = []; c.module_presets_changed.connect(changed.append)
    c.look_presets_changed.emit(""); pump(0.1)
    choose(share.KEEP_BOTH); file_for_open(allfile)
    assert win._preset_sharing.import_presets(panel)
    assert asked[-1] == ("3 look presets and 2 module presets", 0, "all.efaspresets"), asked
    assert sorted(store.names()) == ["Film/B&W/Soft", "Film/Warm", "Top"] and store.folders() == ["Film/Spare"]
    assert store.get("Film/Warm")["exposure_ev"] == 0.5 and "marks" in store.get("Film/Warm") and "logo" not in store.get("Film/Warm")["marks"]
    assert module_store.names("exposure") == ["Push a stop"] and module_store.names("color") == ["Vivid"] and sorted(changed) == ["color", "exposure"]
    assert sorted(panel._mine) == ["Film/B&W/Soft", "Film/Warm", "Top"], "the list shows what was imported"
    assert "Imported 5 presets" in win._coord_label.text(), win._coord_label.text()

    # the same file again: every name is taken. Keep both, skip, replace, cancel
    choose(share.KEEP_BOTH); assert win._preset_sharing.import_presets(panel)
    assert asked[-1][1] == 5 and "Film/Warm (imported)" in store.names() and len(store.names()) == 6 and module_store.names("exposure") == ["Push a stop", "Push a stop (imported)"]
    n = len(store.names()); choose(share.SKIP); assert not win._preset_sharing.import_presets(panel) and len(store.names()) == n
    assert "Nothing was imported" in win._coord_label.text()
    store.save_preset("Top", {"saturation": 0.99}); choose(share.REPLACE); assert win._preset_sharing.import_presets(panel)
    assert store.get("Top") == {"saturation": 0.4} and len(store.names()) == n, "replaced in place, not added"
    store.save_preset("Top", {"saturation": 0.99}); choose(None); assert not win._preset_sharing.import_presets(panel)
    assert store.get("Top") == {"saturation": 0.99}, "cancelled: nothing changes"

    # a file that is not a presets file: the person is told, nothing is asked, nothing changes
    junk = os.path.join(work, "junk.efaspresets"); open(junk, "w").write("this is not json"); file_for_open(junk)
    told.clear(); n_asked = len(asked)
    assert not win._preset_sharing.import_presets(panel)
    assert told and told[-1][0] == "warning" and "could not be read" in told[-1][1] and len(asked) == n_asked, told
    newer = os.path.join(work, "newer.efaspresets"); open(newer, "w").write(json.dumps({"format": "efas-presets", "version": 99, "look_presets": []})); file_for_open(newer)
    assert not win._preset_sharing.import_presets(panel) and "newer EFAS" in told[-1][1]
    file_for_open(os.path.join(work, "missing.efaspresets")); assert not win._preset_sharing.import_presets(panel) and "could not be read" in told[-1][1]
    file_for_open(""); assert not win._preset_sharing.import_presets(panel), "the file dialog was cancelled"
    win.close()
    print("OK")
""")


def test_presets_are_shared_through_files_in_the_window():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC, "PHOTOEDITOR_AUDIO": "off"})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1800:] + out.stderr[-3000:]
