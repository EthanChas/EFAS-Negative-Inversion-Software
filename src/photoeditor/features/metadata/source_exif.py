"""EXIF of a source file as a piexif-format dict - no Qt imports."""

import copy
import os
from typing import Optional

_CACHE_MAX = 64
_cache: dict[str, tuple[int, int, Optional[dict]]] = {}


def read_exif_from_file(file_path: str) -> Optional[dict]:
    """None when the file has no readable EXIF. The caller gets its own copy, so mutating it never leaks into a later read."""
    try:
        st = os.stat(file_path)
    except OSError:
        return _read_uncached(file_path)
    hit = _cache.get(file_path)
    if hit is None or hit[0] != st.st_mtime_ns or hit[1] != st.st_size:
        if len(_cache) >= _CACHE_MAX:
            _cache.clear()
        hit = (st.st_mtime_ns, st.st_size, _read_uncached(file_path))
        _cache[file_path] = hit
    return copy.deepcopy(hit[2])


def _read_uncached(file_path: str) -> Optional[dict]:
    import piexif

    try:
        return piexif.load(file_path)
    except Exception:
        pass
    try:
        from PIL import Image

        with Image.open(file_path) as img:
            exif_bytes = img.info.get("exif")
            if exif_bytes:
                return piexif.load(exif_bytes)
    except Exception:
        pass
    try:
        from .jxl_boxes import is_jxl, read_jxl_exif

        with open(file_path, "rb") as fh:
            data = fh.read()
        if is_jxl(data):
            exif_bytes = read_jxl_exif(data)
            if exif_bytes:
                return piexif.load(exif_bytes)
    except Exception:
        pass
    return None
