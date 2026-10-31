"""Making, renaming and deleting the folders of the Library on disk, and following a folder to its new name. No Qt imports.

A folder is only ever made with a plain name, renamed in the place it is in (never over another folder) and deleted to the Recycle Bin (never for good: if that
cannot be done the folder is left where it is). Every function says what is wrong with a FolderError whose text is fit to show.
"""

import os
from dataclasses import dataclass, field

from ..open_image.logic import SUPPORTED_EXTS
from .removal import SIDECAR_SUFFIXES, TrashUnavailable, send_to_trash

_BAD_CHARS = '<>:"/\\|?*'
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)), *(f"lpt{n}" for n in range(1, 10))}


class FolderError(Exception):
    """A folder could not be made, renamed or deleted; the text says why."""


@dataclass(frozen=True)
class FolderSummary:
    photos: int
    bytes: int
    folders: int   # folders inside it, at any depth
    others: int    # files that are not photos or the sidecars EFAS wrote
    names: tuple = field(default=())   # a few of its sub-folder names, for the confirmation


def norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def flat(path: str) -> str:
    """A path spelled for comparing without changing its length: the case of Windows, and one kind of slash."""
    return os.path.normcase(path.replace("/", os.sep))


def is_inside(path: str, folder: str, include_self: bool = True) -> bool:
    """Whether `path` is `folder` itself (when include_self) or inside it."""
    if not path or not folder:
        return False
    a, b = norm(path), norm(folder).rstrip("\\/")
    return (include_self and a == b) or a.startswith(b + os.sep)


def check_name(name: str) -> str:
    """The name a folder may have, tidied (spaces round it dropped), or a FolderError saying what is wrong with it."""
    name = (name or "").strip()
    if not name:
        raise FolderError("Type a name for the folder.")
    if name in (".", "..") or name.endswith("."):
        raise FolderError("A folder name cannot end with a dot.")
    shown = sorted({c for c in name if c in _BAD_CHARS})
    if shown:
        raise FolderError("A folder name cannot contain " + " ".join(shown) + ".")
    if any(ord(c) < 32 for c in name):
        raise FolderError("A folder name cannot contain control characters.")
    if name.split(".")[0].lower() in _RESERVED:
        raise FolderError(f"\"{name}\" is a name Windows keeps for itself; pick another.")
    if len(name) > 200:
        raise FolderError("That name is too long.")
    return name


def create_folder(parent: str, name: str) -> str:
    """Make a folder called `name` inside `parent` and say where it is."""
    name = check_name(name)
    if not parent or not os.path.isdir(parent):
        raise FolderError("The folder to make it in is not there any more.")
    target = os.path.join(parent, name)
    if os.path.exists(target):
        raise FolderError(f"\"{name}\" is already in \"{os.path.basename(parent.rstrip('/' + os.sep)) or parent}\".")
    try:
        os.mkdir(target)
    except OSError as exc:
        raise FolderError(f"The folder could not be made: {exc.strerror or exc}") from exc
    return target


def sibling(folder: str, name: str) -> str:
    """Where `folder` is when it has the name `name`: the same place, spelled the way `folder` is."""
    old = folder.rstrip("/" + os.sep)
    return old[: len(old) - len(os.path.basename(old.replace("/", os.sep)))] + name


def plan_rename(folder: str, new_name: str) -> str:
    """Where `folder` would be with the name `new_name` - or a FolderError saying why it cannot be renamed. Nothing is changed. It never replaces another folder (a change of
    capitals only is allowed)."""
    new_name = check_name(new_name)
    old = folder.rstrip("/" + os.sep) or folder      # (the root of a Unix disk is "/": stripped, it would be nothing)
    if not os.path.isdir(old):
        raise FolderError("That folder is not there any more.")
    if os.path.dirname(old.replace("/", os.sep)) == old.replace("/", os.sep) or not os.path.basename(old.replace("/", os.sep)):
        raise FolderError("A whole drive cannot be renamed here.")
    target = sibling(old, new_name)
    if target == old:
        raise FolderError("That is the name it has already.")
    if os.path.exists(target) and flat(target) != flat(old):
        raise FolderError(f"There is a folder called \"{new_name}\" there already.")
    return target


def rename_folder(folder: str, new_name: str) -> str:
    """Give `folder` another name where it is, and say its new path (see plan_rename)."""
    target = plan_rename(folder, new_name)
    old = folder.rstrip("/" + os.sep)
    try:
        os.rename(old, target)
    except OSError as exc:
        raise FolderError(f"The folder could not be renamed: {exc.strerror or exc}. Is a photo from it open in another program?") from exc
    return target


def plan_move(folder: str, into: str) -> str:
    """Where `folder` would be when it is moved into the folder `into` - or a FolderError saying why it cannot be. Nothing is changed. A folder cannot go into itself or into a folder
    inside it, cannot replace a folder of the same name, and has to stay on the same drive (a move to another drive would be a copy and then a delete, which is left to File Explorer)."""
    old = folder.rstrip("/" + os.sep) or folder
    if not os.path.isdir(old):
        raise FolderError("That folder is not there any more.")
    if not into or not os.path.isdir(into):
        raise FolderError("The folder to move it into is not there any more.")
    name = os.path.basename(old.replace("/", os.sep))
    if not name:
        raise FolderError("A whole drive cannot be moved.")
    if is_inside(into, old):
        raise FolderError("A folder cannot be moved into itself or into a folder inside it.")
    if norm(os.path.dirname(old.replace("/", os.sep))) == norm(into):
        raise FolderError(f"\"{name}\" is already in that folder.")
    if os.path.splitdrive(os.path.abspath(old))[0].lower() != os.path.splitdrive(os.path.abspath(into))[0].lower():
        raise FolderError("That folder is on another drive. Moving it there means copying every photo and deleting the originals, which EFAS leaves to File Explorer; "
                          "move it there, then add the new place to the Library with the + button.")
    target = os.path.join(into, name)
    if os.path.exists(target):
        raise FolderError(f"There is a folder called \"{name}\" in that folder already.")
    return target


def move_folder(folder: str, into: str) -> str:
    """Move `folder` into the folder `into` and say its new path (see plan_move)."""
    target = plan_move(folder, into)
    try:
        os.rename(folder.rstrip("/" + os.sep), target)
    except OSError as exc:
        raise FolderError(f"The folder could not be moved: {exc.strerror or exc}. Is a photo from it open in another program?") from exc
    return target


def remap(path: str, old: str, new: str) -> str:
    """`path` after the folder `old` became `new`: a path in it is given the new folder in place of the old one, any other path comes back as it was.
    A path is not respelled when only the last name of the folder changed (so each photo keeps the way its own path was written)."""
    old_s = old.rstrip("/" + os.sep)
    if not path or not old_s:
        return path
    here, there = flat(path), flat(old_s)
    if here != there and not here.startswith(there + os.sep):
        return path
    new_s = new.rstrip("/" + os.sep)
    last_old, last_new = os.path.basename(old_s.replace("/", os.sep)), os.path.basename(new_s.replace("/", os.sep))
    if flat(sibling(old_s, last_new)) == flat(new_s):
        return path[: len(old_s) - len(last_old)] + last_new + path[len(old_s):]
    return new_s + path[len(old_s):]


def remap_all(paths: list[str], old: str, new: str) -> list[str]:
    return [remap(p, old, new) for p in paths]


def _entries(folder: str):
    try:
        with os.scandir(folder) as it:
            yield from list(it)
    except OSError:
        return


def summarise(folder: str, limit: int = 200000) -> FolderSummary:
    """What a folder holds, for the confirmation before it is deleted: photos and their size, folders in it, and other files (which would go with it)."""
    photos = size = folders = others = 0
    names: list[str] = []
    stack = [folder]
    seen = 0
    while stack and seen < limit:
        here = stack.pop()
        for entry in _entries(here):
            seen += 1
            try:
                if entry.is_dir(follow_symlinks=False):
                    folders += 1
                    if len(names) < 6 and here == folder:
                        names.append(entry.name)
                    stack.append(entry.path)
                elif os.path.splitext(entry.name)[1].lower() in SUPPORTED_EXTS:
                    photos += 1
                    size += entry.stat().st_size
                elif any(entry.name.lower().endswith(s) for s in SIDECAR_SUFFIXES):
                    continue
                else:
                    others += 1
            except OSError:
                continue
    return FolderSummary(photos, size, folders, others, tuple(names))


def photos_under(folder: str) -> list[str]:
    """Every photo in the folder, at any depth."""
    out: list[str] = []
    stack = [folder]
    while stack:
        here = stack.pop()
        for entry in _entries(here):
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
                elif os.path.splitext(entry.name)[1].lower() in SUPPORTED_EXTS:
                    out.append(entry.path)
            except OSError:
                continue
    return sorted(out)


def check_deletable(folder: str, protected: list[str] = ()) -> None:
    """Raise a FolderError unless this folder may be sent to the Recycle Bin: it must be a real folder (not a link), not a whole drive, and neither a protected folder nor one that holds one."""
    if not folder or not os.path.isdir(folder):
        raise FolderError("That folder is not there any more.")
    if os.path.islink(folder) or _is_junction(folder):
        raise FolderError("That folder is a link to another place, and EFAS does not delete links.")
    clean = folder.rstrip("/" + os.sep)
    if os.path.dirname(clean.replace("/", os.sep)) == clean.replace("/", os.sep) or not os.path.basename(clean.replace("/", os.sep)):
        raise FolderError("A whole drive cannot be deleted here.")
    for keep in protected:
        if keep and (is_inside(keep, folder) or is_inside(folder, keep)):
            raise FolderError("EFAS keeps its own data in a folder that includes this one, so it is not deleted.")


def _is_junction(path: str) -> bool:
    try:
        return bool(os.path.isjunction(path))   # Python 3.12+
    except AttributeError:
        return False


def delete_folder(folder: str, trasher=None, protected: list[str] = ()) -> None:
    """Send the folder, and everything in it, to the Recycle Bin. TrashUnavailable when there is no Recycle Bin to use; FolderError when it could not be done (the folder is
    then still where it was)."""
    check_deletable(folder, protected)
    trasher = trasher or send_to_trash
    try:
        trasher(folder)
    except TrashUnavailable:
        raise
    except OSError as exc:
        raise FolderError(f"The folder could not be moved to the Recycle Bin: {exc}") from exc
    if os.path.exists(folder):
        raise FolderError("The folder is still where it was; nothing was deleted.")


def hidden_under(hidden: list[str], folder: str) -> list[str]:
    """The hidden folders that are `folder` or inside it."""
    return [h for h in hidden if is_inside(h, folder)]


def without_inside(folders: list[str], folder: str) -> list[str]:
    """`folders` without the ones that are `folder` or inside it."""
    return [f for f in folders if not is_inside(f, folder)]
