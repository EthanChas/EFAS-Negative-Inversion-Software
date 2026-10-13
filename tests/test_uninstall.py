"""Uninstall EFAS: the helper script deletes the data folders and the program after the app has exited, and only then; and it only deletes what it was told."""
import os
import subprocess
import sys
import time

import pytest

from photoeditor.features.uninstall import logic as un


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Point the places the uninstaller looks at into tmp_path, so a test can never go near the real ones."""
    new, old = tmp_path / "home" / ".EFAS", tmp_path / "home" / ".photoeditor"
    monkeypatch.setattr(un, "home_folder", lambda: str(new))
    monkeypatch.setattr(un, "old_home_folder", lambda: str(old))
    monkeypatch.setattr(un, "legacy_data_dirs", lambda: [])
    monkeypatch.setattr(un, "app_data_dir", lambda: str(new))
    return new, old


def fill(folder, name="data.db"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(b"x" * 100)
    sub = folder / "database-backups"
    sub.mkdir(exist_ok=True)
    (sub / "photo-edits-2026-01-01.db").write_bytes(b"y")


def wait_until(cond, secs=40.0):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return cond()


def sleeper(secs):
    return subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({secs})"])


def test_plan_lists_only_known_data_folders(isolated, tmp_path):
    new, old = isolated
    fill(new)
    stray = tmp_path / "Documents"
    stray.mkdir()
    plan = un.make_plan(True, False, extra_cache=[str(tmp_path / "cache" / "thumbnails")])
    assert plan.folders == [str(new)], "only folders that exist, and never anything the app does not own"
    assert plan.program is None
    fill(old)
    assert un.make_plan(True, False).folders == [str(new), str(old)], "an old folder left behind goes too"
    assert un.make_plan(False, False).is_empty()
    assert un.make_plan(False, False).folders == []


def test_running_from_source_has_no_program_to_delete(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert un.program_path() is None
    assert un.make_plan(False, True).program is None


def test_a_frozen_exe_is_the_program(tmp_path, monkeypatch):
    exe = tmp_path / "EFAS Negative Inversion Software.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert un.program_path() == str(exe)
    assert un.make_plan(False, True).program == str(exe)


def test_script_text_is_safe_with_odd_paths(tmp_path):
    plan = un.Plan(folders=[str(tmp_path / "100% data & stuff")], program=str(tmp_path / "it's (a) test.exe"))
    win = un.windows_script(plan, 1234)
    assert "100%% data & stuff" in win and "tasklist" in win and 'del "%~f0"' in win and "1234" in win
    posix = un.posix_script(plan, 1234)
    assert "kill -0" in posix and "'" in posix and "rm -f -- \"$0\"" in posix
    with pytest.raises(ValueError):
        un.launch(un.Plan())


def test_the_script_deletes_everything_once_the_app_has_exited(isolated, tmp_path):
    new, old = isolated
    fill(new)
    fill(old)
    exe = tmp_path / "program" / "EFAS.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    keep = tmp_path / "photos"
    keep.mkdir()
    (keep / "picture.jpg").write_bytes(b"photo")
    (keep / "picture.jpg.xmp").write_bytes(b"sidecar")
    plan = un.make_plan(True, False)
    plan.program = str(exe)
    app = sleeper(3)
    script = un.launch(plan, app.pid)
    time.sleep(0.5)
    assert new.exists() and exe.exists(), "nothing is touched while the app is still running"
    assert wait_until(lambda: not new.exists() and not old.exists() and not exe.exists() and not os.path.exists(script)), (new.exists(), old.exists(), exe.exists(), os.path.exists(script))
    app.wait()
    assert not os.path.exists(script + ".pid"), "the helper leaves nothing behind"
    assert (keep / "picture.jpg").exists() and (keep / "picture.jpg.xmp").exists(), "photos and their sidecars are never touched"
    assert exe.parent.exists(), "only the program file goes, not the folder it sat in"


def test_only_the_program_when_the_data_is_kept(isolated, tmp_path):
    new, _old = isolated
    fill(new)
    exe = tmp_path / "EFAS.exe"
    exe.write_bytes(b"MZ")
    plan = un.make_plan(False, False)
    plan.program = str(exe)
    app = sleeper(1)
    script = un.launch(plan, app.pid)
    assert wait_until(lambda: not exe.exists() and not os.path.exists(script))
    assert new.exists() and (new / "data.db").exists()
    app.wait()


def test_a_locked_file_is_retried_until_it_is_free(isolated, tmp_path):
    new, _old = isolated
    fill(new)
    holder = subprocess.Popen([sys.executable, "-c", f"import time; f = open(r'{new / 'data.db'}', 'rb'); time.sleep(4)"])
    time.sleep(0.8)
    app = sleeper(1)
    script = un.launch(un.make_plan(True, False), app.pid)
    assert wait_until(lambda: not new.exists() and not os.path.exists(script), 60), "deleted once the other process let go"
    holder.wait(); app.wait()


def test_it_gives_up_and_deletes_nothing_if_the_app_never_exits(isolated, tmp_path):
    new, _old = isolated
    fill(new)
    app = sleeper(12)
    script = un.launch(un.make_plan(True, False), app.pid, wait=2)
    assert wait_until(lambda: not os.path.exists(script), 30), "the helper ends"
    assert new.exists() and (new / "data.db").exists(), "a close that was cancelled never turns into a deletion"
    app.kill(); app.wait()


def test_a_folder_shared_with_other_programs_only_loses_efass_own_files(isolated, tmp_path, monkeypatch):
    """AppData/Roaming/Python is where Python keeps its installed packages; an older version that was started through python left its database there."""
    new, _old = isolated
    fill(new)
    roaming = tmp_path / "Roaming"
    shared = roaming / "Python"
    packages = shared / "Python313" / "site-packages"
    packages.mkdir(parents=True)
    (packages / "some_package.py").write_text("keep")
    (shared / "photoeditor.db").write_bytes(b"old db")
    (shared / "session.json").write_text("{}")
    (shared / "backups").mkdir()
    (shared / "backups" / "photoeditor-2026-01-01.db").write_bytes(b"b")
    (shared / "backups" / "someone-elses.db").write_bytes(b"keep")
    (shared / "unrelated.txt").write_text("keep")
    ours = roaming / "PhotoEditor"
    fill(ours, "photoeditor.db")
    monkeypatch.setattr(un, "legacy_data_dirs", lambda: [str(shared), str(ours)])
    plan = un.make_plan(True, False)
    assert str(shared) not in plan.folders and str(ours) in plan.folders and str(new) in plan.folders
    assert sorted(os.path.basename(f) for f in plan.files) == ["photoeditor-2026-01-01.db", "photoeditor.db", "session.json"]
    app = sleeper(1)
    script = un.launch(plan, app.pid)
    assert wait_until(lambda: not new.exists() and not ours.exists() and not os.path.exists(script))
    app.wait()
    assert (packages / "some_package.py").read_text() == "keep" and (shared / "unrelated.txt").exists() and (shared / "backups" / "someone-elses.db").exists()
    assert not (shared / "photoeditor.db").exists() and not (shared / "session.json").exists() and not (shared / "backups" / "photoeditor-2026-01-01.db").exists()


def test_the_wait_loop_uses_no_pipe():
    """A pipe between tasklist and find can hang a detached script for ever (it did, once, and flashed a console window every second): the check reads a file."""
    text = un.windows_script(un.Plan(folders=["C:/x"]), 1234)
    waiting = text.split(":gone")[0]
    assert "|" not in waiting and '"%~f0.pid"' in waiting


def test_the_posix_helper_does_not_wait_for_a_process_that_has_already_exited():
    """A process that has exited but has not been collected by its parent still answers kill -0 (it is a zombie): the helper must treat it as gone, or it gives up after
    its waiting time and deletes nothing."""
    text = un.posix_script(un.Plan(folders=["/tmp/x"]), 4242)
    assert 'ps -o stat= -p "$PID"' in text and "Z*) break" in text
    assert text.index("Z*) break") < text.index("sleep 1"), "checked inside the waiting loop, before it sleeps"
