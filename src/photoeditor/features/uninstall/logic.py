"""Uninstalling EFAS: what to delete, and the small script that does it once the app has closed - no Qt imports.

A running program cannot delete its own files (Windows will not let an exe be deleted while it runs, and the databases are open), so the app starts a
detached helper script and quits. The script waits for the app to exit, deletes what was asked for - trying again for a while if something is still
locked - and then deletes itself. If the app has not exited after a minute the script gives up and deletes nothing, so a close that was cancelled
cannot turn into a surprise deletion later."""

import os
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

from ..datadir import RENAMED, app_data_dir, home_folder, legacy_data_dirs, old_home_folder

REGISTRY_KEY = r"HKCU\Software\PhotoEditor"
WAIT_SECONDS = 60
RETRIES = 30
CONFIRM_WORD = "UNINSTALL"
_SYS32 = "%SystemRoot%" + chr(92) + "System32" + chr(92)
_PAUSE = f'"{_SYS32}ping.exe" -n 2 127.0.0.1 >nul'


# What older versions kept directly in a folder that may be shared with other programs (the per-launcher folders such as AppData\Roaming\Python,
# where Python itself keeps installed packages): only these files are ever deleted from such a folder, never the folder.
_SHARED_FOLDER_FILES = tuple(n for n, new in RENAMED.items() if "." in n) + ("photoeditor.db-wal", "photoeditor.db-shm")


@dataclass
class Plan:
    folders: list[str] = field(default_factory=list)  # folders that belong to EFAS entirely, deleted with everything in them
    files: list[str] = field(default_factory=list)    # EFAS's own files inside folders that also belong to other programs
    program: str | None = None
    clean_registry: bool = False

    def is_empty(self) -> bool:
        return not self.folders and not self.files and not self.program


def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def allowed_data_folders(extra_cache: list[str] | tuple[str, ...] = ()) -> list[str]:
    """Every folder the app has ever kept the user's data or caches in - and only those, whatever else is asked for."""
    out = [app_data_dir(), home_folder(), old_home_folder(), *legacy_data_dirs(), *extra_cache]
    seen, unique = set(), []
    for p in out:
        key = os.path.normcase(os.path.abspath(p))
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def _is_efas_folder(path: str) -> bool:
    """Is every file in this folder EFAS's? True for the data folders and the app's own named old ones; not for a folder named after a launcher."""
    name = os.path.basename(os.path.normpath(path))
    return name in (".EFAS", ".photoeditor", "PhotoEditor", "thumbnails", "thumbnail-cache") or (name.startswith("Ethans ") and name.endswith(" Editing App")) or (bool(os.environ.get("PHOTOEDITOR_DATA_DIR")) and _same(path, os.environ["PHOTOEDITOR_DATA_DIR"]))


def data_folders(extra_cache: list[str] | tuple[str, ...] = ()) -> list[str]:
    """The data folders that exist right now and belong to EFAS entirely."""
    return [p for p in allowed_data_folders(extra_cache) if os.path.isdir(p) and _is_efas_folder(p)]


def shared_folder_files() -> list[str]:
    """EFAS's own old files in folders it shared with other programs, that exist right now (listed so the user can be told about them)."""
    out = []
    for folder in allowed_data_folders():
        if not os.path.isdir(folder) or _is_efas_folder(folder):
            continue
        for name in _SHARED_FOLDER_FILES:
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                out.append(path)
        backups = os.path.join(folder, "backups")
        if os.path.isdir(backups):
            out += [os.path.join(backups, f) for f in os.listdir(backups) if f.startswith("photoeditor-") and f.endswith(".db")]
    return out


def program_path() -> str | None:
    """The file the user started EFAS from (the exe; on a Mac the .app that holds it); None when running from source, where there is no program to delete."""
    if not getattr(sys, "frozen", False):
        return None
    exe = os.path.abspath(sys.executable)
    if not os.path.isfile(exe):
        return None
    parts = exe.split(os.sep)
    for i, part in enumerate(parts):
        if part.lower().endswith(".app") and sys.platform == "darwin":
            return os.sep.join(parts[: i + 1])
    return exe


def make_plan(delete_data: bool, delete_program: bool, extra_cache: list[str] | tuple[str, ...] = ()) -> Plan:
    plan = Plan()
    if delete_data:
        plan.folders = data_folders(extra_cache)
        plan.files = shared_folder_files()
        plan.clean_registry = sys.platform.startswith("win")
    if delete_program:
        plan.program = program_path()
    return plan


def _bat_quote(path: str) -> str:
    return '"' + path.replace("%", "%%") + '"'


def windows_script(plan: Plan, pid: int, wait: int = WAIT_SECONDS, retries: int = RETRIES) -> str:
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        "set N=0",
        ":waitexit",
        f'"{_SYS32}tasklist.exe" /FI "PID eq {pid}" /FO CSV /NH 2>nul | "{_SYS32}find.exe" """{pid}""" >nul',
        "if errorlevel 1 goto gone",
        "set /a N=N+1",
        f"if %N% GEQ {wait} goto giveup",
        _PAUSE,
        "goto waitexit",
        ":gone",
    ]
    targets = [(p, "rmdir /s /q") for p in plan.folders] + [(p, "del /f /q") for p in plan.files]
    if plan.program:
        targets.append((plan.program, "rmdir /s /q" if os.path.isdir(plan.program) else "del /f /q"))
    for i, (path, command) in enumerate(targets):
        q = _bat_quote(path)
        lines += [
            "set N=0",
            f":again{i}",
            f"if not exist {q} goto next{i}",
            f"{command} {q} >nul 2>&1",
            f"if not exist {q} goto next{i}",
            "set /a N=N+1",
            f"if %N% GEQ {retries} goto next{i}",
            _PAUSE,
            f"goto again{i}",
            f":next{i}",
        ]
    if plan.clean_registry:
        lines.append(f'"{_SYS32}reg.exe" delete "{REGISTRY_KEY}" /f >nul 2>&1')
    lines += [":giveup", '(goto) 2>nul & del "%~f0"']
    return "\r\n".join(lines) + "\r\n"


def posix_script(plan: Plan, pid: int, wait: int = WAIT_SECONDS, retries: int = RETRIES) -> str:
    lines = [
        "#!/bin/sh",
        f"PID={int(pid)}",
        "n=0",
        'while kill -0 "$PID" 2>/dev/null; do',
        "  n=$((n+1))",
        f"  [ $n -ge {wait} ] && {{ rm -f -- \"$0\"; exit 0; }}",
        "  sleep 1",
        "done",
    ]
    targets = list(plan.folders) + list(plan.files) + ([plan.program] if plan.program else [])
    for path in targets:
        q = shlex.quote(path)
        lines += [
            "n=0",
            f"while [ -e {q} ] && [ $n -lt {retries} ]; do",
            f"  rm -rf -- {q} 2>/dev/null",
            f"  [ -e {q} ] && sleep 1",
            "  n=$((n+1))",
            "done",
        ]
    lines.append('rm -f -- "$0"')
    return "\n".join(lines) + "\n"


def write_script(plan: Plan, pid: int, wait: int = WAIT_SECONDS, retries: int = RETRIES) -> str:
    """Write the helper script to a temporary file and return its path."""
    windows = sys.platform.startswith("win")
    fd, path = tempfile.mkstemp(prefix="efas-uninstall-", suffix=".bat" if windows else ".sh")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write(windows_script(plan, pid, wait, retries) if windows else posix_script(plan, pid, wait, retries))
    if not windows:
        os.chmod(path, 0o700)
    return path


def launch(plan: Plan, pid: int | None = None, wait: int = WAIT_SECONDS, retries: int = RETRIES) -> str:
    """Start the helper, detached from this process, and return the script's path. The caller then quits the app."""
    if plan.is_empty():
        raise ValueError("There is nothing to uninstall.")
    script = write_script(plan, os.getpid() if pid is None else pid, wait, retries)
    if sys.platform.startswith("win"):
        # A hidden console of its own (the helper's pipes and ping need one), outside the app's process group, and - when allowed - outside any job
        # object the app was started in, so it outlives the app.
        base = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        for flags in (base | subprocess.CREATE_BREAKAWAY_FROM_JOB, base):
            try:
                subprocess.Popen(["cmd.exe", "/c", script], creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break
            except OSError:
                if flags == base:
                    raise
    else:
        subprocess.Popen(["/bin/sh", script], start_new_session=True, close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return script
