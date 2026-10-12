"""The user's own pre-made tags: tags they use again and again, kept in a short list so they never have to type them in twice - no Qt imports.

The list lives in one small file in the data folder. It is only a shortcut list: a tag does not have to be in it to be used, and taking a tag out of it
does not touch any photo."""

import json
import os

from ..datadir import PREMADE_TAGS_FILE, app_data_dir
from . import logic as T


def path() -> str:
    return os.path.join(app_data_dir(), PREMADE_TAGS_FILE)


def load() -> list[str]:
    """The saved list (empty if there is none, or it cannot be read), each tag as it is stored, in the order the user put them."""
    try:
        with open(path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    return T.unique(t for t in data if isinstance(t, str)) if isinstance(data, list) else []


def save(tags) -> list[str]:
    tags = T.unique(tags)
    os.makedirs(app_data_dir(), exist_ok=True)
    tmp = path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(tags, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path())
    return tags


def add(tags) -> list[str]:
    """Put tags on the list (ones already there stay where they are)."""
    return save([*load(), *tags])


def remove(tags) -> list[str]:
    gone = {T.clean_tag(t).casefold() for t in tags}
    return save([t for t in load() if t.casefold() not in gone])
