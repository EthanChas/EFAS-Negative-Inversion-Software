"""Names to offer while typing a camera, lens or film - no Qt imports.

The user's presets come first, then the bundled lists (assets/gear/*.json). What is typed in the Roll Card's fields is never remembered or
suggested back: the fields are plain text, so anything can be typed."""

import json
from pathlib import Path

from .roll import KNOWN_FILMS

_BUNDLED = Path(__file__).resolve().parents[2] / "assets" / "gear"


def _bundled_names(fname: str, make) -> list[str]:
    try:
        with open(_BUNDLED / fname, encoding="utf-8") as f:
            return [n for n in (make(d) for d in json.load(f) if isinstance(d, dict)) if n]
    except (OSError, json.JSONDecodeError):
        return []


def suggestions(kind: str) -> list[str]:
    """The user's presets first, then the built-in lists (unless switched off in the Presets section).
    The films the app has canister art for are always offered."""
    from . import presets

    seed: list[str] = []
    if presets.use_bundled():
        if kind == "camera":
            seed = _bundled_names("cameras.json", lambda d: (d.get("displayName") or f"{d.get('make', '')} {d.get('model', '')}").strip())
        elif kind == "lens":
            seed = _bundled_names("lenses.json", lambda d: (d.get("displayName") or d.get("lensModel") or "").strip())
        elif kind == "film":
            seed = _bundled_names("film_stocks.json", lambda d: (d.get("displayName") or f"{d.get('manufacturer', '')} {d.get('stockName', '')}").strip())
    first = presets.user_names(kind) if kind in presets.KINDS else []
    if kind == "film":
        seed = list(KNOWN_FILMS) + seed
    out, seen = [], set()
    for name in first + seed:
        if name.casefold() not in seen:
            seen.add(name.casefold()); out.append(name)
    return out
