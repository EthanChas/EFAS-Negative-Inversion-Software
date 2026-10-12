"""File > Uninstall EFAS (the dialog, its warning and confirmation) and the first start of the new version moving an old data folder by itself."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_DIALOG = textwrap.dedent(r'''
    import os, sys, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    root = tempfile.mkdtemp()
    for var in ("USERPROFILE", "HOME"):
        os.environ[var] = root
    os.environ["LOCALAPPDATA"] = os.path.join(root, "Local"); os.environ["APPDATA"] = os.path.join(root, "Roaming"); os.environ["XDG_CACHE_HOME"] = os.path.join(root, "cache")
    os.environ["PHOTOEDITOR_DATA_DIR"] = os.path.join(root, "data")
    os.makedirs(os.environ["PHOTOEDITOR_DATA_DIR"])
    from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
    from photoeditor.features.uninstall import logic as un
    from photoeditor.desktop.view.uninstall_dialog import UninstallDialog
    app = QApplication([])

    # the dialog: nothing happens until the word is typed, and the warning shows only while data is ticked
    d = UninstallDialog([r"C:\Users\x\.EFAS"], r"C:\Programs\EFAS.exe")
    d.show()
    assert d.program_box.isChecked() and d.data_box.isChecked() and not d.ok_btn.isEnabled()
    assert "CANNOT BE UNDONE" in d.warning.text() and d.warning.isVisible()
    d.confirm.setText("uninstal"); assert not d.ok_btn.isEnabled()
    d.confirm.setText("uninstall"); assert d.ok_btn.isEnabled() and "Delete my data and uninstall" in d.ok_btn.text()
    d.data_box.setChecked(False); assert not d.warning.isVisible() and d.ok_btn.text() == "Uninstall" and d.choices() == (False, True)
    d.program_box.setChecked(False); assert not d.ok_btn.isEnabled() and not d.confirm.isVisible(), "nothing ticked: nothing to do"
    d.data_box.setChecked(True); assert d.choices() == (True, False)
    src = UninstallDialog([], None); src.show()
    assert not src.program_box.isEnabled() and src.choices()[1] is False, "running from source: no program to remove"

    # File > Uninstall EFAS...
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.show(); app.processEvents()
    assert win._uninstall_action.text() == "Uninstall EFAS..."
    launched = []
    un.launch = lambda plan, *a, **k: launched.append(plan) or "script"
    closed = []
    real_close = win.close
    win.close = lambda: closed.append(True)
    answer = {"v": QDialog.DialogCode.Rejected}
    UninstallDialog.exec = lambda self: answer["v"]
    win._on_uninstall()
    assert not launched and not closed, "cancelling does nothing"
    answer["v"] = QDialog.DialogCode.Accepted
    UninstallDialog.exec = lambda self: answer["v"]
    win._on_uninstall()
    assert len(launched) == 1 and closed == [True]
    assert launched[0].folders == [os.environ["PHOTOEDITOR_DATA_DIR"]], launched[0].folders
    win.close = real_close
    # a failure to start the helper removes nothing and keeps the app open
    def boom(*a, **k): raise OSError("no")
    un.launch = boom
    shown = []
    QMessageBox.critical = staticmethod(lambda *a, **k: shown.append(a[2]))
    closed.clear(); win.close = lambda: closed.append(True)
    win._on_uninstall()
    assert shown and "nothing was removed" in shown[0] and not closed
    win.close = real_close; win.close()
    print("UNINSTALL UI OK"); sys.stdout.flush(); os._exit(0)
''')

_FIRST_START = textwrap.dedent(r'''
    import os, sys, tempfile, sqlite3
    root = tempfile.mkdtemp()
    for var in ("USERPROFILE", "HOME"):
        os.environ[var] = root
    os.environ["LOCALAPPDATA"] = os.path.join(root, "Local")
    os.environ["APPDATA"] = os.path.join(root, "Roaming")
    os.environ["XDG_CACHE_HOME"] = os.path.join(root, "cache")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ.pop("PHOTOEDITOR_DATA_DIR", None)
    old = os.path.join(root, ".photoeditor"); os.makedirs(os.path.join(old, "backups"))
    from photoeditor.features.persistence import edit_store
    from photoeditor.desktop.export_worker import default_edit_state
    conn = edit_store.connect(os.path.join(old, "photoeditor.db"))
    for i in range(5):
        edit_store.save_edit_state(conn, f"C:/p/{i}.jpg", {**default_edit_state(False), "exposure_ev": 0.1 * i})
    conn.commit(); conn.close()
    open(os.path.join(old, "look_presets.json"), "w").write('{"presets": [{"name": "Warm"}]}')
    open(os.path.join(old, "settings.json"), "w").write('{"advanced_mode": true}')
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); app.processEvents()
    new = os.path.join(root, ".EFAS")
    assert os.path.isdir(new) and not os.path.exists(old), (os.listdir(root))
    assert os.path.exists(os.path.join(new, "photo-edits.db")) and os.path.exists(os.path.join(new, "look-presets.json")) and os.path.exists(os.path.join(new, "app-settings.json"))
    assert not os.path.exists(os.path.join(new, "photoeditor.db"))
    assert win.controller.db_path == os.path.join(new, "photo-edits.db")
    assert win.controller._db.execute("SELECT COUNT(*) FROM edits").fetchone()[0] == 5
    import json
    assert json.load(open(os.path.join(new, "look-presets.json")))["presets"][0]["name"] == "Warm"
    win.close()
    print("FIRST START OK"); sys.stdout.flush(); os._exit(0)
''')


def _run(script, ok):
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", script], env=env, capture_output=True, text=True, timeout=300)
    assert ok in done.stdout, done.stdout[-1500:] + done.stderr[-4000:]


def test_uninstall_dialog_and_menu():
    _run(_DIALOG, "UNINSTALL UI OK")


def test_first_start_of_the_new_version_moves_the_old_folder():
    _run(_FIRST_START, "FIRST START OK")
