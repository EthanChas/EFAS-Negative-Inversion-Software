"""The user's saved edit presets - a name and a look (tone, color, film type, sharpening, watermark) to put on any photo. No Qt imports.

Kept in look_presets.json in the app's data folder, in the order they were made. What a look may contain is the controller's business
(AppController.LOOK_FIELDS); this file only stores named dicts of plain values."""

import json
import os
from typing import Any

from ..datadir import app_data_dir

MAX_NAME = 60


def _path() -> str:
    return os.path.join(app_data_dir(), "look_presets.json")


def clean_name(name: str) -> str:
    return " ".join(str(name).split())[:MAX_NAME]


def load() -> list[dict[str, Any]]:
    """[{"name": str, "look": dict}] in saved order."""
    try:
        with open(_path(), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get("presets") if isinstance(raw, dict) else None
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items if isinstance(items, list) else []:
        if not (isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("look"), dict)):
            continue
        name = clean_name(item["name"])
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            out.append({"name": name, "look": item["look"]})
    return out


def _save(presets: list[dict[str, Any]]) -> None:
    try:
        os.makedirs(app_data_dir(), exist_ok=True)
        tmp = _path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"presets": presets}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _path())
    except OSError:
        pass


def names() -> list[str]:
    return [p["name"] for p in load()]


def get(name: str) -> dict[str, Any] | None:
    key = clean_name(name).casefold()
    return next((p["look"] for p in load() if p["name"].casefold() == key), None)


def save_preset(name: str, look: dict[str, Any]) -> str | None:
    """Add a preset, or replace the one with that name (case-insensitive) keeping its place."""
    name = clean_name(name)
    if not name:
        return None
    presets = load()
    for p in presets:
        if p["name"].casefold() == name.casefold():
            p["name"], p["look"] = name, look
            break
    else:
        presets.append({"name": name, "look": look})
    _save(presets)
    return name


def replace_preset(old_name: str, new_name: str, look: dict[str, Any]) -> str | None:
    """Rewrite a preset - possibly under a new name - keeping its place in the list."""
    old_key, new_name = clean_name(old_name).casefold(), clean_name(new_name)
    if not new_name:
        return None
    presets = load()
    index = next((i for i, p in enumerate(presets) if p["name"].casefold() == old_key), None)
    if index is None or any(i != index and p["name"].casefold() == new_name.casefold() for i, p in enumerate(presets)):
        return None
    presets[index] = {"name": new_name, "look": look}
    _save(presets)
    return new_name


def delete_preset(name: str) -> bool:
    key = clean_name(name).casefold()
    presets = load()
    kept = [p for p in presets if p["name"].casefold() != key]
    if len(kept) == len(presets):
        return False
    _save(kept)
    return True
