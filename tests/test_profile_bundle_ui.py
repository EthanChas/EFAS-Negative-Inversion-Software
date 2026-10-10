"""Sharing and receiving a film profile through the Film Profiles dialog."""
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
    work = tempfile.mkdtemp()
    sys.path.insert(0, TESTS)
    from PyQt6.QtWidgets import QApplication, QMessageBox, QInputDialog, QFileDialog
    import test_film_profile as T
    from photoeditor.features.densitometry import film_profile as fp
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view import profile_dialogs as pdg

    win = aw.AppWindow(); c = win.controller
    store = c.profile_store()
    mine = T.make_profile(name="My roll"); store.save(mine)
    out = os.path.join(work, "shared.efasprofile")
    shown = []
    QMessageBox.information = staticmethod(lambda *a, **k: shown.append(a[2]))
    QMessageBox.warning = staticmethod(lambda *a, **k: shown.append(a[2]))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (out, ""))
    pdg._ask = lambda parent, title, fields: ["Sam", "Portra 160 on my lightbox"]
    dlg = pdg.ProfilesDialog(c)
    assert dlg.list.count() == 1 and dlg.buttons["share"].isEnabled()
    dlg._share()
    assert os.path.isfile(out) and "fingerprint" in shown[-1]

    # receiving: declining changes nothing, accepting adds a marked copy
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (out, ""))
    class Box:
        answer = QMessageBox.StandardButton.No
    ask_calls = []
    def fake_exec(self):
        ask_calls.append(self.text()); return Box.answer
    QMessageBox.exec = fake_exec
    dlg._import()
    assert dlg.list.count() == 1 and ask_calls and "Sam" in ask_calls[-1] and "does not show who made it" in ask_calls[-1]
    Box.answer = QMessageBox.StandardButton.Yes
    dlg._import()
    assert dlg.list.count() == 2
    ids = [r["id"] for r in store.list()]
    got = [store.load(i) for i in ids if i != mine.id]
    assert len(got) == 1 and got[0].kind == "supplied" and got[0].extras["received"]["author"] == "Sam"
    dlg._show()
    assert "Received from Sam" in dlg.detail.toPlainText()

    # a damaged bundle is refused with the reasons
    bad = os.path.join(work, "bad.efasprofile"); open(bad, "wb").write(b"junk")
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (bad, ""))
    dlg._import()
    assert dlg.list.count() == 2 and "failed its checks" in shown[-1]
    win.close()
    print("BUNDLE UI OK")
'''.replace("TESTS", repr(TESTS)))


def test_share_and_receive_a_profile_bundle():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert "BUNDLE UI OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3000:]
