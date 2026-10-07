"""Where the app keeps its own files (database, backups, presets, settings) - no Qt imports.

The folder is `~/.photoeditor`, deliberately NOT under AppData. Programs started from a packaged ("Store"/MSIX) app - Claude's desktop app is one -
and their children get a private copy of AppData: what they write there is invisible to a program started normally, and the other way round. The
editor then showed two different sets of edits depending on how it was launched, and the "reset" the user saw was simply the other copy.
Everywhere outside AppData both kinds of program see the same files, so one folder there cannot split in two.

`legacy_data_dirs()` lists the places earlier versions kept data (AppData, as each launcher sees it, and every package's private copy of it);
features/persistence/consolidate.py merges them into the one folder, now and again whenever one of them has something new."""

import glob
import os

FOLDER_NAME = ".photoeditor"
_OLD_NAME = "PhotoEditor"  # the folder earlier versions used inside AppData\Roaming
_OLD_LAUNCH_NAMES = ("Python", "python", "pythonw", "Ethans Fuckass Editing App", "Ethans Editing App", "PhotoEditor Beta", "photoeditor")


def app_data_dir() -> str:
    """PHOTOEDITOR_DATA_DIR overrides it (tests); otherwise one fixed folder in the user's home, the same for every way of launching."""
    override = os.environ.get("PHOTOEDITOR_DATA_DIR")
    if override:
        return override
    return os.path.join(os.path.expanduser("~"), FOLDER_NAME)


def _roaming() -> str:
    return os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")


def legacy_data_dirs() -> list[str]:
    """Folders earlier versions kept data in that exist now, other than the current one: AppData\\Roaming\\PhotoEditor as this process sees it,
    every packaged app's private copy of it, and the per-launcher folders from before there was a fixed one."""
    local = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    roaming = _roaming()
    candidates = [os.path.join(roaming, _OLD_NAME)]
    candidates += sorted(glob.glob(os.path.join(local, "Packages", "*", "LocalCache", "Roaming", _OLD_NAME)))
    candidates += [os.path.join(roaming, name) for name in _OLD_LAUNCH_NAMES]
    current = os.path.normcase(os.path.abspath(app_data_dir()))
    seen, out = set(), []
    for path in candidates:
        key = os.path.normcase(os.path.abspath(path))
        if key != current and key not in seen and os.path.isdir(path):
            seen.add(key)
            out.append(path)
    return out
