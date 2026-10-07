"""Where the app keeps its own files (database, backups, presets, settings) - no Qt imports."""

import glob
import os

FOLDER_NAME = ".photoeditor"
_OLD_NAME = "PhotoEditor"
_OLD_LAUNCH_NAMES = ("Python", "python", "pythonw", "Ethans Editing App", "PhotoEditor Beta", "photoeditor")
_DB_NAME = "photoeditor.db"


def app_data_dir() -> str:
    """PHOTOEDITOR_DATA_DIR overrides it (tests); otherwise one fixed folder in the user's home, the same for every way of launching."""
    override = os.environ.get("PHOTOEDITOR_DATA_DIR")
    if override:
        return override
    return os.path.join(os.path.expanduser("~"), FOLDER_NAME)


def _roaming() -> str:
    return os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")


def _holds_data(path: str) -> bool:
    """The PhotoEditor folders always count; a folder named after a launcher only when it has the app's database in it."""
    return os.path.basename(path) == _OLD_NAME or os.path.isfile(os.path.join(path, _DB_NAME))


def legacy_data_dirs() -> list[str]:
    """Folders earlier versions kept data in that exist now, other than the current one: AppData\\Roaming\\PhotoEditor as this process sees it,
    every packaged app's private copy of it, and the per-launcher folders from before there was a fixed one."""
    local = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    roaming = _roaming()
    candidates = [os.path.join(roaming, _OLD_NAME)]
    candidates += sorted(glob.glob(os.path.join(local, "Packages", "*", "LocalCache", "Roaming", _OLD_NAME)))
    candidates += [os.path.join(roaming, name) for name in _OLD_LAUNCH_NAMES]
    candidates += sorted(glob.glob(os.path.join(roaming, "Ethans * Editing App")))
    current = os.path.normcase(os.path.abspath(app_data_dir()))
    seen, out = set(), []
    for path in candidates:
        key = os.path.normcase(os.path.abspath(path))
        if key != current and key not in seen and os.path.isdir(path) and _holds_data(path):
            seen.add(key)
            out.append(path)
    return out
