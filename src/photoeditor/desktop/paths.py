import os

from PyQt6.QtCore import QStandardPaths

from ..features.datadir import app_data_dir  # noqa: F401  (re-exported: the controller imports it from here)


def legacy_database_paths() -> list[str]:
    """The per-executable databases earlier versions wrote (see features/persistence/legacy.py)."""
    base = os.path.dirname(app_data_dir())
    names = ("Python", "python", "pythonw", "Ethans Fuckass Editing App", "Ethans Editing App", "PhotoEditor Beta", "photoeditor")
    seen, out = set(), []
    for name in names:
        path = os.path.join(base, name, "photoeditor.db")
        key = os.path.normcase(path)
        if key not in seen and os.path.isfile(path) and os.path.normcase(os.path.dirname(path)) != os.path.normcase(app_data_dir()):
            seen.add(key)
            out.append(path)
    return out


def thumbnail_cache_dir() -> str:
    """Shared by ImportWindow and the main window's Filmstrip, so both
    read/write the same on-disk thumbnail cache (see
    features/browse/processor.py) instead of keeping separate ones."""
    return os.path.join(
        QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation),
        "thumbnails",
    )
