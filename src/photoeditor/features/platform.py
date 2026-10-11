"""What differs between Windows, macOS and Linux, in one place. No Qt imports."""

import sys

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
LINUX = sys.platform.startswith("linux")


def pick(windows, mac, linux):
    """The value for the running system (Linux's is also used for other Unix-like systems)."""
    return windows if WINDOWS else mac if MACOS else linux


def reveal_command(path: str) -> list[str] | None:
    """The command that opens the system file manager with `path` selected, or None when this system has no such command (the caller opens the folder instead)."""
    import os

    if WINDOWS:
        return ["explorer", "/select,", os.path.normpath(path)]
    if MACOS:
        return ["open", "-R", path]
    return None
