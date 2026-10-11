"""A journal of whole-roll actions (Crop Roll, Reset Crops, Paste to Folder, Even Out Roll) so each can be undone in one step.

For every photo an action changed, the journal keeps the fields it changed, as they were before and as the action left them. Undoing puts the "before" values back, but
only on photos where those fields still hold what the action wrote: a photo edited since is left alone and reported, so an undo never wipes later work. Only the last few
actions per folder are kept. No Qt imports."""

import json
import os
import sqlite3
from dataclasses import dataclass, field

from . import edit_store

KEEP = 5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS roll_undo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder TEXT NOT NULL,
    label TEXT NOT NULL,
    created TEXT NOT NULL,
    data TEXT NOT NULL
)
"""


def ensure(conn: sqlite3.Connection) -> None:
    conn.execute(_SCHEMA)


def _plain(value):
    """A value as JSON makes it (tuples become lists), so before/after comparisons do not trip on the type."""
    return json.loads(json.dumps(value))


@dataclass
class Entry:
    id: int
    folder: str
    label: str
    created: str
    ops: list


@dataclass
class UndoResult:
    restored: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


def fields_op(path: str, before: dict, after: dict) -> dict:
    """An edit-state change on one photo: the changed fields before and after."""
    return {"kind": "fields", "path": path, "before": _plain(before), "after": _plain(after)}


def film_base_op(path: str, before, after) -> dict:
    """A change of one photo's own film base (None means it used the roll's)."""
    return {"kind": "film_base", "path": path, "before": _plain(before), "after": _plain(after)}


def record(conn: sqlite3.Connection, folder: str, label: str, ops: list) -> int | None:
    """Keep an action's changes. Nothing is recorded for an action that changed nothing."""
    if not ops:
        return None
    ensure(conn)
    key = edit_store.folder_key(folder, is_file=False)
    cur = conn.execute("INSERT INTO roll_undo (folder, label, created, data) VALUES (?, ?, datetime('now', 'localtime'), ?)", (key, label, json.dumps(ops)))
    conn.execute("DELETE FROM roll_undo WHERE folder = ? AND id NOT IN (SELECT id FROM roll_undo WHERE folder = ? ORDER BY id DESC LIMIT ?)", (key, key, KEEP))
    conn.commit()
    return cur.lastrowid


def latest(conn: sqlite3.Connection, folder: str) -> Entry | None:
    ensure(conn)
    key = edit_store.folder_key(folder, is_file=False)
    row = conn.execute("SELECT id, folder, label, created, data FROM roll_undo WHERE folder = ? ORDER BY id DESC LIMIT 1", (key,)).fetchone()
    if row is None:
        return None
    try:
        return Entry(row[0], row[1], row[2], row[3], json.loads(row[4]))
    except ValueError:
        return None


def discard(conn: sqlite3.Connection, entry_id: int) -> None:
    conn.execute("DELETE FROM roll_undo WHERE id = ?", (entry_id,))
    conn.commit()


def _current_fields(state: dict, names) -> dict:
    return {k: _plain(state.get(k)) for k in names}


def undo(conn: sqlite3.Connection, entry: Entry, skip_paths: set[str] | None = None) -> UndoResult:
    """Put the entry's "before" values back wherever the photo still holds the "after" values. `skip_paths` are photos the caller deals with itself (the open one)."""
    from ..xmp import logic as xmp

    result = UndoResult()
    skip = {os.path.normcase(os.path.abspath(p)) for p in (skip_paths or ())}
    for op in entry.ops:
        path = op["path"]
        if os.path.normcase(os.path.abspath(path)) in skip:
            continue
        if op["kind"] == "film_base":
            current = edit_store.get_photo_film_base(conn, path)
            if _plain(current) != op["after"]:
                result.skipped.append((path, "its film base was changed since"))
                continue
            edit_store.set_photo_film_base(conn, path, tuple(op["before"]) if op["before"] else None)
            result.restored.append(path)
            continue
        state = edit_store.load_edit_state(conn, path)
        if state is None:
            result.skipped.append((path, "it no longer has saved edits"))
            continue
        names = list(op["after"])
        if _current_fields(state, names) != op["after"]:
            result.skipped.append((path, "it was edited since"))
            continue
        for k, v in op["before"].items():
            state[k] = tuple(v) if isinstance(v, list) and k in ("crop_rect",) else v
        edit_store.save_edit_state(conn, path, state)
        if "crop_rect" in op["before"] and state.get("crop_rect") is None:
            try:
                xmp.write_sidecar(path, state, (1, 1))
            except Exception:
                pass
        result.restored.append(path)
    discard(conn, entry.id)
    return result
