"""The user's saved edit presets - a name and a look (tone, color, film type, sharpening, watermark) to put on any photo. No Qt imports.

Kept in look-presets.json in the app's data folder, in the order they were made. What a look may contain is the controller's business
(AppController.LOOK_FIELDS); this file only stores named dicts of plain values. It also keeps the folders made on purpose ("folders"), which stay when nothing is in them."""

import json
import os
from typing import Any

from ..datadir import LOOK_PRESETS_FILE, app_data_dir
from ..presettree import logic as tree
from ..presettree.logic import MAX_PATH, clean_path

MAX_NAME = MAX_PATH


def _path() -> str:
    return os.path.join(app_data_dir(), LOOK_PRESETS_FILE)


def clean_name(name: str) -> str:
    """A preset name: a path, so "B&W / Number 1" is Number 1 in the folder B&W (see features/presettree)."""
    return clean_path(name)


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


def folders() -> list[str]:
    """The folders made on purpose (they stay when nothing is in them), cleaned and without repeats, in the order made. A folder a preset's name runs through needs no entry here."""
    try:
        with open(_path(), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get("folders") if isinstance(raw, dict) else None
    out: list[str] = []
    seen: set[str] = set()
    for item in items if isinstance(items, list) else []:
        path = clean_name(item) if isinstance(item, str) else ""
        if path and path.casefold() not in seen:
            seen.add(path.casefold())
            out.append(path)
    return out


def _save(presets: list[dict[str, Any]], folder_list: list[str] | None = None) -> None:
    """Write the presets - and the folders, which are left as they were unless a new list is given."""
    if folder_list is None:
        folder_list = folders()
    try:
        os.makedirs(app_data_dir(), exist_ok=True)
        tmp = _path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"presets": presets, "folders": folder_list}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _path())
    except OSError:
        pass


def set_folders(paths: list[str]) -> None:
    """Replace the list of folders made on purpose (cleaned, without repeats)."""
    clean: list[str] = []
    seen: set[str] = set()
    for path in paths:
        path = clean_name(path)
        if path and path.casefold() not in seen:
            seen.add(path.casefold())
            clean.append(path)
    _save(load(), clean)


def add_folder(path: str) -> str | None:
    """Make a folder (it stays when empty). None when the name is empty or there is already a folder with it."""
    path = clean_name(path)
    if not path:
        return None
    known = {p.casefold() for p in tree.folder_paths(names(), folders())}
    if path.casefold() in known:
        return None
    set_folders([*folders(), path])
    return path


def remove_folder_records(folder: str) -> None:
    """Forget the folders made on purpose that are this folder or inside it (the presets are not touched)."""
    set_folders([f for f in folders() if not tree.is_inside(f, folder)])


def rename_folder_records(old: str, new: str) -> None:
    """The folders made on purpose that are `old` or inside it, moved to `new` (the presets are not touched)."""
    old, new = clean_name(old), clean_name(new)
    prefix = old.casefold() + tree.SEP
    out = []
    for f in folders():
        if f.casefold() == old.casefold():
            out.append(new)
        elif f.casefold().startswith(prefix):
            out.append(tree.join(new, f[len(old) + 1:]))
        else:
            out.append(f)
    set_folders(out)


def forget_empty_folders() -> int:
    """Remove the folders made on purpose that have no preset in them. How many were removed."""
    current = folders()
    empty = {f.casefold() for f in tree.empty_folders(names(), current)}
    kept = [f for f in current if f.casefold() not in empty]
    set_folders(kept)
    return len(current) - len(kept)


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
