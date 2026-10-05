"""The library index - one searchable record per photo under the library folders, kept in a small SQLite file. No Qt imports.

What the Lighttable view searches and sorts on - when a photo was taken, which camera and lens, ISO, size - is read from each file's own EXIF
once and remembered, so opening the Lighttable on thousands of photos is instant instead of re-reading every file. Only new or changed
files (by size and modification time) are read again. The things the editor itself keeps - ratings, flags, edits, Roll Cards - are not
copied here; they are joined in when the Lighttable asks (see query.py)."""

import os
import sqlite3
from datetime import datetime
from typing import Iterable, Iterator

from ..datadir import app_data_dir
from ..open_image.logic import SUPPORTED_EXTS

_SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    path TEXT PRIMARY KEY,
    folder TEXT NOT NULL,
    name TEXT NOT NULL,
    ext TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    taken TEXT NOT NULL,        -- 'YYYY-MM-DD HH:MM:SS': the EXIF capture time, else the file's modification time
    taken_exif INTEGER NOT NULL, -- 1 when 'taken' came from the EXIF
    make TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    camera TEXT NOT NULL DEFAULT '',
    lens TEXT NOT NULL DEFAULT '',
    iso INTEGER NOT NULL DEFAULT 0,
    focal REAL NOT NULL DEFAULT 0,
    aperture REAL NOT NULL DEFAULT 0,
    shutter TEXT NOT NULL DEFAULT '',
    width INTEGER NOT NULL DEFAULT 0,
    height INTEGER NOT NULL DEFAULT 0
)
"""
_COLUMNS = ("path", "folder", "name", "ext", "size", "mtime_ns", "taken", "taken_exif", "make", "model", "camera", "lens", "iso", "focal",
            "aperture", "shutter", "width", "height")
_SKIP_DIRS = {"$recycle.bin", "system volume information", "__pycache__"}


def default_db_path() -> str:
    return os.path.join(app_data_dir(), "library_index.db")


def connect(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or default_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(_SCHEMA)
    conn.execute("CREATE INDEX IF NOT EXISTS images_folder ON images(folder)")
    return conn


def scan_files(roots: Iterable[str]) -> Iterator[tuple[str, int, int]]:
    """Every photo under the roots, recursively: (path, size, mtime_ns). Each file is listed once even if roots overlap."""
    seen: set[str] = set()
    stack = [r for r in roots if r and os.path.isdir(r)]  # the roots as given: the editor's own tables key photos by these same spellings
    while stack:
        folder = stack.pop()
        key = os.path.normcase(folder)
        if key in seen:
            continue
        seen.add(key)
        try:
            with os.scandir(folder) as it:
                entries = list(it)
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name.lower() not in _SKIP_DIRS and not entry.name.startswith("."):
                        stack.append(entry.path)
                elif os.path.splitext(entry.name)[1].lower() in SUPPORTED_EXTS and not entry.name.startswith("."):
                    st = entry.stat()
                    yield entry.path, st.st_size, st.st_mtime_ns
            except OSError:
                continue


def _num(value, default=0.0) -> float:
    try:
        if isinstance(value, tuple) and len(value) == 2:  # an EXIF rational
            return float(value[0]) / float(value[1]) if value[1] else default
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return default


def _text(value) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    return str(value or "").replace("\x00", "").strip()


def _shutter(seconds: float) -> str:
    if seconds <= 0:
        return ""
    return f"{seconds:.1f}s" if seconds >= 1 else f"1/{round(1 / seconds)}"


def _camera_name(make: str, model: str) -> str:
    if model and make and not model.lower().startswith(make.lower().split()[0]):
        return f"{make} {model}"
    return model or make


def read_record(path: str, size: int | None = None, mtime_ns: int | None = None) -> dict:
    """One photo's record. The EXIF is read from the file header only (a few milliseconds, RAW files included); a file without
    readable EXIF still gets a record, dated by its modification time."""
    if size is None or mtime_ns is None:
        st = os.stat(path)
        size, mtime_ns = st.st_size, st.st_mtime_ns
    name, ext = os.path.splitext(os.path.basename(path))
    rec = {
        "path": path, "folder": os.path.dirname(path), "name": name, "ext": ext.lower().lstrip("."), "size": int(size), "mtime_ns": int(mtime_ns),
        "taken": datetime.fromtimestamp(mtime_ns / 1e9).strftime("%Y-%m-%d %H:%M:%S"), "taken_exif": 0, "make": "", "model": "", "camera": "",
        "lens": "", "iso": 0, "focal": 0.0, "aperture": 0.0, "shutter": "", "width": 0, "height": 0,
    }
    try:
        from PIL import Image

        with Image.open(path) as img:
            rec["width"], rec["height"] = img.size
            exif = img.getexif()
            sub = exif.get_ifd(0x8769)  # the Exif sub-directory: capture details live there
            when = _text(sub.get(36867) or sub.get(36868) or exif.get(306))  # DateTimeOriginal, Digitized, DateTime
            try:
                rec["taken"] = datetime.strptime(when[:19], "%Y:%m:%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
                rec["taken_exif"] = 1
            except ValueError:
                pass
            rec["make"], rec["model"] = _text(exif.get(271)), _text(exif.get(272))
            rec["camera"] = _camera_name(rec["make"], rec["model"])
            rec["lens"] = _text(sub.get(42036))
            rec["iso"] = int(_num(sub.get(34855) if not isinstance(sub.get(34855), tuple) else sub.get(34855)[0]))
            rec["focal"] = round(_num(sub.get(37386)), 1)
            rec["aperture"] = round(_num(sub.get(33437)), 1)
            rec["shutter"] = _shutter(_num(sub.get(33434)))
    except Exception:
        pass  # a file Pillow cannot open still goes in, with what is known
    return rec


class LibraryIndex:
    """The SQLite index. One connection per thread: make one wherever it is used."""

    def __init__(self, db_path: str | None = None):
        self.conn = connect(db_path)

    def close(self) -> None:
        self.conn.close()

    def known(self) -> dict[str, tuple[int, int]]:
        return {p: (s, m) for p, s, m in self.conn.execute("SELECT path, size, mtime_ns FROM images")}

    def upsert(self, records: list[dict]) -> None:
        marks = ",".join("?" * len(_COLUMNS))
        self.conn.executemany(f"INSERT OR REPLACE INTO images ({','.join(_COLUMNS)}) VALUES ({marks})", [tuple(r[c] for c in _COLUMNS) for r in records])
        self.conn.commit()

    def remove(self, paths: Iterable[str]) -> int:
        paths = list(paths)
        for i in range(0, len(paths), 500):
            chunk = paths[i:i + 500]
            self.conn.execute(f"DELETE FROM images WHERE path IN ({','.join('?' * len(chunk))})", chunk)
        self.conn.commit()
        return len(paths)

    def all(self) -> list[dict]:
        cur = self.conn.execute(f"SELECT {','.join(_COLUMNS)} FROM images")
        return [dict(zip(_COLUMNS, row)) for row in cur]

    def under(self, roots: Iterable[str]) -> list[dict]:
        """The indexed photos inside any of the roots (folders)."""
        prefixes = [os.path.normcase(os.path.abspath(r)).rstrip("\\/") + os.sep for r in roots if r]
        return [r for r in self.all() if any(os.path.normcase(r["path"]).startswith(p) for p in prefixes)]

    def refresh(self, roots: Iterable[str], batch: int = 200, progress=None, cancelled=None) -> tuple[int, int, int]:
        """Bring the index up to date with the folders: new and changed files are read, vanished ones dropped. -> (added, changed, removed).
        progress(done, total, path) is called as files are read; cancelled() stops it early (what was read so far is kept)."""
        roots = [r for r in roots if r and os.path.isdir(r)]
        known = self.known()
        on_disk = {p: (s, m) for p, s, m in scan_files(roots)}
        todo = [p for p, sm in on_disk.items() if known.get(p) != sm]
        added = sum(1 for p in todo if p not in known)
        buffer: list[dict] = []
        for n, path in enumerate(todo):
            if cancelled is not None and cancelled():
                break
            try:
                buffer.append(read_record(path, *on_disk[path]))
            except OSError:
                continue
            if len(buffer) >= batch:
                self.upsert(buffer)
                buffer = []
            if progress is not None:
                progress(n + 1, len(todo), path)
        if buffer:
            self.upsert(buffer)
        # vanished files: indexed, under a root being refreshed, but no longer on disk
        norm_roots = [os.path.normcase(os.path.abspath(r)).rstrip("\\/") + os.sep for r in roots]
        gone = [p for p in known if p not in on_disk and any(os.path.normcase(p).startswith(r) for r in norm_roots)]
        removed = self.remove(gone) if gone and not (cancelled is not None and cancelled()) else 0
        return added, len(todo) - added, removed
