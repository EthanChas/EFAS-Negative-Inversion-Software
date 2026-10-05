"""AppWindow must survive being shown at any size AND being left alive at interpreter exit.

Both run in a subprocess: the failure these guard against is a native access violation (no Python
frame) that kills the interpreter, and it happens *after* the script's last line - during
finalization - so only the child's exit code can see it. It was intermittent (~half of runs), hence
several concurrent children per check.
"""
import os
import subprocess
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")

# Isolated data dir + QSettings ini so the child never touches the user's real database or registry.
_PRELUDE = textwrap.dedent("""
    import os, sys, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    tmp = tempfile.mkdtemp()
    os.environ["PHOTOEDITOR_DATA_DIR"] = tmp
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication
    from photoeditor.desktop.view import crop_tool_panel, export_panel
    ini = os.path.join(tmp, "settings.ini")
    isolated = lambda *a, **k: QSettings(ini, QSettings.Format.IniFormat)
    export_panel.QSettings = isolated
    crop_tool_panel.QSettings = isolated
""")
_CREATE_APP = textwrap.dedent("""
    app = QApplication([])
    from photoeditor.desktop.view.app_window import AppWindow
""")


def _run(body: str, *, create_app: bool = True) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    code = _PRELUDE + (_CREATE_APP if create_app else "") + textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", code],
        env=env, capture_output=True, text=True, timeout=180,
    )


def _run_many(body: str, n: int, **kwargs) -> list[subprocess.CompletedProcess]:
    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(lambda _: _run(body, **kwargs), range(n)))


def test_exit_hook_destroys_windows_before_pyqt_cleanup():
    # Deterministic form of the crash check below. PyQt's own atexit cleanup deletes the windows too,
    # but too late (that is the crash), so the hook has to be the one that does it: spy on its delete.
    r = _run("""
        import atexit
        from photoeditor.desktop.view import app_window
        real_delete, deleted = app_window.sip.delete, []
        app_window.sip = type("SipSpy", (), {"delete": staticmethod(lambda obj: (deleted.append(obj), real_delete(obj)))})
        shown, unshown = AppWindow(), AppWindow()
        shown.show()
        app.processEvents()
        atexit._run_exitfuncs()
        print("hook deleted both" if len(deleted) == 2 else f"hook deleted {len(deleted)}", flush=True)
    """)
    assert "hook deleted both" in r.stdout, r.stdout + r.stderr
    assert r.returncode == 0, f"rc={r.returncode}:\n{r.stderr}"


@pytest.mark.parametrize(
    "setup, n",
    [
        ("w = AppWindow()", 12),  # never shown: the most sensitive shape (crashed ~1 run in 3 before the fix)
        ("w = AppWindow(); w.show(); app.processEvents()", 6),
        ("w = AppWindow(); w.resize(1500, 950); w.show(); app.processEvents()", 6),
    ],
    ids=["unshown", "shown-default-size", "shown-1500x950"],
)
def test_window_left_alive_at_interpreter_exit_does_not_crash(setup, n):
    # Deliberately never closes/deletes the window: module globals stay alive into finalization, which
    # used to end in an access violation (rc != 0) after the script's last line - at any size.
    results = _run_many(setup + '\nprint("done", flush=True)', n)
    for r in results:
        assert "done" in r.stdout, r.stderr
        assert r.returncode == 0, f"crashed at exit (rc={r.returncode}):\n{r.stderr}"


def test_window_shows_and_resizes_at_any_size():
    r = _run("""
        w = AppWindow()
        w.show()
        app.processEvents()
        for width, height in [(1, 1), (100, 100), (320, 200), (480, 360), (533, 360), (800, 600),
                              (1500, 950), (3840, 2160), (300, 2000), (2000, 300), (1500, 950), (1, 1)]:
            w.resize(width, height)
            app.processEvents()
            assert w.width() >= w.minimumWidth() and w.height() >= w.minimumHeight()
        w.showMaximized(); app.processEvents()
        w.showNormal(); app.processEvents()
        print("sizes ok", flush=True)
    """)
    assert "sizes ok" in r.stdout, r.stdout + r.stderr
    assert r.returncode == 0, f"rc={r.returncode}:\n{r.stderr}"


def test_real_entry_point_exits_cleanly():
    # photoeditor.__main__.main() end to end (app-wide stylesheet, maximized window, event loop, then
    # sys.exit). Its exit used to crash most of the time; the loop is told to quit shortly after start.
    results = _run_many("""
        from PyQt6.QtCore import QTimer
        import photoeditor.__main__ as entry
        real_exec = QApplication.exec
        def exec_then_quit():
            QTimer.singleShot(300, QApplication.instance().quit)
            return real_exec()
        QApplication.exec = staticmethod(exec_then_quit)
        entry.main()
    """, n=8, create_app=False)
    for r in results:
        assert r.returncode == 0, f"main() exited with rc={r.returncode}:\n{r.stderr}"
