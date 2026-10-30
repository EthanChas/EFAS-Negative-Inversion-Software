"""Thin I/O wrapper around logic.py - the boundary where file/image decoding,
and the on-disk thumbnail cache, happen."""

import io
import os
import time

import numpy as np
import rawpy
from PIL import Image

from ..negative import printengine
from ..negative.logic import ProcessMode, detect_process_mode
from ..open_image import ls600raw
from ..open_image.logic import is_ls600, is_raw
from .logic import thumbnail_cache_key

_THUMB_QUALITY = 85
THUMB_ATTEMPTS = 3        # a picture that cannot be read is tried this many times...
THUMB_RETRY_WAIT_S = 0.6  # ...with this long between, before its tile is left blank
_NEUTRAL = "_modern"   # a neutral thumbnail's file-name tag: they used to be made with the Original conversion, and those are not reused


def _embedded_preview(path: str, max_dim: int):
    """The JPEG preview most RAW files carry inside them, decoded at about the size wanted - tens of milliseconds, where a demosaic takes
    most of a second. None when the file has none (or it cannot be read), and the caller falls back to decoding the RAW itself."""
    try:
        with rawpy.imread(path) as raw:
            thumb = raw.extract_thumb()
        if thumb.format != rawpy.ThumbFormat.JPEG:
            return None
        img = Image.open(io.BytesIO(thumb.data))
        img.draft("RGB", (max_dim * 2, max_dim * 2))
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
        transfer = "srgb"   # how the pixels were encoded: a camera's JPEG preview and an ordinary picture are sRGB
        if is_ls600(path):      # a Noritsu LS-600 dump: linear light, read whole and shrunk
            import cv2

            full = ls600raw.load_rgb16(path)
            scale = max_dim / max(full.shape[:2])
            img = Image.fromarray(np.clip(np.rint(cv2.resize(full, (max(1, round(full.shape[1] * scale)), max(1, round(full.shape[0] * scale))), interpolation=cv2.INTER_AREA) / 257.0), 0, 255).astype(np.uint8))
            transfer = "linear"
        elif is_raw(path):
            img = _embedded_preview(path, max_dim)
            if img is None:
                with rawpy.imread(path) as raw:
                    rgb = raw.postprocess(use_camera_wb=True, half_size=True, output_bps=8)
                img = Image.fromarray(rgb)
                transfer = "bt709"   # libraw's own curve, which is what the editor's RAW decode carries too
        else:
            img = Image.open(path).convert("RGB")

        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        pixels = np.array(img)
        if detect_process_mode(pixels) != ProcessMode.E6:
            pixels = printengine.convert(pixels, printengine.Settings(transfer=transfer))   # the conversion the editor starts a photo with, so a tile matches what opening it shows
            img = Image.fromarray(pixels)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_THUMB_QUALITY)
        return buf.getvalue()
    except Exception:
        return None


def load_cached_thumbnail(cache_dir: str, path: str) -> bytes | None:
    """The cached JPEG bytes for `path`, if a cache entry for its current
    mtime/size already exists - None on any kind of miss."""
    cache_path = os.path.join(cache_dir, f"{thumbnail_cache_key(path)}{_NEUTRAL}.jpg")
    try:
        with open(cache_path, "rb") as f:
            return f.read()
    except OSError:
        return None


def save_cached_thumbnail(cache_dir: str, path: str, data: bytes) -> None:
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f"{thumbnail_cache_key(path)}{_NEUTRAL}.jpg")
    try:
        with open(cache_path, "wb") as f:
            f.write(data)
    except OSError:
        pass


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
        pass


def load_edited_thumbnail(cache_dir: str, path: str) -> bytes | None:
    try:
        with open(_edited_cache_path(cache_dir, path), "rb") as f:
            return f.read()
    except OSError:
        return None


def put_edited_thumbnail(cache_dir: str, path: str, data: bytes) -> None:
    """Keep an edited-look thumbnail (as load_edited_thumbnail read it) for a photo that was moved to this path."""
    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(_edited_cache_path(cache_dir, path), "wb") as f:
            f.write(data)
    except OSError:
        pass


def forget_edited_thumbnail(cache_dir: str, path: str) -> None:
    """Drop the edited-look thumbnail (the photo's crop or edits changed behind the editor's back); the plain one shows until the photo is opened again."""
    try:
        os.remove(_edited_cache_path(cache_dir, path))
    except OSError:
        pass


def get_thumbnail_with_retry(cache_dir: str | None, path: str, max_dim: int = 200) -> bytes | None:
    """get_or_make_thumbnail_bytes, trying again a moment later when the picture could not be read. A file that has only just been moved, copied or written is often still held by
    something else for a second (the camera's software, a virus scan, the indexer) and cannot be opened yet; reading it once and giving up left its tile blank until the photo was opened.
    Meant for a worker thread: it waits."""
    for attempt in range(max(1, THUMB_ATTEMPTS)):
        data = get_or_make_thumbnail_bytes(cache_dir, path, max_dim)
        if data is not None or not os.path.isfile(path):
            return data
        if attempt + 1 < THUMB_ATTEMPTS:
            time.sleep(THUMB_RETRY_WAIT_S)
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
