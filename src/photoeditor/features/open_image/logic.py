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


def is_supported(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in SUPPORTED_EXTS


def file_dialog_filter() -> str:
    """A Qt QFileDialog-style filter string listing every supported extension."""
    patterns = " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTS))
    return f"Images and RAW files ({patterns})"
