"""Pure file-type logic for single-file open."""

import os

STANDARD_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp", ".heic", ".heif"}
RAW_EXTS = {
    ".cr2", ".cr3", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".dng",
    ".raf", ".rw2", ".orf", ".pef", ".srw", ".raw", ".x3f",
}
SUPPORTED_EXTS = STANDARD_EXTS | RAW_EXTS


def is_raw(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in RAW_EXTS


def is_ls600(path: str) -> bool:
    """Whether `path` is a Noritsu LS-600 scanner dump (a headerless .raw: features/open_image/ls600raw.py), which RAW decoding cannot read."""
    from .ls600raw import is_ls600_raw

    return is_ls600_raw(path)


def source_encoding(path: str) -> str | None:
    """How a file's codes were made from light, when the file says so (see Metering.transfer): an LS-600 dump holds the scanner's linear light. None for the rest, which are read by the
    usual rule (RAW decoded by EFAS: BT.709, anything else: sRGB)."""
    return "linear" if path and is_ls600(path) else None


def is_supported(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in SUPPORTED_EXTS


def file_dialog_filter() -> str:
    """A Qt QFileDialog-style filter string listing every supported extension."""
    patterns = " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTS))
    return f"Images and RAW files ({patterns})"
