"""Extra > Check My Scanning Light in the window: the menu entry, choosing photos, running both checks in the background on made-up sensor data, the answer, the table, the picture of
what was measured, and saving the report."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
TESTS = str(Path(__file__).resolve().parent)

_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    sys.path.insert(0, os.environ["TESTS_DIR"])
    import _lightcheck_synth as syn
    from PyQt6.QtWidgets import QApplication, QFileDialog
    from photoeditor.features.lightcheck import capture
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    work = tempfile.mkdtemp()
    for i in range(4):
        open(os.path.join(work, f"scan{i}.ARW"), "wb").write(b"x")
    open(os.path.join(work, "scan0.JPG"), "wb").write(b"x")
    GOOD = (0.45, 0.16, 0.07)
    mode = {"m": "bare"}
    def fake_planes(path):
        i = int(os.path.basename(path)[4])
        if mode["m"] == "bare":
            return syn.bare_light([0.5, 0.48, 0.46, 0.455][i], bg=[1.0, 1.01, 1.02, 1.03][i], seed=i)
        return syn.negative(base=GOOD, light=[1.0, 1.0, 0.75, 1.0][i], seed=i)
    def fake_exif(path):
        i = int(os.path.basename(path)[4])
        return syn.exif(minute=[0, 5, 10, 15][i])
    capture.load_planes, capture.read_exif = fake_planes, fake_exif   # the worker looks these up when it runs

    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view.light_check_dialog import LightCheckDialog
    win = aw.AppWindow()

    # --- the menu entry opens the dialog once
    from PyQt6.QtWidgets import QMenu
    menus = [o.title().replace("&", "") for o in win._light_check_action.associatedObjects() if isinstance(o, QMenu)]
    assert menus == ["Extra"] and win._light_check_action.text() == "Check My Scanning Light...", menus
    win._filmstrip_folder = work
    win.show_light_check()
    d = win._light_check
    assert isinstance(d, LightCheckDialog) and d.isVisible() and d._start_folder == work
    win.show_light_check(); assert win._light_check is d, "a second click brings the same window forward"

    def wait():
        end = time.time() + 60
        while d._worker is not None and time.time() < end:
            app.processEvents(); time.sleep(0.02)
        app.processEvents(); app.processEvents()
        assert d._worker is None, "the check finished"

    # --- nothing chosen: the button is off; one photo is not enough
    assert not d.run_button.isEnabled() and d.current_mode() == "bare" and not d.reference.isVisible()
    d.set_files([os.path.join(work, "scan0.ARW")]); assert not d.run_button.isEnabled() and "at least two" in d.chosen.text()

    # --- the bare-light check
    d.set_files([work])
    assert d.run_button.isEnabled() and "4 RAW photos" in d.chosen.text(), d.chosen.text()   # the .JPG is not a RAW photo
    d.start(); wait()
    res = d.result
    assert res is not None and len(res.shots) == 4 and d.answer.isVisible() and d.save_button.isEnabled()
    labels = [d.findings.item(r, 0).text() for r in range(d.findings.rowCount())]
    assert labels == ["Brightness", "Colour", "Evenness", "Same settings", "Blown out"], labels
    assert d.findings.item(0, 1).text() == "CHANGED" and "dimmer" in d.findings.item(0, 2).text()
    assert "warm up" in d.bottom.text()
    assert d.shots.rowCount() == 4 and d.shots.columnCount() == 8 and d.shots.item(1, 1).text() == "scan1.ARW" and d.shots.item(3, 2).text() == "15.0"
    assert d.report.toPlainText().startswith("LIGHT CHECK") and d.tabs.count() == 3
    charts = d.charts_area.widget()
    assert charts is not None and charts.layout().count() >= 4
    assert not d.todo.isVisible()

    # --- saving writes the report and the numbers beside it, and never overwrites without asking the file dialog
    out = os.path.join(work, "report.txt")
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (out, ""))
    d.save_report()
    assert open(out, encoding="utf-8").read().startswith("LIGHT CHECK") and open(os.path.join(work, "report.csv"), encoding="utf-8").read().startswith("index,file,capture_time")
    assert "Saved report.txt" in d.status.text()
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
    os.remove(out); d.save_report(); assert not os.path.exists(out), "Cancel writes nothing"

    # --- switching to the film check clears the old answer and offers a reference scan
    d.mode.setCurrentIndex(1)
    assert d.current_mode() == "film" and not d.answer.isVisible() and d.reference.isVisible() and d.result is None and not d.save_button.isEnabled()
    d.set_files([work]); mode["m"] = "film"
    assert [d.reference.itemText(i) for i in range(d.reference.count())] == ["First colour negative", "scan0.ARW", "scan1.ARW", "scan2.ARW", "scan3.ARW"]
    d.reference.setCurrentIndex(2)   # scan1 is the reference
    d.start(); wait()
    res = d.result
    assert res.ri == 1 and res.shots[2].notes, "the dimmer scan is worth a look"
    assert d.findings.item(0, 0).text() == "Light brightness" and d.findings.item(0, 1).text() == "CHECK"
    assert d.todo.isVisible() and d.todo.text().startswith("What to do:")
    assert d.shots.columnCount() == 10 and d.shots.item(1, 1).text() == "scan1.ARW (reference)" and "brightness" in d.shots.item(2, 9).text()
    assert d.shots.currentRow() == 1 or d.shots.selectionModel().selectedRows()[0].row() == 1, "the reference is selected"
    d.shots.selectRow(2); app.processEvents()
    assert d.measured._image is not None and "scan2.ARW" in d.measured._text and d.measured._image.width() == 45 * 4
    assert d.report.toPlainText().startswith("FILM SCAN CHECK")

    # --- a file that is not a RAW capture is reported, not a crash
    capture.load_planes = lambda p: (_ for _ in ()).throw(capture.CaptureError("scan2.ARW could not be read as a RAW file (test)."))
    d.start(); wait()
    assert "could not be read" in d.status.text() and d.run_button.isEnabled()

    # --- Stop
    mode["m"] = "bare"; d.mode.setCurrentIndex(0); d.set_files([work])
    def slow(path):
        time.sleep(0.4); return fake_planes(path)
    capture.load_planes = slow
    d.start(); app.processEvents(); d.stop(); wait()
    assert d.status.text() == "Stopped." and d.result is None
    d.close()
    print("OK")
''')


def test_light_check_dialog_in_the_window():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""), TESTS_DIR=TESTS, PHOTOEDITOR_GPU="off")
    done = subprocess.run([sys.executable, "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0 and "OK" in done.stdout, (done.stdout[-1500:], done.stderr[-3000:])
