import os

from PyQt6.QtCore import QStandardPaths

from ..features.datadir import app_data_dir  # noqa: F401  (re-exported: the controller imports it from here)


def thumbnail_cache_dir() -> str:
    """Shared by ImportWindow and the main window's Filmstrip, so both
    read/write the same on-disk thumbnail cache (see
    features/browse/processor.py) instead of keeping separate ones."""
    return os.path.join(
        QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation),
        "thumbnails",
    )
