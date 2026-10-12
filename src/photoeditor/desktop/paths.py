import os
import shutil

from PyQt6.QtCore import QStandardPaths

from ..features.datadir import THUMBNAIL_DIR, app_data_dir  # noqa: F401  (re-exported: the controller imports it from here)

_moved = False

# The cache folders older builds used, named for whatever the program was called when it ran (python.exe while run from source, the app's
# own name, or the names it had before): each held "<name>/cache/thumbnails" under the system's local-app-data folder.
_OLD_CACHE_OWNERS = (
    "python", "pythonw", "PhotoEditor", "Ethans Fuckass Editing App", "EFAS-Negative-Inversion-Software-v0", "EFAS Negative Inversion Software",
)


def system_thumbnail_dir() -> str:
    """Where older versions kept the thumbnail cache: the system's cache folder for the app."""
    return os.path.join(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation), "thumbnails")


def old_thumbnail_dirs() -> list[str]:
    """Every folder an earlier version may have left the thumbnail cache in (the ones that exist)."""
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericCacheLocation)
    if os.path.basename(os.path.normpath(base)).lower() == "cache":
        base = os.path.dirname(os.path.normpath(base))  # GenericCacheLocation can be ".../AppData/Local/cache" on Windows
    found = [system_thumbnail_dir(), *(os.path.join(base, owner, "cache", "thumbnails") for owner in _OLD_CACHE_OWNERS)]
    out, seen = [], set()
    for p in found:
        key = os.path.normcase(os.path.abspath(p))
        if key not in seen and os.path.isdir(p):
            seen.add(key)
            out.append(p)
    return out


def merge_thumbnails(old: str, new: str) -> None:
    """Bring every thumbnail from `old` into `new`, the newer of two copies of the same one winning, then drop `old` once it is empty. Nothing is
    deleted but the copies that were merged."""
    os.makedirs(new, exist_ok=True)
    for name in os.listdir(old):
        src, dst = os.path.join(old, name), os.path.join(new, name)
        try:
            if not os.path.isfile(src):
                continue
            if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
                os.remove(src)
            else:
                shutil.move(src, dst)
        except OSError:
            continue
    for folder in (old, os.path.dirname(old)):
        try:
            os.rmdir(folder)  # only if it is empty now
        except OSError:
            break


def _move_old_thumbnails(new: str) -> None:
    """Once per run: bring the old caches into the data folder, so everything the app stores is in one place - including the edited-look thumbnails
    (the cropped, rotated previews), which would otherwise show as the untouched scan. It is only a cache, so a failure costs nothing."""
    global _moved
    _moved = True
    try:
        for old in old_thumbnail_dirs():
            if os.path.normcase(os.path.abspath(old)) != os.path.normcase(os.path.abspath(new)):
                merge_thumbnails(old, new)
    except OSError:
        pass


def thumbnail_cache_dir() -> str:
    """Shared by ImportWindow and the main window's Filmstrip, so both
    read/write the same on-disk thumbnail cache (see
    features/browse/processor.py) instead of keeping separate ones."""
    path = os.path.join(app_data_dir(), THUMBNAIL_DIR)
    if not _moved and not os.environ.get("PHOTOEDITOR_DATA_DIR"):
        _move_old_thumbnails(path)
    return path
