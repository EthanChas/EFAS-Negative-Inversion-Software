"""The editor's remembered choices that live outside the database (export presets and folder, crop guide, library folders): one .ini file in the data
folder, instead of the Windows registry.

The registry is not safe for this: a program started from a packaged app gets a private copy of it, so what the editor remembered depended on how it
was launched (the same trap as AppData - see features/datadir.py). A file in the data folder is the same for every launch.

The first time, whatever the registry holds is copied in. A registry that looks different later (the other kind of launch saw another copy) is
copied in too - but only the keys the file does not already have, and each distinct registry state only once, so a choice deleted here does not
come back."""

import hashlib
import json
import os

from PyQt6.QtCore import QSettings

from ..features.datadir import app_data_dir

_FILE = "qsettings.ini"
_IMPORTED = "_meta/registry_imports"
_checked: set[str] = set()


def _native() -> QSettings:
    return QSettings("PhotoEditor", "PhotoEditor")  # the registry


def _import_registry(ini: QSettings) -> None:
    native = _native()
    keys = sorted(native.allKeys())
    if not keys:
        return
    state = hashlib.sha1(json.dumps([[k, str(native.value(k))] for k in keys]).encode("utf-8")).hexdigest()
    seen = str(ini.value(_IMPORTED, "") or "").split(",")
    if state in seen:
        return
    for key in keys:
        if not ini.contains(key):
            ini.setValue(key, native.value(key))
    ini.setValue(_IMPORTED, ",".join([s for s in seen if s] + [state]))
    ini.sync()


def qsettings() -> QSettings:
    """The editor's settings file (read and written like any QSettings: value / setValue)."""
    path = os.path.join(app_data_dir(), _FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ini = QSettings(path, QSettings.Format.IniFormat)
    if path not in _checked:
        _checked.add(path)
        if not os.environ.get("PHOTOEDITOR_DATA_DIR"):  # a test's throwaway folder must not pick up the real registry
            _import_registry(ini)
    return ini
