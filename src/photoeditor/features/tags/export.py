"""Keywords in an exported file - piexif only, no Qt imports."""

import os

_JPEG = (".jpg", ".jpeg")


def embed_keywords(dest_path: str, tags: list[str]) -> bool:
    """Write the tags into a JPEG as the EXIF XPKeywords field (what Windows shows as the file's Tags)."""
    if not tags or os.path.splitext(dest_path)[1].lower() not in _JPEG:
        return False
    try:
        import piexif

        exif = piexif.load(dest_path)
        exif["0th"][piexif.ImageIFD.XPKeywords] = tuple("; ".join(tags).encode("utf-16-le") + b"\x00\x00")
        piexif.insert(piexif.dump(exif), dest_path)
        return True
    except Exception:
        return False
