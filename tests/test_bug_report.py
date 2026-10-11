"""The problem report: it strips personal paths, says what it holds, makes a zip, and builds a GitHub issue link without sending anything."""
import os
import subprocess
import sys
import textwrap
import threading
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from photoeditor.features.support import applog, report as R  # noqa: E402


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path / "data"))
    yield tmp_path / "data"
    applog.uninstall()


def test_paths_lose_their_folders_and_addresses_are_blanked():
    text = (r"Failed on C:\Users\Ethan\Pictures\Holiday 2026\IMG_0042.CR2 and /home/ethan/scans/roll 3/frame.tif, contact me@example.com. "
            r"Also D:\x\y.png.")
    out = R.redact(text)
    assert "Ethan" not in out and "ethan" not in out and "Holiday" not in out and "roll 3" not in out.replace("<folder>/frame.tif", "")
    assert "<folder>/IMG_0042.CR2" in out and "<folder>/frame.tif" in out and "<folder>/y.png" in out and "<email>" in out and "example.com" not in out
    assert R.redact("no paths here, ratio 3/4 and 1/2") == "no paths here, ratio 3/4 and 1/2"


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_the_log_records_errors_from_any_thread_and_keeps_going(data_dir):
    assert applog.install("9.9.9")
    assert applog.install("9.9.9"), "calling twice is harmless"
    hook_calls = []
    old = applog._old_hooks
    applog._old_hooks = (lambda *a: hook_calls.append(a), old[1])
    sys.excepthook(ValueError, ValueError("main thread trouble"), None)
    t = threading.Thread(target=lambda: 1 / 0, name="worker-x")
    t.start()
    t.join()
    for h in applog.logger().handlers:
        h.flush()
    text = "\n".join(applog.read_tail())
    assert "EFAS 9.9.9 started" in text and "main thread trouble" in text and "ZeroDivisionError" in text and "worker-x" in text
    assert hook_calls, "the original error handler still runs"
    applog._old_hooks = old


def test_the_log_is_trimmed_to_its_tail(data_dir):
    applog.install("1")
    for i in range(500):
        applog.logger().info("line %d", i)
    for h in applog.logger().handlers:
        h.flush()
    tail = applog.read_tail(50)
    assert len(tail) == 50 and tail[-1].endswith("line 499")


def test_a_report_holds_what_it_says_and_nothing_personal(data_dir):
    applog.install("1.2.3")
    applog.logger().warning("Export failed for %s: boom", r"C:\Users\Ethan\Pictures\Private Wedding\a.cr2")
    (data_dir / "settings.json").write_text('{"backup_dir": "C:\\\\Users\\\\Ethan\\\\Secret Backups", "advanced_mode": true, "keybinds": {"x": "Ctrl+Q"}}')
    r = R.build("1.2.3", "Export fails", "It crashed", "Click export", "A file")
    md = R.full_markdown(r)
    assert "It crashed" in md and "Click export" in md and "1.2.3" in md and "Python" in md and "PyQt6" in md
    for secret in ("Ethan", "Private Wedding", "Secret Backups", "Ctrl+Q"):
        assert secret not in md, secret
    assert "boom" in md and "<folder>/a.cr2" in md and '"advanced_mode": true' in md
    listing = " ".join(r.contents())
    assert "log" in listing and "preference" in listing and "Never included" in listing
    bare = R.build("1.2.3", "t", "w", include_log=False, include_settings=False, include_data=False)
    assert bare.log_lines is None and "### Log" not in R.full_markdown(bare) and "### Preferences" not in R.full_markdown(bare) and "log" not in " ".join(bare.contents()).lower().replace("never", "")


def test_the_zip_has_the_report_and_the_log_and_leaves_no_partial_file(data_dir, tmp_path):
    applog.install("1")
    r = R.build("1", "t", "what")
    path = R.write_zip(r, str(tmp_path / "out" / "report"))
    assert path.endswith(".zip") and not [f for f in os.listdir(tmp_path / "out") if f.endswith(".part")]
    with zipfile.ZipFile(path) as z:
        assert sorted(z.namelist()) == ["log.txt", "report.md"] and "what" in z.read("report.md").decode()


def test_the_issue_link_goes_to_the_projects_new_issue_page_with_the_text_filled_in(data_dir):
    r = R.build("1.2.3", "Crash on open", "It closed itself & lost my edit", "1. Open\n2. Click")
    url = R.issue_url(r, "EFAS problem report.zip")
    parts = urlparse(url)
    assert (parts.scheme, parts.netloc, parts.path) == ("https", "github.com", "/EthanChas/EFAS-Negative-Inversion-Software/issues/new")
    q = parse_qs(parts.query)
    assert q["title"] == ["Crash on open"] and "lost my edit" in q["body"][0] and "drag `EFAS problem report.zip`" in q["body"][0]
    assert "log" not in q["body"][0].lower().replace("drag", "") or "Log" not in q["body"][0]
    long = R.build("1", "t", "x" * 9000)
    assert len(R.issue_url(long)) < 9000, "long text is cut so the link still works"
    assert "title=Problem%20report" in R.issue_url(R.build("1", "", "only a description"))


_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    from PyQt6.QtWidgets import QApplication
    from PyQt6 import QtGui
    app = QApplication([])
    from photoeditor.desktop.view import bug_report_dialog as B

    opened = []
    QtGui.QDesktopServices.openUrl = staticmethod(lambda url: opened.append(url.toString()))
    B.QDesktopServices = QtGui.QDesktopServices
    dlg = B.BugReportDialog("0.4.0")
    assert not dlg.save_button.isEnabled() and not dlg.issue_button.isEnabled(), "nothing to send until something is written"
    dlg.title.setText("Thumbnails are black")
    dlg.what.setPlainText("The Workbench shows black tiles for RAW files.")
    assert dlg.save_button.isEnabled() and "Workbench shows black tiles" in dlg.preview.toPlainText()
    assert "Never included" in dlg.contents.toPlainText()
    dlg.log_box.setChecked(False)
    assert "### Log" not in dlg.preview.toPlainText() and "log" not in dlg.contents.toPlainText().lower().replace("never included: your photos, edits, tags, notes, roll cards or folder names", "")
    dlg.log_box.setChecked(True)
    out = os.path.join(work, "report.zip")
    assert dlg.save_report(out) == out and os.path.isfile(out)
    dlg.saved_path = ""
    import photoeditor.desktop.view.bug_report_dialog as mod
    mod.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (os.path.join(work, "again.zip"), ""))
    dlg.open_issue()
    assert os.path.isfile(os.path.join(work, "again.zip"))
    assert len(opened) == 1 and opened[0].startswith("https://github.com/EthanChas/EFAS-Negative-Inversion-Software/issues/new?")
    assert "again.zip" in dlg.status.text() and "Submit" in dlg.status.text()
    print("BUG REPORT UI OK")
''')


def test_the_report_dialog():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert "BUG REPORT UI OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3500:]
