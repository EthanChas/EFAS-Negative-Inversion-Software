"""The user's own autofill presets for the Roll Card - cameras, lenses and films - no Qt imports.

A preset is a name the Roll Card's fields suggest while you type. A camera preset can remember its usual lens (picking the camera fills
the lens in), a film preset its ISO and format (picking the film fills those in). They live in presets.json under the app's data folder."""

import json
import os
from typing import Any, Optional

from ..datadir import app_data_dir
from .models import FORMAT_OPTIONS
from .roll import KNOWN_FILMS

KINDS = ("camera", "lens", "film")


def _path() -> str:
    return os.path.join(app_data_dir(), "presets.json")


def load() -> dict[str, Any]:
    """{"camera": [{"name", "lens"}], "lens": [{"name"}], "film": [{"name", "iso", "format"}], "use_bundled": bool} - always complete."""
    data: dict[str, Any] = {}
    try:
        with open(_path(), encoding="utf-8") as f:
            raw = json.load(f)
        data = raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        pass
    out: dict[str, Any] = {"use_bundled": data.get("use_bundled", True) is not False}
    for kind in KINDS:
        entries = []
        for item in data.get(kind, []) if isinstance(data.get(kind), list) else []:
            if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip():
                entries.append(dict(item, name=item["name"].strip()))
        out[kind] = entries
    return out


def save(data: dict[str, Any]) -> None:
    os.makedirs(app_data_dir(), exist_ok=True)
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _path())


def _clean(kind: str, name: str, extra: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": name.strip()}
    if kind == "camera":
        entry["lens"] = str(extra.get("lens", "")).strip()
    elif kind == "film":
        iso = extra.get("iso")
        entry["iso"] = int(iso) if isinstance(iso, (int, float)) and not isinstance(iso, bool) and iso > 0 else None
        fmt = extra.get("format", "")
        entry["format"] = fmt if fmt in FORMAT_OPTIONS[1:] else ""
    return entry


def upsert(kind: str, name: str, **extra: Any) -> bool:
    """Add a preset, or replace the one with the same name (case-insensitive). False for a blank name."""
    if kind not in KINDS or not name.strip():
        return False
    data = load()
    entry = _clean(kind, name, extra)
    entries = [e for e in data[kind] if e["name"].casefold() != entry["name"].casefold()]
    entries.append(entry)
    data[kind] = sorted(entries, key=lambda e: e["name"].casefold())
    save(data)
    return True


def remove(kind: str, name: str) -> bool:
    if kind not in KINDS:
        return False
    data = load()
    kept = [e for e in data[kind] if e["name"].casefold() != name.strip().casefold()]
    if len(kept) == len(data[kind]):
        return False
    data[kind] = kept
    save(data)
    return True


def entries(kind: str) -> list[dict[str, Any]]:
    return load().get(kind, [])


def user_names(kind: str) -> list[str]:
    return [e["name"] for e in entries(kind)]


def find(kind: str, name: str) -> Optional[dict[str, Any]]:
    needle = name.strip().casefold()
    return next((e for e in entries(kind) if e["name"].casefold() == needle), None)


def camera_lens(camera: str) -> str:
    """The usual lens saved with this camera preset, or ""."""
    entry = find("camera", camera)
    return entry.get("lens", "") if entry else ""


def film_info(film: str) -> tuple[Optional[int], str]:
    """(ISO, format) to fill in when this film is picked: the user's preset if there is one, else a film the app knows."""
    entry = find("film", film)
    if entry is not None:
        return entry.get("iso"), entry.get("format", "")
    known = next((v for k, v in KNOWN_FILMS.items() if k.casefold() == film.strip().casefold()), None)
    return (known[0], known[1]) if known else (None, "")


def use_bundled() -> bool:
    return load()["use_bundled"]


def set_use_bundled(on: bool) -> None:
    data = load()
    data["use_bundled"] = bool(on)
    save(data)
