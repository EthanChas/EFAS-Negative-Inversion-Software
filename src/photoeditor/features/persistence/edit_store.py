"""Pure sqlite3 I/O for persisting per-image edit state across app
restarts - no Qt imports, just a db file path and plain dicts in/out.

One row per file path (not NegPy's content-hash keying - consistent with
the simpler, mtime/size-based identity this app already uses for the
thumbnail cache; renaming a file loses its saved edits, which is an
accepted trade for not having to hash every file on open)."""

import json
import os
import sqlite3

import numpy as np

_SCHEMA = """
CREATE TABLE IF NOT EXISTS edits (
    path TEXT PRIMARY KEY,
    exposure_ev REAL NOT NULL,
    tone_curve_points TEXT NOT NULL,
    negative_inverted INTEGER NOT NULL,
    rotation_quarter_turns INTEGER NOT NULL,
    flip_h INTEGER NOT NULL,
    flip_v INTEGER NOT NULL,
    crop_rect TEXT,
    saturation REAL NOT NULL,
    temperature REAL NOT NULL,
    tint REAL NOT NULL,
    shadows REAL NOT NULL DEFAULT 0.0,
    highlights REAL NOT NULL DEFAULT 0.0,
    sharpen_amount REAL NOT NULL DEFAULT 0.0,
    sharpen_radius REAL NOT NULL DEFAULT 1.0,
    sharpen_masking REAL NOT NULL DEFAULT 0.0,
    sharpen_method TEXT NOT NULL DEFAULT 'usm',
    dust_auto INTEGER NOT NULL DEFAULT 0,
    dust_threshold REAL NOT NULL DEFAULT 0.66,
    dust_size INTEGER NOT NULL DEFAULT 4,
    scratch_lines TEXT NOT NULL DEFAULT '[]',
    scratch_sensitivity REAL NOT NULL DEFAULT 0.5,
    heal_strokes TEXT NOT NULL DEFAULT '[]',
    film_type TEXT NOT NULL DEFAULT 'auto',
    invert_r REAL NOT NULL DEFAULT 0.0,
    invert_g REAL NOT NULL DEFAULT 0.0,
    invert_b REAL NOT NULL DEFAULT 0.0,
    contrast REAL NOT NULL DEFAULT 0.0,
    fine_rotation REAL NOT NULL DEFAULT 0.0,
    distortion REAL NOT NULL DEFAULT 0.0,
    chroma_denoise REAL NOT NULL DEFAULT 0.0,
    wm_film TEXT NOT NULL DEFAULT 'off',
    wm_texture TEXT NOT NULL DEFAULT 'plastic',
    wm_size TEXT NOT NULL DEFAULT 'medium',
    wm_position TEXT NOT NULL DEFAULT 'bottom_right',
    wm_info INTEGER NOT NULL DEFAULT 0,
    wm_camera TEXT NOT NULL DEFAULT '',
    wm_lens TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
)
"""

_FLAGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS flags (
    path TEXT PRIMARY KEY,
    flag TEXT NOT NULL
)
"""

_FLATFIELD_SCHEMA = """
CREATE TABLE IF NOT EXISTS folder_flatfield (
    folder TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT '',
    height INTEGER NOT NULL,
    width INTEGER NOT NULL,
    gain BLOB NOT NULL
)
"""

_ROLL_SCHEMA = """
CREATE TABLE IF NOT EXISTS folder_roll (
    folder TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_RATINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ratings (
    path TEXT PRIMARY KEY,
    rating INTEGER NOT NULL
)
"""

_TAGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tags (
    path TEXT NOT NULL,
    tag TEXT NOT NULL COLLATE NOCASE,
    PRIMARY KEY (path, tag)
)
"""
_TAGS_INDEX = "CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags (tag)"

_SNAPSHOTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    path TEXT NOT NULL,
    name TEXT NOT NULL COLLATE NOCASE,
    state TEXT NOT NULL,
    created TEXT NOT NULL,
    PRIMARY KEY (path, name)
)
"""

_BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS folder_base (
    folder TEXT PRIMARY KEY,
    r INTEGER NOT NULL,
    g INTEGER NOT NULL,
    b INTEGER NOT NULL
)
"""

FLAG_KEEPER = "keeper"
FLAG_REJECTED = "rejected"

_MIGRATIONS = (
    ("shadows", "REAL", "0.0"),
    ("highlights", "REAL", "0.0"),
    ("sharpen_amount", "REAL", "0.0"),
    ("sharpen_radius", "REAL", "1.0"),
    ("sharpen_masking", "REAL", "0.0"),
    ("sharpen_method", "TEXT", "'usm'"),
    ("dust_auto", "INTEGER", "0"),
    ("dust_threshold", "REAL", "0.66"),
    ("dust_size", "INTEGER", "4"),
    ("scratch_lines", "TEXT", "'[]'"),
    ("scratch_sensitivity", "REAL", "0.5"),
    ("heal_strokes", "TEXT", "'[]'"),
    ("clone_strokes", "TEXT", "'[]'"),
    ("ai_dust", "INTEGER", "0"),
    ("ai_threshold", "REAL", "0.3"),
    ("ai_grow", "INTEGER", "1"),
    ("marks", "TEXT", "'{}'"),
    ("film_type", "TEXT", "'auto'"),
    ("invert_r", "REAL", "0.0"),
    ("invert_g", "REAL", "0.0"),
    ("invert_b", "REAL", "0.0"),
    ("contrast", "REAL", "0.0"),
    ("fine_rotation", "REAL", "0.0"),
    ("distortion", "REAL", "0.0"),
    ("chroma_denoise", "REAL", "0.0"),
    ("local_contrast", "REAL", "0.0"),
    ("vignette", "REAL", "0.0"),
    ("vignette_size", "REAL", "0.5"),
    ("border", "REAL", "0.0"),
    ("border_color", "TEXT", "'white'"),
    ("carrier", "INTEGER", "0"),
    ("metering", "TEXT", "'{}'"),
    ("wm_film", "TEXT", "'off'"),
    ("wm_texture", "TEXT", "'plastic'"),
    ("wm_size", "TEXT", "'medium'"),
    ("wm_position", "TEXT", "'bottom_right'"),
    ("wm_info", "INTEGER", "0"),
    ("wm_camera", "TEXT", "''"),
    ("wm_lens", "TEXT", "''"),
    ("metadata", "TEXT", "'{}'"),
    ("module_presets", "TEXT", "'{}'"),
)

_FIELDS = (
    ("exposure_ev", "plain"),
    ("tone_curve_points", "json"),
    ("negative_inverted", "bool"),
    ("rotation_quarter_turns", "plain"),
    ("flip_h", "bool"),
    ("flip_v", "bool"),
    ("crop_rect", "json_null"),
    ("saturation", "plain"),
    ("temperature", "plain"),
    ("tint", "plain"),
    ("shadows", "plain"),
    ("highlights", "plain"),
    ("sharpen_amount", "plain"),
    ("sharpen_radius", "plain"),
    ("sharpen_masking", "plain"),
    ("sharpen_method", "plain"),
    ("dust_auto", "bool"),
    ("dust_threshold", "plain"),
    ("dust_size", "plain"),
    ("scratch_lines", "json"),
    ("scratch_sensitivity", "plain"),
    ("heal_strokes", "json"),
    ("clone_strokes", "json"),
    ("ai_dust", "bool"),
    ("ai_threshold", "plain"),
    ("ai_grow", "plain"),
    ("marks", "json"),
    ("film_type", "plain"),
    ("invert_r", "plain"),
    ("invert_g", "plain"),
    ("invert_b", "plain"),
    ("contrast", "plain"),
    ("fine_rotation", "plain"),
    ("distortion", "plain"),
    ("chroma_denoise", "plain"),
    ("local_contrast", "plain"),
    ("vignette", "plain"),
    ("vignette_size", "plain"),
    ("border", "plain"),
    ("border_color", "plain"),
    ("carrier", "bool"),
    ("metering", "json"),
    ("wm_film", "plain"),
    ("wm_texture", "plain"),
    ("wm_size", "plain"),
    ("wm_position", "plain"),
    ("wm_info", "bool"),
    ("wm_camera", "plain"),
    ("wm_lens", "plain"),
    ("metadata", "json"),
    ("module_presets", "json"),
)


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(_SCHEMA)
    conn.execute(_FLAGS_SCHEMA)
    conn.execute(_FLATFIELD_SCHEMA)
    conn.execute(_ROLL_SCHEMA)
    conn.execute(_RATINGS_SCHEMA)
    conn.execute(_BASE_SCHEMA)
    conn.execute(_TAGS_SCHEMA)
    conn.execute(_TAGS_INDEX)
    conn.execute(_SNAPSHOTS_SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(edits)")}
    for column, sql_type, default in _MIGRATIONS:
        if column not in existing:
            conn.execute(f"ALTER TABLE edits ADD COLUMN {column} {sql_type} NOT NULL DEFAULT {default}")


def _encode(value, kind: str):
    if kind == "bool":
        return int(value)
    if kind == "json":
        return json.dumps(value)
    if kind == "json_null":
        return json.dumps(value) if value is not None else None
    return value


def _decode(value, kind: str, field: str):
    if kind == "bool":
        return bool(value)
    if kind == "json_null":
        return tuple(json.loads(value)) if value else None
    if kind == "json":
        data = json.loads(value)
        if field == "tone_curve_points":
            return [tuple(p) for p in data]
        if field == "scratch_lines":
            return [tuple(line) for line in data]
        return data
    return value


def save_edit_state(conn: sqlite3.Connection, path: str, state: dict) -> None:
    names = [name for name, _ in _FIELDS]
    state = {"module_presets": {}, **state}
    values = [_encode(state[name], kind) for name, kind in _FIELDS]
    marks = ", ".join("?" * (len(names) + 1))
    updates = ", ".join(f"{name}=excluded.{name}" for name in names)
    conn.execute(
        f"""
        INSERT INTO edits (path, {", ".join(names)}, updated_at)
        VALUES ({marks}, datetime('now'))
        ON CONFLICT(path) DO UPDATE SET {updates}, updated_at=excluded.updated_at
        """,
        [path, *values],
    )
    conn.commit()


def load_edit_state(conn: sqlite3.Connection, path: str) -> dict | None:
    names = [name for name, _ in _FIELDS]
    row = conn.execute(f"SELECT {', '.join(names)} FROM edits WHERE path = ?", (path,)).fetchone()
    if row is None:
        return None
    return {name: _decode(value, kind, name) for (name, kind), value in zip(_FIELDS, row)}


def edited_paths(conn: sqlite3.Connection, paths: list[str]) -> set[str]:
    """Which of paths have a saved edit row (queried in chunks to stay under SQLite's variable limit)."""
    found: set[str] = set()
    for i in range(0, len(paths), 500):
        chunk = paths[i : i + 500]
        marks = ",".join("?" * len(chunk))
        found.update(row[0] for row in conn.execute(f"SELECT path FROM edits WHERE path IN ({marks})", chunk))
    return found


def set_flag(conn: sqlite3.Connection, path: str, flag: str | None) -> None:
    """flag is FLAG_KEEPER, FLAG_REJECTED, or None to clear the mark."""
    if flag is None:
        conn.execute("DELETE FROM flags WHERE path = ?", (path,))
    else:
        conn.execute(
            "INSERT INTO flags (path, flag) VALUES (?, ?) ON CONFLICT(path) DO UPDATE SET flag=excluded.flag",
            (path, flag),
        )
    conn.commit()


def get_flag(conn: sqlite3.Connection, path: str) -> str | None:
    row = conn.execute("SELECT flag FROM flags WHERE path = ?", (path,)).fetchone()
    return row[0] if row else None


def get_flags(conn: sqlite3.Connection, paths: list[str]) -> dict[str, str]:
    """{path: flag} for whichever of paths are marked (queried in chunks)."""
    found: dict[str, str] = {}
    for i in range(0, len(paths), 500):
        chunk = paths[i : i + 500]
        marks = ",".join("?" * len(chunk))
        found.update(conn.execute(f"SELECT path, flag FROM flags WHERE path IN ({marks})", chunk).fetchall())
    return found


def folder_key(path_or_folder: str, is_file: bool = True) -> str:
    """Normalized key for a folder (case-insensitive, like Windows paths)."""
    folder = os.path.dirname(path_or_folder) if is_file else path_or_folder
    return os.path.normcase(os.path.abspath(folder))


def set_folder_flatfield(conn: sqlite3.Connection, folder: str, gain: np.ndarray, source: str = "", enabled: bool = True) -> None:
    gain = np.ascontiguousarray(gain, dtype=np.float32)
    h, w = gain.shape[:2]
    conn.execute(
        """
        INSERT INTO folder_flatfield (folder, enabled, source, height, width, gain) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(folder) DO UPDATE SET enabled=excluded.enabled, source=excluded.source,
            height=excluded.height, width=excluded.width, gain=excluded.gain
        """,
        (folder, int(enabled), source, h, w, gain.tobytes()),
    )
    conn.commit()


def get_folder_flatfield(conn: sqlite3.Connection, folder: str) -> dict | None:
    """{"gain": (h, w, 3) float32, "enabled": bool, "source": str} or None."""
    row = conn.execute(
        "SELECT enabled, source, height, width, gain FROM folder_flatfield WHERE folder = ?", (folder,)
    ).fetchone()
    if row is None:
        return None
    enabled, source, h, w, blob = row
    try:
        gain = np.frombuffer(blob, dtype=np.float32).reshape(h, w, 3).copy()
    except ValueError:
        return None
    return {"gain": gain, "enabled": bool(enabled), "source": source}


def set_folder_flatfield_enabled(conn: sqlite3.Connection, folder: str, enabled: bool) -> None:
    conn.execute("UPDATE folder_flatfield SET enabled = ? WHERE folder = ?", (int(enabled), folder))
    conn.commit()


def delete_folder_flatfield(conn: sqlite3.Connection, folder: str) -> None:
    conn.execute("DELETE FROM folder_flatfield WHERE folder = ?", (folder,))
    conn.commit()


def get_folder_roll(conn: sqlite3.Connection, folder: str) -> dict | None:
    """The folder's Roll Card as a plain dict (see features/metadata/roll.py), or None."""
    row = conn.execute("SELECT data FROM folder_roll WHERE folder = ?", (folder,)).fetchone()
    if row is None:
        return None
    try:
        data = json.loads(row[0])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def set_folder_roll(conn: sqlite3.Connection, folder: str, data: dict) -> None:
    conn.execute(
        "INSERT INTO folder_roll (folder, data, updated_at) VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(folder) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
        (folder, json.dumps(data, ensure_ascii=False)),
    )
    conn.commit()


def delete_folder_roll(conn: sqlite3.Connection, folder: str) -> None:
    conn.execute("DELETE FROM folder_roll WHERE folder = ?", (folder,))
    conn.commit()


def list_folder_rolls(conn: sqlite3.Connection) -> list[tuple[str, dict]]:
    """Every saved Roll Card as (folder, dict), most recently changed first - for copying one onto another roll."""
    out = []
    for folder, raw in conn.execute("SELECT folder, data FROM folder_roll ORDER BY updated_at DESC"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            out.append((folder, data))
    return out


def set_rating(conn: sqlite3.Connection, path: str, rating: int) -> None:
    """rating 1-5; 0 clears it."""
    if rating <= 0:
        conn.execute("DELETE FROM ratings WHERE path = ?", (path,))
    else:
        conn.execute(
            "INSERT INTO ratings (path, rating) VALUES (?, ?) ON CONFLICT(path) DO UPDATE SET rating=excluded.rating",
            (path, min(5, int(rating))),
        )
    conn.commit()


def get_rating(conn: sqlite3.Connection, path: str) -> int:
    row = conn.execute("SELECT rating FROM ratings WHERE path = ?", (path,)).fetchone()
    return int(row[0]) if row else 0


def get_ratings(conn: sqlite3.Connection, paths: list[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for i in range(0, len(paths), 500):
        chunk = paths[i : i + 500]
        marks = ",".join("?" * len(chunk))
        found.update(conn.execute(f"SELECT path, rating FROM ratings WHERE path IN ({marks})", chunk).fetchall())
    return found


def state_to_json(state: dict) -> str:
    """An edit state (as AppController._edit_state_dict builds it) as one JSON text, each field encoded the way its column is."""
    state = {"module_presets": {}, **state}
    return json.dumps({name: _encode(state[name], kind) for name, kind in _FIELDS if name in state})


def state_from_json(text: str) -> dict:
    """The edit state a snapshot holds; a field it does not have (it was taken before the field existed) is simply missing."""
    raw = json.loads(text)
    return {name: _decode(raw[name], kind, name) for name, kind in _FIELDS if name in raw}


def save_snapshot(conn: sqlite3.Connection, path: str, name: str, state: dict) -> None:
    conn.execute(
        "INSERT INTO snapshots (path, name, state, created) VALUES (?, ?, ?, datetime('now', 'localtime')) "
        "ON CONFLICT(path, name) DO UPDATE SET state=excluded.state, created=excluded.created",
        (path, name, state_to_json(state)),
    )
    conn.commit()


def list_snapshots(conn: sqlite3.Connection, path: str) -> list[tuple[str, str]]:
    """(name, when taken) of a photo's snapshots, newest first."""
    return [(n, c) for n, c in conn.execute("SELECT name, created FROM snapshots WHERE path = ? ORDER BY created DESC, rowid DESC", (path,))]


def get_snapshot(conn: sqlite3.Connection, path: str, name: str) -> dict | None:
    row = conn.execute("SELECT state FROM snapshots WHERE path = ? AND name = ?", (path, name)).fetchone()
    return state_from_json(row[0]) if row else None


def delete_snapshot(conn: sqlite3.Connection, path: str, name: str) -> bool:
    cur = conn.execute("DELETE FROM snapshots WHERE path = ? AND name = ?", (path, name))
    conn.commit()
    return cur.rowcount > 0


def get_tags(conn: sqlite3.Connection, paths: list[str]) -> dict[str, list[str]]:
    """{path: its tags, A-Z} for the photos that have any."""
    found: dict[str, list[str]] = {}
    for i in range(0, len(paths), 500):
        chunk = paths[i : i + 500]
        marks = ",".join("?" * len(chunk))
        for path, tag in conn.execute(f"SELECT path, tag FROM tags WHERE path IN ({marks}) ORDER BY tag COLLATE NOCASE", chunk):
            found.setdefault(path, []).append(tag)
    return found


def all_tagged(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Every tagged photo's tags - for the Workbench, which shows the whole library at once."""
    found: dict[str, list[str]] = {}
    for path, tag in conn.execute("SELECT path, tag FROM tags ORDER BY tag COLLATE NOCASE"):
        found.setdefault(path, []).append(tag)
    return found


def set_tags(conn: sqlite3.Connection, path: str, tags: list[str]) -> None:
    conn.execute("DELETE FROM tags WHERE path = ?", (path,))
    conn.executemany("INSERT OR IGNORE INTO tags (path, tag) VALUES (?, ?)", [(path, t) for t in tags])
    conn.commit()


def add_tags(conn: sqlite3.Connection, paths: list[str], tags: list[str]) -> None:
    conn.executemany("INSERT OR IGNORE INTO tags (path, tag) VALUES (?, ?)", [(p, t) for p in paths for t in tags])
    conn.commit()


def remove_tags(conn: sqlite3.Connection, paths: list[str], tags: list[str]) -> None:
    conn.executemany("DELETE FROM tags WHERE path = ? AND tag = ?", [(p, t) for p in paths for t in tags])
    conn.commit()


def tag_counts(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """Every tag in use with how many photos carry it, most used first."""
    return [(t, n) for t, n in conn.execute("SELECT tag, COUNT(*) FROM tags GROUP BY tag COLLATE NOCASE ORDER BY COUNT(*) DESC, tag COLLATE NOCASE")]


_UNTOUCHED = {
    "exposure_ev": 0.0, "rotation_quarter_turns": 0, "flip_h": False, "flip_v": False, "crop_rect": None, "saturation": 0.0,
    "temperature": 0.0, "tint": 0.0, "shadows": 0.0, "highlights": 0.0, "sharpen_amount": 0.0, "dust_auto": False,
    "scratch_lines": [], "heal_strokes": [], "clone_strokes": [], "ai_dust": False, "marks": {}, "film_type": "auto", "invert_r": 0.0, "invert_g": 0.0, "invert_b": 0.0, "contrast": 0.0,
    "fine_rotation": 0.0, "distortion": 0.0, "chroma_denoise": 0.0, "local_contrast": 0.0, "metering": {}, "wm_film": "off",
    "vignette": 0.0, "border": 0.0, "carrier": False,
}


def is_untouched(state: dict, default_curve) -> bool:
    """True when a saved edit state is still what opening the photo gave it - nothing was changed."""
    if [tuple(p) for p in state["tone_curve_points"]] != [tuple(p) for p in default_curve]:
        return False
    return all(state[k] == v for k, v in _UNTOUCHED.items() if k in state)


def touched_paths(conn: sqlite3.Connection, paths: list[str], default_curve) -> set[str]:
    """Which of paths have edits that changed something (opening a photo saves a row, so a row alone does not mean it was edited)."""
    found: set[str] = set()
    for p in paths:
        state = load_edit_state(conn, p)
        if state is not None and not is_untouched(state, default_curve):
            found.add(p)
    return found


def get_folder_base(conn: sqlite3.Connection, folder: str) -> tuple[int, int, int] | None:
    row = conn.execute("SELECT r, g, b FROM folder_base WHERE folder = ?", (folder,)).fetchone()
    return (int(row[0]), int(row[1]), int(row[2])) if row else None


def set_folder_base(conn: sqlite3.Connection, folder: str, rgb: tuple[int, int, int]) -> None:
    conn.execute(
        "INSERT INTO folder_base (folder, r, g, b) VALUES (?, ?, ?, ?) ON CONFLICT(folder) DO UPDATE SET r=excluded.r, g=excluded.g, b=excluded.b",
        (folder, int(rgb[0]), int(rgb[1]), int(rgb[2])),
    )
    conn.commit()


def delete_folder_base(conn: sqlite3.Connection, folder: str) -> None:
    conn.execute("DELETE FROM folder_base WHERE folder = ?", (folder,))
    conn.commit()
