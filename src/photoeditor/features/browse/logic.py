"""Pure folder-scanning logic."""

import hashlib
import os

from ..open_image.logic import SUPPORTED_EXTS


def list_images_in_folder(folder: str) -> list[str]:
    """Every supported image file directly inside `folder` (standard images
    and RAW - the same formats File > Open Image accepts), sorted by name.
    One level deep, no recursion - "open this folder" is one roll, the same
    model NegPy uses for its own folder-load (its recursive walk is a
    separate, opt-in library-search feature this doesn't need)."""
    if not folder or not os.path.isdir(folder):
        return []
    paths = []
    for name in os.listdir(folder):
        ext = os.path.splitext(name)[1].lower()
        if ext in SUPPORTED_EXTS:
            paths.append(os.path.join(folder, name))
    paths.sort()
    return paths


def list_subfolders(folder: str) -> list[str]:
    """Immediate subdirectories of `folder`, sorted by name - for lazily
    populating a folder tree one level at a time, the same "read children
    only when expanded" approach NegPy's own LibraryTree uses rather than
    walking the whole tree upfront."""
    if not folder or not os.path.isdir(folder):
        return []
    try:
        subfolders = [
            os.path.join(folder, entry.name)
            for entry in os.scandir(folder)
            if entry.is_dir(follow_symlinks=False) and not entry.name.startswith(".")
        ]
    except OSError:
        return []
    subfolders.sort(key=str.lower)
    return subfolders


# How the Library lists its folders: key, name, (which fact it sorts on, newest/most first?).
SORT_MODES = (
    ("added", "As added"), ("name", "Name A-Z"), ("name_desc", "Name Z-A"), ("date_new", "Newest first"), ("date_old", "Oldest first"),
    ("count_most", "Most photos"), ("count_fewest", "Fewest photos"),
)
DEFAULT_SORT = "added"
_SORT_FACT = {  # mode: (fact, descending)
    "added": ("order", False), "name": ("name", False), "name_desc": ("name", True), "date_new": ("date", True), "date_old": ("date", False),
    "count_most": ("count", True), "count_fewest": ("count", False),
}


def sort_fact(mode: str) -> tuple[str, bool]:
    """(the fact a sort mode is about - "order", "name", "date" or "count" - and whether it runs from most to least); an unknown mode is "as added"."""
    return _SORT_FACT.get(mode, _SORT_FACT[DEFAULT_SORT])


def folder_stats(folder: str) -> tuple[int, int, float]:
    """(photos directly in the folder, subfolders, when its newest photo was last changed). The date is the newest photo's file time, or the folder's own when
    it holds no photos - the day the roll was last added to, which is what "newest first" should mean for a library of scanned rolls."""
    if not folder or not os.path.isdir(folder):
        return (0, 0, 0.0)
    images, subfolders, newest = 0, 0, 0.0
    try:
        for entry in os.scandir(folder):
            if entry.is_dir(follow_symlinks=False):
                if not entry.name.startswith("."):
                    subfolders += 1
            elif os.path.splitext(entry.name)[1].lower() in SUPPORTED_EXTS:
                images += 1
                try:
                    newest = max(newest, entry.stat().st_mtime)
                except OSError:
                    pass
        if not newest:
            newest = os.stat(folder).st_mtime
    except OSError:
        pass
    return (images, subfolders, newest)


def folder_counts(folder: str) -> tuple[int, int]:
    """(image count, subfolder count) directly inside `folder` - a single
    shallow scan, not a recursive walk, so showing this next to every node
    in a folder tree stays cheap regardless of how deep the tree goes."""
    if not folder or not os.path.isdir(folder):
        return (0, 0)
    images = 0
    subfolders = 0
    try:
        for entry in os.scandir(folder):
            if entry.is_dir(follow_symlinks=False):
                if not entry.name.startswith("."):
                    subfolders += 1
            elif os.path.splitext(entry.name)[1].lower() in SUPPORTED_EXTS:
                images += 1
    except OSError:
        return (0, 0)
    return (images, subfolders)


def thumbnail_cache_key(path: str) -> str:
    """A cache key that changes if the file is replaced (mtime/size), unlike
    NegPy's full content hash - cheap to compute for a folder of RAW files,
    at the cost of not tracking identity across a rename (not needed here,
    since nothing else is keyed off this file long-term)."""
    try:
        stat = os.stat(path)
        basis = f"{path}|{stat.st_mtime_ns}|{stat.st_size}"
    except OSError:
        basis = path
    return hashlib.sha1(basis.encode("utf-8", "surrogateescape")).hexdigest()
