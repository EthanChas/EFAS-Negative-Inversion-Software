"""The film profiles that come with EFAS (assets/film_profiles): characteristic curves printed by a film's maker, kept as "supplied" profiles (not measured by EFAS).

They are copied into the person's own film-profiles folder the first time the folder is used, each once: a profile that was deleted, or changed, afterwards is not put back. No Qt imports."""
import json
import os
from pathlib import Path

from .film_profile import FilmProfile, ProfileError, ProfileStore

BUNDLED_DIR = Path(__file__).resolve().parents[2] / "assets" / "film_profiles"
MARKER = "bundled-installed.txt"      # the ids already put in this folder (not a .json file: the store would list it as a profile)


def available() -> list[FilmProfile]:
    out = []
    try:
        files = sorted(BUNDLED_DIR.glob("*.json"))
    except OSError:
        return out
    for path in files:
        try:
            out.append(FilmProfile.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError, ProfileError):
            continue
    return out


def install(store: ProfileStore) -> list[str]:
    """Put the bundled profiles that this folder has not had yet into it; returns the names of those added."""
    marker = os.path.join(store.folder, MARKER)
    try:
        with open(marker, encoding="utf-8") as f:
            had = {line.strip() for line in f if line.strip()}
    except OSError:
        had = set()
    added, now = [], set(had)
    for profile in available():
        if profile.id in had:
            continue
        now.add(profile.id)
        if not store.exists(profile.id):
            store.save(profile)
            added.append(profile.name)
    if now != had:
        try:
            os.makedirs(store.folder, exist_ok=True)
            with open(marker, "w", encoding="utf-8") as f:
                f.write("\n".join(sorted(now)) + "\n")
        except OSError:
            pass
    return added
