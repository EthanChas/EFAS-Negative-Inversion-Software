"""What tethered captures are called: a roll prefix and a frame number, the camera's own extension kept. No Qt.

A RAW and its JPEG from one shot share a frame number (scan_0007.CR3, scan_0007.JPG). The next number is found from what is already in the folder, so a roll can be picked up
again later, or from another computer, and never overwrite or repeat a frame."""

import os
import re

from .backend import TetherError

DEFAULT_PREFIX = "scan_"
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
DIGITS = 4


def clean_prefix(text: str) -> str:
    """The prefix as a file name can have it (no slashes or other characters Windows forbids), or the default when nothing is left."""
    cleaned = _BAD.sub("", (text or "").strip()).strip(". ")[:40]
    return cleaned or DEFAULT_PREFIX


def next_frame(folder: str, prefix: str) -> int:
    """One more than the highest frame number already in `folder` under `prefix` (1 for an empty folder)."""
    prefix = clean_prefix(prefix)
    pattern = re.compile(re.escape(prefix) + r"(\d+)", re.IGNORECASE)
    highest = 0
    try:
        names = os.listdir(folder)
    except OSError:
        return 1
    for name in names:
        m = pattern.match(os.path.splitext(name)[0])
        if m:
            highest = max(highest, int(m.group(1)))
    return highest + 1


def unique_path(folder: str, name: str) -> str:
    """folder/name, or the first of name-1, name-2... that is free: a capture is the one thing that cannot be made again."""
    path = os.path.join(folder, name)
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(name)
    for n in range(1, 10000):
        candidate = os.path.join(folder, f"{stem}-{n}{ext}")
        if not os.path.exists(candidate):
            return candidate
    raise TetherError(f"No free file name was found beside {path}.")


def file_name(prefix: str, frame: int, camera_name: str) -> str:
    """The name to save a file the camera called `camera_name` under, for this frame: prefix, number, and the camera's own extension."""
    return f"{clean_prefix(prefix)}{frame:0{DIGITS}d}{os.path.splitext(camera_name)[1]}"
