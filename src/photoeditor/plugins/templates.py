"""Starting points for plugin authors: the bundled example plugins, and an empty plugin to fill in. Pure files; no Qt."""
import json
import os
import re
import shutil
from pathlib import Path

_QUOTES = re.compile(r'["\\\n\r]')  # kept out of the name written into the program's comment and print line
EXAMPLES_DIR =Path(__file__).resolve().parents[1] / "assets" / "plugin-examples"

_PY_TEMPLATE = '''"""{name}: describe what this plugin does here.

EFAS calls register(api) when the plugin is switched on in Settings > Plugins. See docs/plugins on GitHub for everything `api` can do."""


def register(api):
    api.info("{name} is on")
    api.add_menu_item("Do something", lambda: api.message("It works!"))
'''

_LUA_TEMPLATE = """-- {name}: describe what this plugin does here.
-- EFAS runs this file when the plugin is switched on in Settings > Plugins. `efas` is everything the plugin can do (see docs/plugins on GitHub).

print("{name} is on")
efas.add_menu_item{{ label = "Do something", on_click = function() efas.message("It works!") end }}
"""


def example_folders() -> list[Path]:
    if not EXAMPLES_DIR.is_dir():
        return []
    return sorted((p for p in EXAMPLES_DIR.iterdir() if p.is_dir()), key=lambda p: p.name)


def install_examples(plugins_dir: str) -> list[str]:
    """Copy the bundled examples into the plugins folder (a folder already there is left alone). Returns the folder names that were added."""
    os.makedirs(plugins_dir, exist_ok=True)
    added = []
    for source in example_folders():
        target = os.path.join(plugins_dir, source.name)
        if os.path.exists(target):
            continue
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
        added.append(source.name)
    return added


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]


def create_template(plugins_dir: str, name: str, language: str, author: str = "") -> str:
    """Make a new plugin folder holding a plugin.json and a short working program; returns the folder. Raises ValueError with a sentence when it cannot."""
    if language not in ("python", "lua"):
        raise ValueError("The language must be Python or Lua.")
    name = name.strip()[:60]
    slug = _slug(name)
    if len(slug) < 2:
        raise ValueError("Give the plugin a name of at least two letters or digits.")
    folder = os.path.join(plugins_dir, slug)
    if os.path.exists(folder):
        raise ValueError(f'There is already a plugin folder called "{slug}".')
    entry = "main.py" if language == "python" else "main.lua"
    os.makedirs(folder)
    manifest = {"id": f"user.{slug}", "name": name, "version": "0.1", "author": author, "description": "", "entry": entry, "api": 1}
    with open(os.path.join(folder, "plugin.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    with open(os.path.join(folder, entry), "w", encoding="utf-8") as f:
        f.write((_PY_TEMPLATE if language == "python" else _LUA_TEMPLATE).format(name=_QUOTES.sub("", name)))
    return folder
