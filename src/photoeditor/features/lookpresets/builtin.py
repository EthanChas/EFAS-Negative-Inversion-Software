"""The presets that come with EFAS: read-only, kept as JSON files in assets/presets, each {"presets": [{"name": "Folder/Name", "description": str, "look": {...}}]}.
Names are paths (see features/presettree): "Film Stocks/Kodak/Portra" is Portra in the folder Kodak in the folder Film Stocks. No Qt imports.

A scanner's colour is not a preset: it is Lab Look's Scanner colour, so a look never brings a second one on top of it. PHOTOEDITOR_EXTRA_PRESETS names one more folder of the same kind of files to read (the tests use it
for their own sets of presets)."""
import json
import os
from pathlib import Path
from typing import Any

from ..presettree import logic as tree

PRESET_DIR = Path(__file__).resolve().parents[2] / "assets" / "presets"
_cache: list[dict[str, Any]] | None = None


def load() -> list[dict[str, Any]]:
    """[{"name", "description", "look"}] from every file in the folder (files in name order, presets in file order); anything unreadable is skipped."""
    global _cache
    if _cache is not None:
        return _cache
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    folders = [PRESET_DIR] + ([Path(os.environ["PHOTOEDITOR_EXTRA_PRESETS"])] if os.environ.get("PHOTOEDITOR_EXTRA_PRESETS") else [])
    files = []
    for folder in folders:
        try:
            files += sorted(folder.glob("*.json"), key=lambda p: p.name.casefold())
        except OSError:
            continue
    for path in files:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for item in raw.get("presets", []) if isinstance(raw, dict) else []:
            if not (isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("look"), dict)):
                continue
            name = tree.clean_path(item["name"])
            if name and name.casefold() not in seen:
                seen.add(name.casefold())
                out.append({"name": name, "description": str(item.get("description", "")), "look": item["look"]})
    _cache = out
    return out


def reload() -> None:
    global _cache
    _cache = None


def names() -> list[str]:
    return [p["name"] for p in load()]


def get(name: str) -> dict[str, Any] | None:
    key = tree.clean_path(name).casefold()
    return next((p["look"] for p in load() if p["name"].casefold() == key), None)


def description(name: str) -> str:
    key = tree.clean_path(name).casefold()
    return next((p["description"] for p in load() if p["name"].casefold() == key), "")
