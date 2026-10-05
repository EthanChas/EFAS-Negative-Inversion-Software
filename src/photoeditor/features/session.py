"""What the app remembers between launches: the last photo and folder, recent folders, which tab was open, the sidebar widths, the
filmstrip filter. One JSON file in the app's data folder - no Qt imports."""

import json
import os
from typing import Any

from .datadir import app_data_dir

MAX_RECENT = 10
_MAX_LAST_BY_FOLDER = 60
_DEFAULTS: dict[str, Any] = {
    "recent_folders": [],      # newest first
    "last_image": "",
    "last_by_folder": {},      # folder -> the photo that was open in it
    "tab": "",                 # the open tool tab's id, or ""
    "left_width": 0,           # the side panels' widths (0 = never set)
    "right_width": 0,
    "filter": "all",
    "auto_advance": True,
    "sheet_columns": 5,        # the contact sheet dialog's last choices
    "sheet_page": "Letter",
    "sheet_landscape": True,
    "sheet_rejected": False,
}


def _path() -> str:
    return os.path.join(app_data_dir(), "session.json")


def load() -> dict[str, Any]:
    """Always complete: damaged or missing values fall back to the defaults, so a bad file never stops the app starting."""
    data: dict[str, Any] = {}
    try:
        with open(_path(), encoding="utf-8") as f:
            raw = json.load(f)
        data = raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        pass
    out: dict[str, Any] = {}
    for key, default in _DEFAULTS.items():
        value = data.get(key, default)
        if isinstance(default, bool):
            out[key] = value if isinstance(value, bool) else default
        elif isinstance(default, int):
            out[key] = value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else default
        elif isinstance(default, list):
            out[key] = [v for v in value if isinstance(v, str)] if isinstance(value, list) else list(default)
        elif isinstance(default, dict):
            out[key] = {k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(value, dict) else {}
        else:
            out[key] = value if isinstance(value, str) else default
    return out


def save(data: dict[str, Any]) -> None:
    try:
        os.makedirs(app_data_dir(), exist_ok=True)
        tmp = _path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, _path())
    except OSError:
        pass  # remembering is a convenience; a read-only data folder must not break editing


def remember_photo(data: dict[str, Any], image_path: str) -> None:
    """Note the open photo: it is the one to come back to, its folder moves to the top of the recents."""
    folder = os.path.dirname(image_path)
    data["last_image"] = image_path
    by_folder = {k: v for k, v in data["last_by_folder"].items() if k != folder}
    by_folder[folder] = image_path
    data["last_by_folder"] = dict(list(by_folder.items())[-_MAX_LAST_BY_FOLDER:])
    norm = os.path.normcase(os.path.abspath(folder))
    data["recent_folders"] = ([folder] + [f for f in data["recent_folders"] if os.path.normcase(os.path.abspath(f)) != norm])[:MAX_RECENT]
