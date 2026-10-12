"""Where the app keeps its own files (databases, backups, presets, settings, thumbnails) and what each one is called - no Qt imports.

Everything lives in one folder, ~/.EFAS. Versions before 0.6 used ~/.photoeditor with vaguer file names; the first start of a newer version moves
everything across by itself and removes the old folder (see persistence/migrate.py)."""

import glob
import os
import threading

FOLDER_NAME = ".EFAS"
OLD_FOLDER_NAME = ".photoeditor"

# What is in the folder (new name on the left, what older versions called it in the comment)
EDITS_DB = "photo-edits.db"                       # photoeditor.db
LIBRARY_INDEX_DB = "workbench-index.db"           # library_index.db
BACKUP_DIR = "database-backups"                   # backups
BACKUP_PREFIX = "photo-edits-"                    # photoeditor-  (photo-edits-YYYY-MM-DD.db)
BEST_BACKUP = "photo-edits-best.db"               # photoeditor-best.db
SETTINGS_FILE = "app-settings.json"               # settings.json
LAYOUT_FILE = "window-and-panel-layout.ini"       # qsettings.ini
SESSION_FILE = "last-session.json"                # session.json
RECENTS_FILE = "recent-folders.json"              # recents.json
REMEMBERED_METADATA_FILE = "remembered-metadata.json"   # metadata_sticky.json
GEAR_PRESETS_FILE = "camera-and-lens-presets.json"      # presets.json
LOOK_PRESETS_FILE = "look-presets.json"           # look_presets.json
MODULE_PRESETS_FILE = "module-presets.json"       # module_presets.json
FONT_CACHE_FILE = "font-list-cache.json"          # fonts.json
GEAR_DIR = "camera-and-lens-lists"                # gear
FILM_PROFILES_DIR = "film-profiles"               # film_profiles
CAMERA_SETUPS_DIR = "camera-setups"               # camera_setups
AI_DUST_CACHE_DIR = "ai-dust-cache"               # ai_dust_cache
LOG_DIR = "logs"                                  # logs
RESTORE_PENDING_DIR = "restore-pending"           # restore_pending
THUMBNAIL_DIR = "thumbnail-cache"                 # (the system's cache folder)
IMPORT_RECORD_FILE = "imported-from-older-folders.json"   # consolidated.json
LEGACY_MERGED_FILE = "merged-older-databases.json"        # legacy_merged.json
MIGRATION_RECORD_FILE = "moved-from-old-version.json"

# Older names -> current names, for the files and folders that sit directly in the data folder
RENAMED = {
    "photoeditor.db": EDITS_DB,
    "library_index.db": LIBRARY_INDEX_DB,
    "backups": BACKUP_DIR,
    "settings.json": SETTINGS_FILE,
    "qsettings.ini": LAYOUT_FILE,
    "session.json": SESSION_FILE,
    "recents.json": RECENTS_FILE,
    "metadata_sticky.json": REMEMBERED_METADATA_FILE,
    "presets.json": GEAR_PRESETS_FILE,
    "look_presets.json": LOOK_PRESETS_FILE,
    "module_presets.json": MODULE_PRESETS_FILE,
    "fonts.json": FONT_CACHE_FILE,
    "gear": GEAR_DIR,
    "film_profiles": FILM_PROFILES_DIR,
    "camera_setups": CAMERA_SETUPS_DIR,
    "ai_dust_cache": AI_DUST_CACHE_DIR,
    "restore_pending": RESTORE_PENDING_DIR,
    "consolidated.json": IMPORT_RECORD_FILE,
    "legacy_merged.json": LEGACY_MERGED_FILE,
}
OLD_BACKUP_PREFIX = "photoeditor-"
_OLD_NAME = "PhotoEditor"
_OLD_LAUNCH_NAMES = ("Python", "python", "pythonw", "Ethans Editing App", "PhotoEditor Beta", "photoeditor")
_OLD_DB_NAME = "photoeditor.db"

_lock = threading.RLock()
_checked: set[str] = set()
last_move: dict | None = None  # what moving an old data folder did in this run (for the log); None when there was nothing to move
_moving: set[str] = set()


def new_name(old: str) -> str:
    """What a file or folder of an older version is called now (unchanged if it was never renamed). Works for a single name, not a path."""
    if old in RENAMED:
        return RENAMED[old]
    if old.startswith(OLD_BACKUP_PREFIX) and old.endswith(".db"):
        return BACKUP_PREFIX + old[len(OLD_BACKUP_PREFIX):]
    return old


def home_folder() -> str:
    return os.path.join(os.path.expanduser("~"), FOLDER_NAME)


def old_home_folder() -> str:
    return os.path.join(os.path.expanduser("~"), OLD_FOLDER_NAME)


def app_data_dir() -> str:
    """PHOTOEDITOR_DATA_DIR overrides it (tests); otherwise ~/.EFAS, the same for every way of launching. The first call in a process moves an older
    version's data across (nothing else writes to the folder before that has finished)."""
    override = os.environ.get("PHOTOEDITOR_DATA_DIR")
    if override:
        return override
    path = home_folder()
    if path not in _checked:
        with _lock:
            if path not in _checked and path not in _moving:
                _moving.add(path)
                try:
                    from .persistence import migrate

                    global last_move
                    last_move = migrate.run_if_needed(path)
                except Exception:
                    last_move = {"problems": [_failure_text()]}
                finally:
                    _moving.discard(path)
                    _checked.add(path)
    return path


def _failure_text() -> str:
    import traceback

    return traceback.format_exc()


def _roaming() -> str:
    return os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")


def _holds_data(path: str) -> bool:
    """The PhotoEditor folders always count; a folder named after a launcher only when it has the app's database in it."""
    return os.path.basename(path) == _OLD_NAME or os.path.isfile(os.path.join(path, _OLD_DB_NAME))


def legacy_data_dirs() -> list[str]:
    """Folders earlier versions kept data in that exist now, other than the current one: AppData\\Roaming\\PhotoEditor as this process sees it,
    every packaged app's private copy of it, and the per-launcher folders from before there was a fixed one. The files in them have the old names."""
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
