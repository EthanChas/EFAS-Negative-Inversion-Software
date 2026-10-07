"""The app's preferences, kept in one small JSON file in the app data folder - no Qt imports, so the decoding and backup code can read them too."""

import json
import os
from typing import Any

from ..datadir import app_data_dir

DEMOSAIC_CHOICES: dict[str, tuple[str, str, str]] = {
    "linear": ("Fast (linear)", "LINEAR", "Quickest and softest - fine for a quick look."),
    "ppg": ("Balanced (PPG)", "PPG", "Fast, with decent edges."),
    "vng": ("Smooth (VNG)", "VNG", "Gentle on noise and grain, a little soft."),
    "ahd": ("Standard (AHD)", "AHD", "The usual all-rounder."),
    "dcb": ("Clean edges (DCB)", "DCB", "Fewer colour fringes on fine edges."),
    "dht": ("Fine detail (DHT)", "DHT", "Sharp detail, kind to grain."),
    "aahd": ("Fine detail (AAHD)", "AAHD", "AHD with fewer maze-like artefacts in fine texture."),
}
BACKUP_KEEP_RANGE = (1, 365)
DEFAULTS: dict[str, Any] = {
    "raw_demosaic": "ahd",
    "raw_auto_bright": True,
    "auto_advance": True,
    "backup_auto": True,
    "check_updates": True,
    "backup_keep": 14,
    "backup_dir": "",
    "keybinds": {},
}

_cache: tuple[int, dict[str, Any]] | None = None


def settings_path() -> str:
    return os.path.join(app_data_dir(), "settings.json")


def _clean(data: Any) -> dict[str, Any]:
    """Unknown keys are dropped and a wrong-typed value falls back to its default, so a damaged file never stops the app."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    if not isinstance(data, dict):
        return out
    if data.get("raw_demosaic") in DEMOSAIC_CHOICES:
        out["raw_demosaic"] = data["raw_demosaic"]
    for key in ("raw_auto_bright", "auto_advance", "backup_auto", "check_updates"):
        if isinstance(data.get(key), bool):
            out[key] = data[key]
    keep = data.get("backup_keep")
    if isinstance(keep, int) and not isinstance(keep, bool):
        out["backup_keep"] = max(BACKUP_KEEP_RANGE[0], min(BACKUP_KEEP_RANGE[1], keep))
    if isinstance(data.get("backup_dir"), str):
        out["backup_dir"] = data["backup_dir"].strip()
    if isinstance(data.get("keybinds"), dict):
        out["keybinds"] = {str(k): v for k, v in data["keybinds"].items() if isinstance(v, str)}
    return out


def _read_raw() -> dict[str, Any] | None:
    try:
        with open(settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def has(key: str) -> bool:
    """True when the settings file itself says something about `key` (as opposed to the default applying)."""
    raw = _read_raw()
    return raw is not None and key in raw


def load() -> dict[str, Any]:
    """All the settings (defaults filled in)."""
    global _cache
    path = settings_path()
    try:
        stamp = os.stat(path).st_mtime_ns
    except OSError:
        return _clean(None)
    if _cache is not None and _cache[0] == stamp:
        return _clean(_cache[1])
    raw = _read_raw()
    data = _clean(raw)
    _cache = (stamp, data)
    return _clean(data)


def save(values: dict[str, Any]) -> None:
    """Write `values` over the saved settings (a key left out keeps its saved value)."""
    merged = load()
    merged.update(values)
    os.makedirs(app_data_dir(), exist_ok=True)
    tmp = settings_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_clean(merged), f, indent=2)
    os.replace(tmp, settings_path())
    global _cache
    _cache = None


def get(key: str) -> Any:
    return load()[key]
