"""Bringing every copy of the user's data into the one data folder - sqlite3 / json / shutil only, no Qt imports.

Earlier versions kept their data in AppData, and a program started from a packaged app (or under another executable's name) got a private copy of
it - so the same user could have several sets of edits, and which one the editor showed depended on how it was started (see features/datadir.py).
This merges them all into `app_data_dir()`:

* the database: the copy with the newest edits is taken as the base when there is no database yet; then every other copy is merged in - a photo's
  edit from the copy that saved it last wins, and ratings, flags, roll cards, film bases, flat-fields, tags and snapshots are added where missing;
* the small JSON files (settings, presets, session...): copied when missing, and the look / module presets are unioned by name;
* the saved gear and the daily database backups: copied when missing.

Nothing is ever deleted or changed in the old copies. Each old database is merged once per state it is in (its size and time are remembered), so a
copy that is used again later - another launch of the old way - is merged again, and nothing a user did there is left behind."""

import glob
import json
import os
import shutil
import sqlite3
from datetime import datetime

_MARKER = "consolidated.json"
_JSON_FILES = ("settings.json", "look_presets.json", "module_presets.json", "presets.json", "metadata_sticky.json", "recents.json", "session.json")
_BACKUP_GLOB = "photoeditor-????-??-??.db"
# table -> (key columns, True when the row from the other copy replaces ours if it is newer)
_TABLES = {
    "edits": (("path",), True),
    "ratings": (("path",), False),
    "flags": (("path",), False),
    "folder_roll": (("folder",), True),
    "folder_base": (("folder",), False),
    "folder_flatfield": (("folder",), False),
    "tags": (("path", "tag"), False),
    "snapshots": (("path", "name"), False),
}
_done_dirs: set[str] = set()


def ensure_ready() -> None:
    """Once per process: merge any other copies of the data into the data folder. Skipped when the folder is overridden (tests), and never raises."""
    from ..datadir import app_data_dir, legacy_data_dirs

    if os.environ.get("PHOTOEDITOR_DATA_DIR"):
        return
    target = app_data_dir()
    if target in _done_dirs:
        return
    _done_dirs.add(target)
    try:
        consolidate(target, legacy_data_dirs())
    except Exception:  # nothing here may stop the editor starting
        pass


def _fingerprint(path: str) -> str:
    st = os.stat(path)
    return f"{os.path.normcase(os.path.abspath(path))}|{st.st_size}|{st.st_mtime_ns}"


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA {schema}.table_info({table})")]


def _newest_edit(path: str) -> str:
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = c.execute("SELECT MAX(updated_at) FROM edits").fetchone()
        finally:
            c.close()
        return row[0] or ""
    except sqlite3.Error:
        return ""


def _merge_db(target: sqlite3.Connection, other: str) -> bool:
    """Merge one other database into `target`. False when it could not be read."""
    try:
        target.commit()
        target.execute("ATTACH DATABASE ? AS other", (other,))  # only ever read from
    except sqlite3.Error:
        return False
    try:
        for table, (keys, newer_wins) in _TABLES.items():
            theirs = set(_columns(target, "other", table))
            if not theirs:
                continue
            common = [c for c in _columns(target, "main", table) if c in theirs]
            if not set(keys) <= set(common):
                continue
            cols = ", ".join(common)
            if newer_wins and "updated_at" in common:
                sets = ", ".join(f"{c}=excluded.{c}" for c in common if c not in keys)
                target.execute(
                    f"INSERT INTO main.{table} ({cols}) SELECT {cols} FROM other.{table} WHERE true "
                    f"ON CONFLICT({', '.join(keys)}) DO UPDATE SET {sets} WHERE excluded.updated_at > main.{table}.updated_at"
                )
            else:
                target.execute(f"INSERT OR IGNORE INTO main.{table} ({cols}) SELECT {cols} FROM other.{table}")
        target.commit()
        return True
    except sqlite3.Error:
        target.rollback()
        return False
    finally:
        target.execute("DETACH DATABASE other")


def _union_presets(ours: str, theirs: str) -> None:
    """Add the presets of `theirs` whose names `ours` lacks (look_presets.json: {"presets": [...]}, module_presets.json: {module: [...]})."""
    try:
        with open(ours, encoding="utf-8") as f:
            mine = json.load(f)
        with open(theirs, encoding="utf-8") as f:
            other = json.load(f)
    except (OSError, ValueError):
        return

    def add(into: list, extra: list) -> bool:
        names = {str(p.get("name", "")).casefold() for p in into if isinstance(p, dict)}
        added = False
        for p in extra:
            if isinstance(p, dict) and str(p.get("name", "")).casefold() not in names:
                into.append(p)
                names.add(str(p.get("name", "")).casefold())
                added = True
        return added

    changed = False
    if isinstance(mine, dict) and isinstance(other, dict):
        if isinstance(mine.get("presets"), list) and isinstance(other.get("presets"), list):
            changed = add(mine["presets"], other["presets"])
        else:
            for module, plist in other.items():
                if isinstance(plist, list):
                    changed |= add(mine.setdefault(module, []), plist)
    if changed:
        tmp = ours + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(mine, f, indent=1)
        os.replace(tmp, ours)


def consolidate(target_dir: str, other_dirs: list[str]) -> dict:
    """Merge the data in `other_dirs` into `target_dir` (see the module docstring). Returns {"databases": [merged paths], "files": [copied names]}."""
    from .edit_store import connect

    os.makedirs(target_dir, exist_ok=True)
    marker_path = os.path.join(target_dir, _MARKER)
    try:
        with open(marker_path, encoding="utf-8") as f:
            done = set(json.load(f))
    except (OSError, ValueError):
        done = set()
    summary: dict = {"databases": [], "files": []}

    # ---- the database ----
    target_db = os.path.join(target_dir, "photoeditor.db")
    dbs = [os.path.join(d, "photoeditor.db") for d in other_dirs if os.path.isfile(os.path.join(d, "photoeditor.db"))]
    fresh = [p for p in dbs if _fingerprint(p) not in done]
    if fresh:
        fresh.sort(key=lambda p: (_newest_edit(p), os.path.getmtime(p)), reverse=True)  # the copy with the newest edits first
        if not os.path.isfile(target_db):  # nothing here yet: start from the best copy, whole
            base = fresh.pop(0)
            try:
                src = sqlite3.connect(f"file:{base}?mode=ro", uri=True)
                dst = sqlite3.connect(target_db)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
                    src.close()
                done.add(_fingerprint(base))
                summary["databases"].append(base)
            except sqlite3.Error:
                if os.path.isfile(target_db):
                    os.remove(target_db)
        conn = connect(target_db)  # creates / upgrades the tables, so the merge below always has somewhere to put things
        try:
            for path in fresh:
                _merge_db(conn, path)  # one that cannot be read is not retried until it changes
                done.add(_fingerprint(path))
                summary["databases"].append(path)
        finally:
            conn.close()

    # ---- the small files, the gear and the daily backups ----
    for name in _JSON_FILES:
        ours = os.path.join(target_dir, name)
        copies = sorted((os.path.join(d, name) for d in other_dirs if os.path.isfile(os.path.join(d, name))), key=os.path.getmtime, reverse=True)
        if not copies:
            continue
        if not os.path.isfile(ours):
            shutil.copy2(copies[0], ours)
            summary["files"].append(name)
            copies = copies[1:]
        if name in ("look_presets.json", "module_presets.json"):
            for other in copies:
                _union_presets(ours, other)
    for d in other_dirs:
        gear = os.path.join(d, "gear")
        if os.path.isdir(gear):
            for root, _dirs, files in os.walk(gear):
                for f in files:
                    src = os.path.join(root, f)
                    dst = os.path.join(target_dir, "gear", os.path.relpath(src, gear))
                    if not os.path.exists(dst):
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.copy2(src, dst)
                        summary["files"].append(os.path.join("gear", os.path.relpath(src, gear)))
        for src in glob.glob(os.path.join(d, "backups", _BACKUP_GLOB)):
            dst = os.path.join(target_dir, "backups", os.path.basename(src))
            if not os.path.exists(dst):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                summary["files"].append(os.path.join("backups", os.path.basename(src)))

    if summary["databases"] or summary["files"] or not os.path.isfile(marker_path):
        try:
            with open(marker_path, "w", encoding="utf-8") as f:
                json.dump(sorted(done), f)
        except OSError:
            pass
    return summary
