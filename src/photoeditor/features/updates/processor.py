"""The network and file side of updating: ask GitHub for the latest release, download it, swap the .exe and restart.

This is the only place the app talks to the internet. It makes a plain GET to api.github.com when checking and, if you accept an update,
to the release download on github.com. Nothing about you or your photos is sent.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from typing import Callable

from .logic import LATEST_API, Release, pick_release, trusted_url

_USER_AGENT = "EFAS-Negative-Inversion-Software"
_CHUNK = 256 * 1024


class UpdateError(Exception):
    """A problem worth showing the user as is."""


def fetch_latest(timeout: float = 6.0) -> Release | None:
    request = urllib.request.Request(LATEST_API, headers={"Accept": "application/vnd.github+json", "User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read(2_000_000).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise UpdateError(f"GitHub answered with an error ({exc.code}).") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpdateError("Could not reach GitHub. Check your internet connection.") from exc
    return pick_release(data)


def can_self_update() -> bool:
    """Only the packaged Windows .exe replaces itself; a source checkout is updated with git or a fresh download."""
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32" and os.access(os.path.dirname(sys.executable), os.W_OK)


def download(release: Release, dest: str, progress: Callable[[int, int], None] | None = None, cancelled: Callable[[], bool] | None = None) -> str:
    """Download the release's .exe to `dest`, checking its size and SHA-256 against what GitHub lists; returns `dest`."""
    if not release.asset_url or not trusted_url(release.asset_url):
        raise UpdateError("This release has no download the app can trust.")
    part = dest + ".part"
    digest = hashlib.sha256()
    done = 0
    try:
        request = urllib.request.Request(release.asset_url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=30) as response, open(part, "wb") as out:
            if not trusted_url(response.geturl()):
                raise UpdateError("The download was redirected somewhere untrusted, so it was stopped.")
            total = int(response.headers.get("Content-Length") or release.asset_size or 0)
            while True:
                if cancelled is not None and cancelled():
                    raise UpdateError("Cancelled.")
                chunk = response.read(_CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)
        if release.asset_size and done != release.asset_size:
            raise UpdateError("The download is incomplete. Try again.")
        if release.sha256 and digest.hexdigest() != release.sha256:
            raise UpdateError("The download does not match GitHub's checksum, so it was discarded.")
        os.replace(part, dest)
    except UpdateError:
        _remove(part)
        raise
    except (urllib.error.URLError, OSError) as exc:
        _remove(part)
        raise UpdateError(f"The download failed: {exc}") from exc
    return dest


def staging_path(release: Release) -> str:
    """Where the new .exe is saved: beside the running one, so swapping it in is a rename on the same drive."""
    return os.path.join(os.path.dirname(sys.executable), f"update-{release.tag}.exe.new")


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def cleanup_leftovers() -> None:
    """Remove the previous version and any unused download left beside the .exe by an update."""
    if not getattr(sys, "frozen", False):
        return
    folder = os.path.dirname(sys.executable)
    _remove(sys.executable + ".old")
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        if name.startswith("update-") and (name.endswith(".exe.new") or name.endswith(".exe.new.part")):
            _remove(os.path.join(folder, name))


def _script(target: str, new: str) -> str:
    t, n = target.replace("%", "%%"), new.replace("%", "%%")
    return (
        "@echo off\r\n"
        f'set "TARGET={t}"\r\nset "NEW={n}"\r\nset "OLD=%TARGET%.old"\r\nset tries=0\r\n'
        "ping 127.0.0.1 -n 3 >nul\r\n"
        ":swap\r\nset /a tries+=1\r\n"
        'if exist "%OLD%" del /f /q "%OLD%" >nul 2>&1\r\n'
        'move /y "%TARGET%" "%OLD%" >nul 2>&1\r\n'
        "if errorlevel 1 (\r\n  if %tries% geq 60 goto fail\r\n  ping 127.0.0.1 -n 2 >nul\r\n  goto swap\r\n)\r\n"
        'move /y "%NEW%" "%TARGET%" >nul 2>&1\r\n'
        'if errorlevel 1 (\r\n  move /y "%OLD%" "%TARGET%" >nul 2>&1\r\n  goto fail\r\n)\r\n'
        'start "" "%TARGET%"\r\n'
        "ping 127.0.0.1 -n 4 >nul\r\n"
        'del /f /q "%OLD%" >nul 2>&1\r\n'
        "goto end\r\n"
        ':fail\r\nif exist "%TARGET%" start "" "%TARGET%"\r\n'
        ':end\r\n(goto) 2>nul & del "%~f0"\r\n'
    )


def start_swap(new_exe: str) -> None:
    """Start the helper that, once this process has quit, puts `new_exe` in place of the running .exe and opens it. Quit the app right after."""
    script = os.path.join(tempfile.gettempdir(), f"efas-update-{os.getpid()}.cmd")
    with open(script, "w", encoding="mbcs", newline="") as f:
        f.write(_script(sys.executable, new_exe))
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(["cmd.exe", "/c", script], env=env, creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
