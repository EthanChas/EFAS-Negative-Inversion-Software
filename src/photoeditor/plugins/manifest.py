"""What a plugin is on disk: a folder in the plugins folder with a plugin.json beside its program (main.py or main.lua). Pure: no Qt."""
import json
import os
import re
from dataclasses import dataclass

API_VERSION = 1  # bumped when the plugin API changes in a way that can break a plugin; a plugin names the lowest it needs
MANIFEST_FILE = "plugin.json"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
LANGUAGES = {".py": "python", ".lua": "lua"}


@dataclass(frozen=True)
class Manifest:
    id: str
    name: str
    version: str
    author: str
    description: str
    language: str  # "python" or "lua"
    entry: str  # the program's file, relative to the plugin's folder
    api: int  # the lowest plugin API version it needs
    folder: str

    @property
    def entry_path(self) -> str:
        return os.path.join(self.folder, self.entry)


@dataclass(frozen=True)
class Found:
    """One folder in the plugins folder: its manifest, or why it is not a usable plugin."""
    folder: str
    manifest: Manifest | None
    error: str = ""


def _text(value, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def parse_manifest(data, folder: str) -> tuple[Manifest | None, str]:
    """(the manifest, "") or (None, what is wrong with it, in a sentence)."""
    if not isinstance(data, dict):
        return None, "plugin.json must hold one JSON object."
    pid = _text(data.get("id"), 64).lower()
    if not ID_RE.match(pid):
        return None, 'plugin.json needs an "id" of 2 to 64 letters, digits, dots, dashes or underscores, like "com.example.hello".'
    name = _text(data.get("name"), 60) or pid
    entry = _text(data.get("entry"), 120)
    if not entry:
        entry = next((f for f in ("main.py", "main.lua") if os.path.isfile(os.path.join(folder, f))), "")
    if not entry:
        return None, 'plugin.json needs an "entry" (the program\'s file), or a main.py or main.lua beside it.'
    normalised = os.path.normpath(entry)
    if os.path.isabs(entry) or entry.startswith(("/", "\\")) or ":" in entry or normalised.startswith("..") or normalised != entry.replace("/", os.sep):
        return None, f'The entry "{entry}" must be a file inside the plugin\'s own folder.'
    language = LANGUAGES.get(os.path.splitext(entry)[1].lower(), "")
    declared = _text(data.get("language"), 10).lower()
    if declared and declared != language:
        return None, f'The language "{declared}" does not match the entry file "{entry}".'
    if not language:
        return None, f'The entry "{entry}" must be a .py (Python) or .lua (Lua) file.'
    if not os.path.isfile(os.path.join(folder, entry)):
        return None, f'The entry file "{entry}" is not in the plugin\'s folder.'
    api = data.get("api", 1)
    if isinstance(api, bool) or not isinstance(api, int) or api < 1:
        return None, 'The "api" must be a whole number, 1 or more.'
    if api > API_VERSION:
        return None, f"It needs plugin API {api} but this EFAS has {API_VERSION}: update EFAS to use it."
    return Manifest(pid, name, _text(data.get("version"), 30) or "0", _text(data.get("author"), 80), _text(data.get("description"), 400), language, entry, api, folder), ""


def load_manifest(folder: str) -> tuple[Manifest | None, str]:
    path = os.path.join(folder, MANIFEST_FILE)
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None, "There is no plugin.json in this folder."
    except (OSError, ValueError) as exc:
        return None, f"plugin.json could not be read ({exc})."
    return parse_manifest(data, folder)


def discover(plugins_dir: str) -> list[Found]:
    """Every folder in the plugins folder, as a Found (usable or not), sorted by name. A second folder with the same id is reported, not loaded."""
    try:
        names = sorted((n for n in os.listdir(plugins_dir) if os.path.isdir(os.path.join(plugins_dir, n)) and not n.startswith((".", "_"))), key=str.lower)
    except OSError:
        return []
    found: list[Found] = []
    seen: set[str] = set()
    for name in names:
        folder = os.path.join(plugins_dir, name)
        manifest, error = load_manifest(folder)
        if manifest is not None and manifest.id in seen:
            manifest, error = None, f'Another plugin folder already uses the id "{manifest.id}".'
        if manifest is not None:
            seen.add(manifest.id)
        found.append(Found(folder, manifest, error))
    return found
