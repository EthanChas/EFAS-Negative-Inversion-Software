"""Watching a folder for the photos that land in it while shooting (tethered, or copied in by hand) - no Qt.

Canon's EOS Utility (and the other tethering programs) save each frame into a folder, often into a sub-folder named for the day. The watch is told the folder, notes what is in it
already, and each time it is asked (poll) says which photos are new. A photo is reported once, when its file has stopped growing, so a RAW file that is still arriving over Wi-Fi
is not opened half-written."""
import os

from ..library.index import scan_files

SETTLE_POLLS = 2   # a file is complete when its size and time have not changed for this many polls in a row


def _key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


class LiveWatch:
    """The photos that appear in `folder` (and the folders inside it) after the watch began."""

    def __init__(self, folder: str, settle_polls: int = SETTLE_POLLS):
        self.folder = folder
        self._settle = max(1, settle_polls)
        self._seen: set[str] = {_key(path) for path, _size, _mtime in scan_files([folder])}   # what was there already is not news
        self._growing: dict[str, tuple[int, int, int]] = {}                                    # key -> (size, mtime_ns, polls it has stayed the same)

    def poll(self) -> list[str]:
        """The photos that are new and complete since the last poll, oldest first (so the newest is the last)."""
        ready: list[tuple[int, str]] = []
        present: set[str] = set()
        for path, size, mtime in scan_files([self.folder]):
            key = _key(path)
            if key in self._seen:
                continue
            present.add(key)
            before = self._growing.get(key)
            same = before[2] + 1 if before is not None and before[:2] == (size, mtime) else 0
            self._growing[key] = (size, mtime, same)
            if size > 0 and same >= self._settle:
                ready.append((mtime, path))
                self._seen.add(key)
        for key in list(self._growing):
            if key in self._seen or key not in present:   # reported, or it vanished (a temporary name that was renamed): stop tracking it
                del self._growing[key]
        return [path for _mtime, path in sorted(ready)]

    def pending(self) -> int:
        """How many new files are still arriving."""
        return len(self._growing)


def describe(paths: list[str]) -> str:
    """The status line for what just arrived."""
    if not paths:
        return ""
    last = os.path.basename(paths[-1])
    return f"Live: {last} arrived" if len(paths) == 1 else f"Live: {len(paths)} photos arrived, the newest is {last}"
