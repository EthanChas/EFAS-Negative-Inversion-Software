"""Exporting all the app's own data to one zip, and getting it back - sqlite3 / zipfile only, no Qt imports.

An export holds a consistent copy of the database (SQLite's backup API, safe while the app is writing), the preset and settings JSON files and the
saved gear, plus manifest.json. Importing never touches the live files: the zip is unpacked into restore_pending/, and the next start swaps it in
(apply_pending_restore) before the database is opened, keeping what it replaces in backups/before-restore-<time>/."""

import datetime as dt
import json
import os
import shutil
import sqlite3
import zipfile

DB_NAME = "photoeditor.db"
# the files worth carrying to another machine (caches, the library index, the session and recent lists are rebuilt on their own)
DATA_FILES = ("settings.json", "presets.json", "look_presets.json", "module_presets.json", "metadata_sticky.json")
GEAR_DIR = "gear"
MANIFEST = "manifest.json"
PENDING = "restore_pending"
_APP = "PhotoEditor data export"


def default_export_name(today: dt.date | None = None) -> str:
    return f"PhotoEditor-data-{(today or dt.date.today()).isoformat()}.zip"


def export_data(conn: sqlite3.Connection, data_dir: str, dest_zip: str) -> list[str]:
    """Write the zip; returns the names of the files it holds."""
    tmp_db = dest_zip + ".db.part"
    out = dest_zip + ".part"
    names: list[str] = []
    dest = sqlite3.connect(tmp_db)
    try:
        conn.commit()
        conn.backup(dest)
    finally:
        dest.close()
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(tmp_db, DB_NAME)
            names.append(DB_NAME)
            for name in DATA_FILES:
                path = os.path.join(data_dir, name)
                if os.path.isfile(path):
                    z.write(path, name)
                    names.append(name)
            gear = os.path.join(data_dir, GEAR_DIR)
            if os.path.isdir(gear):
                for root, _dirs, files in os.walk(gear):
                    for f in files:
                        full = os.path.join(root, f)
                        arc = GEAR_DIR + "/" + os.path.relpath(full, gear).replace(os.sep, "/")
                        z.write(full, arc)
                        names.append(arc)
            z.writestr(MANIFEST, json.dumps({"app": _APP, "made": dt.datetime.now().isoformat(timespec="seconds"), "files": names}, indent=2))
        os.replace(out, dest_zip)
    finally:
        for leftover in (tmp_db, out):
            try:
                os.remove(leftover)
            except OSError:
                pass
    return names


def _safe(name: str) -> bool:
    """Only the files an export holds, and nothing that could land outside the data folder."""
    if name == MANIFEST or name in (DB_NAME, *DATA_FILES):
        return True
    parts = name.split("/")
    return parts[0] == GEAR_DIR and len(parts) > 1 and all(p not in ("", ".", "..") and ":" not in p and "\\" not in p for p in parts)


def check_source(path: str) -> str:
    """"" when `path` is something Import can use: an export zip, or a database backup (.db). Otherwise a sentence saying why not."""
    if not os.path.isfile(path):
        return "That file does not exist."
    if path.lower().endswith(".db"):
        try:
            c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                c.close()
        except sqlite3.Error:
            return "That is not a readable database."
        return "" if "edits" in tables else "That database is not one of this app's."
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if MANIFEST not in names or DB_NAME not in names:
                return "That zip is not a PhotoEditor data export."
            if not all(_safe(n) for n in names if not n.endswith("/")):
                return "That zip holds files this app does not recognise."
    except zipfile.BadZipFile:
        return "That is not a zip file."
    return ""


def stage_import(path: str, data_dir: str) -> list[str]:
    """Unpack an export (or copy a .db backup) into data_dir/restore_pending/ for the next start. Returns what was staged."""
    problem = check_source(path)
    if problem:
        raise ValueError(problem)
    pending = os.path.join(data_dir, PENDING)
    shutil.rmtree(pending, ignore_errors=True)
    os.makedirs(pending)
    staged: list[str] = []
    if path.lower().endswith(".db"):
        shutil.copyfile(path, os.path.join(pending, DB_NAME))
        return [DB_NAME]
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.endswith("/") or name == MANIFEST:
                continue
            target = os.path.join(pending, *name.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(name) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            staged.append(name)
    return staged


def pending_restore(data_dir: str) -> bool:
    return os.path.isdir(os.path.join(data_dir, PENDING))


def cancel_pending(data_dir: str) -> None:
    shutil.rmtree(os.path.join(data_dir, PENDING), ignore_errors=True)


def apply_pending_restore(data_dir: str, now: dt.datetime | None = None) -> list[str]:
    """At start, before the database is opened: swap in what stage_import unpacked. What it replaces is kept first. Returns the files restored."""
    pending = os.path.join(data_dir, PENDING)
    if not os.path.isdir(pending):
        return []
    stamp = (now or dt.datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    keep = os.path.join(data_dir, "backups", f"before-restore-{stamp}")
    restored: list[str] = []
    try:
        for root, _dirs, files in os.walk(pending):
            for f in files:
                src = os.path.join(root, f)
                rel = os.path.relpath(src, pending)
                live = os.path.join(data_dir, rel)
                if os.path.isfile(live):
                    os.makedirs(os.path.dirname(os.path.join(keep, rel)), exist_ok=True)
                    shutil.copy2(live, os.path.join(keep, rel))
                os.makedirs(os.path.dirname(live), exist_ok=True)
                if rel == DB_NAME:  # the old write-ahead files belong to the old database
                    for ext in ("-wal", "-shm"):
                        try:
                            os.remove(live + ext)
                        except OSError:
                            pass
                os.replace(src, live)
                restored.append(rel.replace(os.sep, "/"))
    finally:
        shutil.rmtree(pending, ignore_errors=True)
    return restored
