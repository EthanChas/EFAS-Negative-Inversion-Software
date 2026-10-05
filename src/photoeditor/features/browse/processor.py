"""Thin I/O wrapper around logic.py - the boundary where file/image decoding,
and the on-disk thumbnail cache, happen."""

import io
import os

import numpy as np
import rawpy
from PIL import Image

from ..negative.logic import ProcessMode, detect_process_mode, invert_negative
from ..open_image.logic import is_raw
from .logic import thumbnail_cache_key

_THUMB_QUALITY = 85


def _embedded_preview(path: str, max_dim: int):
    """The JPEG preview most RAW files carry inside them, decoded at about the size wanted - tens of milliseconds, where a demosaic takes
    most of a second. None when the file has none (or it cannot be read), and the caller falls back to decoding the RAW itself."""
    try:
        with rawpy.imread(path) as raw:
            thumb = raw.extract_thumb()
        if thumb.format != rawpy.ThumbFormat.JPEG:
            return None
        img = Image.open(io.BytesIO(thumb.data))
        img.draft("RGB", (max_dim * 2, max_dim * 2))  # the JPEG decoder can skip straight to a fraction of the size
        return img.convert("RGB")
    except Exception:
        return None


def make_thumbnail_bytes(path: str, max_dim: int = 200) -> bytes | None:
    """A small JPEG thumbnail of `path`, auto-inverted to a positive if it
    looks like a negative (matching the main editor's own auto-invert on
    open - see AppController.open_file) - so the grid shows photos, not
    raw orange-mask scans, the same reasoning as NegPy's own thumbnailer.
    None if the file is unreadable."""
    try:
        if is_raw(path):
            img = _embedded_preview(path, max_dim)
            if img is None:
                with rawpy.imread(path) as raw:
                    # half_size: a fast, low-detail decode is plenty for a
                    # thumbnail - a full demosaic here would make browsing a
                    # folder of RAWs noticeably slower for no visible benefit.
                    rgb = raw.postprocess(use_camera_wb=True, half_size=True, output_bps=8)
                img = Image.fromarray(rgb)
        else:
            img = Image.open(path).convert("RGB")

        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        pixels = np.array(img)
        if detect_process_mode(pixels) != ProcessMode.E6:
            pixels = invert_negative(pixels)
            img = Image.fromarray(pixels)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_THUMB_QUALITY)
        return buf.getvalue()
    except Exception:
        return None


def load_cached_thumbnail(cache_dir: str, path: str) -> bytes | None:
    """The cached JPEG bytes for `path`, if a cache entry for its current
    mtime/size already exists - None on any kind of miss."""
    cache_path = os.path.join(cache_dir, f"{thumbnail_cache_key(path)}.jpg")
    try:
        with open(cache_path, "rb") as f:
            return f.read()
    except OSError:
        return None


def save_cached_thumbnail(cache_dir: str, path: str, data: bytes) -> None:
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f"{thumbnail_cache_key(path)}.jpg")
    try:
        with open(cache_path, "wb") as f:
            f.write(data)
    except OSError:
        pass  # a thumbnail that fails to cache just regenerates next time


def _edited_cache_path(cache_dir: str, path: str) -> str:
    return os.path.join(cache_dir, f"{thumbnail_cache_key(path)}_edited.jpg")


def save_edited_thumbnail(cache_dir: str, path: str, pixels: np.ndarray, max_dim: int = 200) -> None:
    """Persists a thumbnail of the *edited* look (the live pipeline output),
    separate from the neutral cached one - so a folder's tiles keep showing
    each photo's edits after switching away and back, or restarting. Same
    mtime/size-keyed identity as the neutral cache, so replacing the source
    file drops it automatically."""
    try:
        os.makedirs(cache_dir, exist_ok=True)
        img = Image.fromarray(np.ascontiguousarray(pixels))
        img.thumbnail((max_dim, max_dim), Image.Resampling.BILINEAR)
        img.save(_edited_cache_path(cache_dir, path), format="JPEG", quality=_THUMB_QUALITY)
    except Exception:
        pass  # a thumbnail that fails to cache just shows the neutral one


def load_edited_thumbnail(cache_dir: str, path: str) -> bytes | None:
    try:
        with open(_edited_cache_path(cache_dir, path), "rb") as f:
            return f.read()
    except OSError:
        return None


def get_or_make_thumbnail_bytes(cache_dir: str | None, path: str, max_dim: int = 200) -> bytes | None:
    """The edited-look thumbnail if one was saved (see save_edited_thumbnail),
    else reads the on-disk cache first (keyed by thumbnail_cache_key, so a
    replaced file regenerates automatically) - this is the single biggest
    gap versus NegPy's own thumbnailer: without it, every folder open
    regenerates every thumbnail from scratch, RAW decode included."""
    if cache_dir:
        edited = load_edited_thumbnail(cache_dir, path)
        if edited is not None:
            return edited
        cached = load_cached_thumbnail(cache_dir, path)
        if cached is not None:
            return cached

    data = make_thumbnail_bytes(path, max_dim)
    if data is not None and cache_dir:
        save_cached_thumbnail(cache_dir, path, data)
    return data
