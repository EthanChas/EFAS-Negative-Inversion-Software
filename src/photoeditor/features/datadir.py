"""Where the app keeps its own files (database, backups, remembered camera/lens names) - no Qt imports."""

import os


def app_data_dir() -> str:
    """A fixed folder, not Qt's AppDataLocation, which is named after the running executable - launching as python, pythonw
    or the packaged EXE would each get a different database. PHOTOEDITOR_DATA_DIR overrides it (tests)."""
    override = os.environ.get("PHOTOEDITOR_DATA_DIR")
    if override:
        return override
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "PhotoEditor")
