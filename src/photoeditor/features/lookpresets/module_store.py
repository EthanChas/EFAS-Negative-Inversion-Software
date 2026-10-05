"""The presets of single editing modules - what the little menu in a module's header stores and loads (darktable-style). No Qt imports.

A module preset is a name and the values of just that module's fields. Kept per module in module_presets.json in the app's data folder:
{"exposure": [{"name": "Push a stop", "values": {...}}], "color": [...]}. They are separate from the whole-look presets
(store.py): those hold a photo's entire look, these hold one module."""

import json
import os
from typing import Any

from ..datadir import app_data_dir
from .store import clean_name


def _path() -> str:
    return os.path.join(app_data_dir(), "module_presets.json")


def _load_all() -> dict[str, list[dict[str, Any]]]:
    try:
        with open(_path(), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for module, items in (raw.items() if isinstance(raw, dict) else []):
        seen: set[str] = set()
        clean = []
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("values"), dict):
                name = clean_name(item["name"])
                if name and name.casefold() not in seen:
                    seen.add(name.casefold())
                    clean.append({"name": name, "values": item["values"]})
        out[str(module)] = clean
    return out


def _save_all(data: dict[str, list[dict[str, Any]]]) -> None:
    try:
        os.makedirs(app_data_dir(), exist_ok=True)
        tmp = _path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _path())
    except OSError:
        pass  # a read-only data folder must not break editing


def names(module: str) -> list[str]:
    return [p["name"] for p in _load_all().get(module, [])]


def get(module: str, name: str) -> dict[str, Any] | None:
    key = clean_name(name).casefold()
    return next((p["values"] for p in _load_all().get(module, []) if p["name"].casefold() == key), None)


def save_preset(module: str, name: str, values: dict[str, Any]) -> str | None:
    """Add a preset to a module, or replace the one with that name (case-insensitive). Returns the stored name; None for a blank one."""
    name = clean_name(name)
    if not name:
        return None
    data = _load_all()
    items = data.setdefault(module, [])
    for item in items:
        if item["name"].casefold() == name.casefold():
            item["name"], item["values"] = name, values
            break
    else:
        items.append({"name": name, "values": values})
    _save_all(data)
    return name


def delete_preset(module: str, name: str) -> bool:
    key = clean_name(name).casefold()
    data = _load_all()
    items = data.get(module, [])
    kept = [p for p in items if p["name"].casefold() != key]
    if len(kept) == len(items):
        return False
    data[module] = kept
    _save_all(data)
    return True
