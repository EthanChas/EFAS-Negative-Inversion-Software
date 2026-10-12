import os
import shutil

from PyQt6.QtCore import QStandardPaths

from ..features.datadir import THUMBNAIL_DIR, app_data_dir  # noqa: F401  (re-exported: the controller imports it from here)

_moved = False


def system_thumbnail_dir() -> str:
    """Where older versions kept the thumbnail cache: the system's cache folder for the app."""
    return os.path.join(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation), "thumbnails")


def _move_old_thumbnails(new: str) -> None:
    """Once per run: bring the old cache into the data folder, so everything the app stores is in one place. It is only a cache, so a failure costs nothing."""
    global _moved
    _moved = True
    old = system_thumbnail_dir()
    try:
        if os.path.isdir(old) and os.path.normcase(os.path.abspath(old)) != os.path.normcase(os.path.abspath(new)):
            os.makedirs(new, exist_ok=True)
            for name in os.listdir(old):
                if not os.path.exists(os.path.join(new, name)):
                    shutil.move(os.path.join(old, name), os.path.join(new, name))
            shutil.rmtree(old, ignore_errors=True)
            try:
                os.rmdir(os.path.dirname(old))  # the app's own cache folder, if that left it empty
            except OSError:
                pass
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
