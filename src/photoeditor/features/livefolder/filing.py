"""Moving photos about on disk for the hotstack folders - no Qt: into a dated folder when a session is finished, and out of the way when a retake replaces one.

A photo goes with its sidecars (the .xmp and merge files EFAS writes beside it), is never overwritten (a name that is taken gets _1, _2...) and is never deleted."""
import os
import shutil
from datetime import datetime

from ..library.removal import SIDECAR_SUFFIXES

DATE_FORMAT = "%d-%m-%Y"   # the same as the Export panel's date sub-folders
RETAKES = "Retakes"        # where a photo that was retaken is set aside, beside where it was


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def is_under(path: str, folder: str) -> bool:
    return bool(folder) and _norm(path).startswith(_norm(folder).rstrip("\\/") + os.sep)


def date_folder_name(when: float) -> str:
    return datetime.fromtimestamp(when).strftime(DATE_FORMAT)


def _taken(path: str) -> bool:
    return os.path.exists(path) or any(os.path.exists(path + s) for s in SIDECAR_SUFFIXES)


def free_name(path: str) -> str:
    """`path`, or the first of path_1, path_2... that neither the photo nor a sidecar of it is using."""
    if not _taken(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 1
    while _taken(f"{stem}_{n}{ext}"):
        n += 1
    return f"{stem}_{n}{ext}"


def move_photo(src: str, dst: str) -> str:
    """Move a photo and its sidecars to `dst` (or the nearest free name beside it) and say where it went. OSError when it cannot be moved: it is then left where it was."""
    dst = free_name(dst)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    for suffix in SIDECAR_SUFFIXES:
        if os.path.isfile(src + suffix):
            try:
                shutil.move(src + suffix, dst + suffix)
            except OSError:
                pass   # a sidecar is written again the next time the photo is saved
    return dst


def finish_plan(photos: list[str], asides: list[str], hotstacks: list[str]) -> list[tuple[str, str]]:
    """Where each photo of a session goes: (from, to). A photo goes into a DD-MM-YYYY folder (the day of its file) inside the hotstack folder it is in - inside its own folder when it is
    in none - and a set-aside retake goes into the Retakes folder of that. Photos that are gone, or already where they would go, are left out."""
    plan = []
    for src, aside in [(p, False) for p in photos] + [(p, True) for p in asides]:
        if not os.path.isfile(src):
            continue
        base = next((h for h in hotstacks if is_under(src, h)), os.path.dirname(src))
        folder = os.path.join(base, date_folder_name(os.path.getmtime(src)))
        if aside:
            folder = os.path.join(folder, RETAKES)
        if _norm(os.path.dirname(src)) != _norm(folder):
            plan.append((src, os.path.join(folder, os.path.basename(src))))
    return plan


def retake_names(old: str, new: str) -> tuple[str, str]:
    """(where the old photo is set aside, the name the retake takes). The retake takes the old photo's name and place, with its own extension."""
    folder = os.path.dirname(old)
    return os.path.join(folder, RETAKES, os.path.basename(old)), os.path.join(folder, os.path.splitext(os.path.basename(old))[0] + os.path.splitext(new)[1])


def swap_in_retake(old: str, new: str) -> tuple[str, str]:
    """The old photo is set aside in a Retakes folder beside it and the new one takes its name and place. Returns (where the old one went, where the new one is now).
    OSError when it cannot be done, with the old photo back where it was."""
    aside_name, target = retake_names(old, new)
    aside = move_photo(old, aside_name)
    try:
        final = move_photo(new, target)
    except OSError:
        move_photo(aside, old)
        raise
    return aside, final
