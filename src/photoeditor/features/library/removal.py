"""Taking photos out of the Workbench (they stay on disk) and deleting them from disk (to the Recycle Bin, never permanently). No Qt imports.

Hiding a photo only records its path; nothing about the file or its edits changes, and it can be brought back. Deleting moves the file, and the
sidecar files EFAS wrote for it, to the Recycle Bin. If that cannot be done the file is left where it is: there is no permanent-delete fallback.
"""

import os
import sys
from dataclasses import dataclass, field

from ..open_image.logic import SUPPORTED_EXTS

SIDECAR_SUFFIXES = (".xmp", ".efas-merge.json")


class TrashUnavailable(RuntimeError):
    """The Recycle Bin cannot be used on this system."""


@dataclass
class DeleteResult:
    deleted: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


@dataclass(frozen=True)
class Summary:
    count: int
    bytes: int
    names: tuple
    folders: tuple
    missing: int


def deletable(path: str) -> bool:
    """Only an existing photo file is ever deleted: never a folder, never another kind of file."""
    return os.path.isfile(path) and os.path.splitext(path)[1].lower() in SUPPORTED_EXTS


def sidecars(path: str) -> list[str]:
    return [path + s for s in SIDECAR_SUFFIXES if os.path.isfile(path + s)]


def summarise(paths: list[str]) -> Summary:
    """What a deletion would take: how many photos, how big, which ones (for the confirmation)."""
    unique = list(dict.fromkeys(paths))
    present = [p for p in unique if deletable(p)]
    size = 0
    for p in present:
        try:
            size += os.path.getsize(p)
        except OSError:
            pass
    return Summary(len(present), size, tuple(os.path.basename(p) for p in present),
                   tuple(dict.fromkeys(os.path.dirname(p) for p in present)), len(unique) - len(present))


def human_size(n: int) -> str:
    value = float(n)
    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1000 or unit == "GB":
            return f"{int(value)} bytes" if unit == "bytes" else f"{value:.1f} {unit}"
        value /= 1000
    return f"{n} bytes"


def _windows_trash(path: str) -> None:
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort),
                    ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE, FOF_SILENT, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x40, 0x400
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = os.path.abspath(path) + "\0"
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_SILENT | FOF_NOERRORUI
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if code != 0 or op.fAnyOperationsAborted:
        raise OSError(f"Windows could not move the file to the Recycle Bin (code {code}).")


def send_to_trash(path: str) -> None:
    """Move one file to the Recycle Bin / Trash. Raises TrashUnavailable if there is no way to do that, OSError if it fails."""
    if sys.platform == "win32":
        _windows_trash(path)
        return
    try:
        from send2trash import send2trash
    except ImportError as exc:
        raise TrashUnavailable("This system has no Recycle Bin support available to EFAS, so nothing was deleted.") from exc
    send2trash(path)


def delete_photos(paths: list[str], trasher=None) -> DeleteResult:
    """Move each photo (and its EFAS sidecars) to the Recycle Bin. A photo counts as deleted only once it is really gone from its folder."""
    trasher = trasher or send_to_trash
    result = DeleteResult()
    for path in dict.fromkeys(paths):
        if not deletable(path):
            result.skipped.append(path)
            continue
        try:
            for extra in sidecars(path):
                trasher(extra)
            trasher(path)
        except TrashUnavailable:
            raise
        except OSError as exc:
            result.failed.append((path, str(exc)))
            continue
        if os.path.exists(path):
            result.failed.append((path, "The file is still in its folder."))
        else:
            result.deleted.append(path)
    return result
