"""One-time merge of the databases older versions wrote - no Qt imports.

The database used to live in Qt's per-executable data folder, so launching as `python`, `pythonw` or the
packaged EXE each wrote their own copy of the user's edits, flags and folder flat-fields. The app now keeps
one database in a fixed folder; this copies those older ones into it. Old files are only read, never changed
or deleted, and each is merged once (a flat-field the user removes later must not come back)."""

import json
import os
import sqlite3

_MARKER = "legacy_merged.json"
_TABLES = ("edits", "flags", "folder_flatfield")


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA {schema}.table_info({table})")]


def merge_legacy_databases(conn: sqlite3.Connection, data_dir: str, legacy_dbs: list[str]) -> list[str]:
    """Copy rows from each legacy database that the current one doesn't already have (newest file first, so the
    most recently used copy wins a conflict). Returns the databases merged this call."""
    marker = os.path.join(data_dir, _MARKER)
    try:
        with open(marker, encoding="utf-8") as f:
            done = set(json.load(f))
    except (OSError, json.JSONDecodeError):
        done = set()
    todo = [p for p in legacy_dbs if os.path.abspath(p) not in done and os.path.isfile(p)]
    todo.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    merged: list[str] = []
    for path in todo:
        try:
            conn.commit()
            conn.execute("ATTACH DATABASE ? AS legacy", (path,))  # only ever read from
        except sqlite3.Error:
            continue
        try:
            for table in _TABLES:
                legacy_cols = set(_columns(conn, "legacy", table))
                common = [c for c in _columns(conn, "main", table) if c in legacy_cols]
                if not common:
                    continue
                cols = ", ".join(common)
                conn.execute(f"INSERT OR IGNORE INTO main.{table} ({cols}) SELECT {cols} FROM legacy.{table}")
            conn.commit()
            merged.append(os.path.abspath(path))
        except sqlite3.Error:
            conn.rollback()  # an unreadable or half-written old file is skipped, not retried forever below
            merged.append(os.path.abspath(path))
        finally:
            conn.execute("DETACH DATABASE legacy")
    if merged:
        try:
            os.makedirs(data_dir, exist_ok=True)
            with open(marker, "w", encoding="utf-8") as f:
                json.dump(sorted(done | set(merged)), f)
        except OSError:
            pass
    return merged
