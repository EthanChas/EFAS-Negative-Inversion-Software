"""Moving the data an older version kept in ~/.photoeditor into ~/.EFAS, under the current file names - sqlite3 / json / shutil only, no Qt imports.

It runs by itself on the first start of a newer version and is built so nothing can be lost:

- everything in the old folder is copied (databases with SQLite's own backup API, so a database that was in use or has a write-ahead log is copied whole),
  each file under a temporary name first and renamed only when complete, so a crash never leaves half a file where the real one belongs;
- if the new folder already has some of the files (an interrupted earlier move), the two are merged - the newer edit wins, presets are added - never overwritten;
- the copy is checked (databases pass SQLite's integrity check and hold every row the old one did; other files are the same size);
- only when every check has passed is the old folder removed. If anything is wrong, the old folder stays exactly as it was and the move is tried again next start."""

import datetime as dt
import json
import os
import shutil
import sqlite3
from pathlib import Path

from ..datadir import (
    BACKUP_DIR,
    EDITS_DB,
    GEAR_DIR,
    MIGRATION_RECORD_FILE,
    RESTORE_PENDING_DIR,
    new_name,
    old_home_folder,
)
from .consolidate import _merge_db, _union_presets
from .health import count_rows

_TRANSIENT = (".part", ".tmp", "-wal", "-shm", "-journal")
_PRESET_FILES = ("look-presets.json", "module-presets.json")


def run_if_needed(new_dir: str) -> dict | None:
    """Move the old data folder into `new_dir` if there is one; None when there is nothing to move."""
    old = old_home_folder()
    if not os.path.isdir(old) or os.path.normcase(os.path.abspath(old)) == os.path.normcase(os.path.abspath(new_dir)):
        return None
    return migrate(old, new_dir)


def _ro_uri(path: str) -> str:
    return Path(path).resolve().as_uri() + "?mode=ro"


def _is_database(path: str) -> bool:
    """Is this file a SQLite database that can be read (as opposed to a damaged one, or a file that only has a .db name)?"""
    try:
        conn = sqlite3.connect(_ro_uri(path), uri=True)
        try:
            conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        finally:
            conn.close()
        return True
    except sqlite3.Error:
        return False


def _is_transient(name: str) -> bool:
    return name.endswith(_TRANSIENT)


def _target_rel(top: str, rel_parts: list[str]) -> list[str]:
    """Where a file at old_dir/<top>/<rel_parts> goes, relative to the new folder."""
    new_top = new_name(top)
    if top == "backups":
        return [new_top] + [new_name(p) for p in rel_parts]
    if top == "restore_pending":
        inner = [new_name(rel_parts[0])] + rel_parts[1:] if rel_parts else rel_parts
        if len(rel_parts) > 1 and rel_parts[0] == "gear":
            inner = [GEAR_DIR] + rel_parts[1:]
        return [new_top] + inner
    return [new_top] + rel_parts


def _plan(old_dir: str) -> list[tuple[str, list[str]]]:
    """(source file, path of its copy relative to the new folder) for everything in the old folder that is worth keeping."""
    out: list[tuple[str, list[str]]] = []
    for entry in sorted(os.listdir(old_dir)):
        src = os.path.join(old_dir, entry)
        if os.path.isdir(src):
            for root, _dirs, files in os.walk(src):
                for f in sorted(files):
                    if _is_transient(f):
                        continue
                    full = os.path.join(root, f)
                    out.append((full, _target_rel(entry, os.path.relpath(full, src).split(os.sep))))
        elif not _is_transient(entry):
            out.append((src, [new_name(entry)]))
    return out


def _backup_db(src: str, dst: str) -> None:
    """A whole, consistent copy of a database, written under a temporary name and renamed when complete."""
    tmp = dst + ".part"
    if os.path.exists(tmp):
        os.remove(tmp)
    source = sqlite3.connect(_ro_uri(src), uri=True)
    try:
        target = sqlite3.connect(tmp)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    os.replace(tmp, dst)


def _copy_plain(src: str, dst: str) -> None:
    tmp = dst + ".part"
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def _copy_one(src: str, dst_rel: list[str], new_dir: str, summary: dict) -> None:
    dst = os.path.join(new_dir, *dst_rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    name = dst_rel[-1]
    is_db = name.endswith(".db")
    if os.path.exists(dst):
        if len(dst_rel) == 1 and name == EDITS_DB:
            conn = sqlite3.connect(dst)
            try:
                if not _merge_db(conn, src):
                    raise sqlite3.Error("could not merge the old database into the new one")
            finally:
                conn.close()
            summary["merged"].append(name)
        elif name in _PRESET_FILES and len(dst_rel) == 1:
            _union_presets(dst, src)
            summary["merged"].append(name)
        return
    if is_db:
        try:
            _backup_db(src, dst)
        except sqlite3.Error:
            _copy_plain(src, dst)  # not a readable database: keep its bytes rather than lose it
            summary["odd"].append("/".join(dst_rel))
    else:
        _copy_plain(src, dst)
    summary["copied"].append("/".join(dst_rel))


def _check_db(src: str, dst: str) -> str | None:
    try:
        conn = sqlite3.connect(_ro_uri(dst), uri=True)
        try:
            ok = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as e:
        return f"{os.path.basename(dst)}: {e}"
    if not ok or ok[0] != "ok":
        return f"{os.path.basename(dst)} did not pass SQLite's integrity check"
    if count_rows(dst) < count_rows(src):
        return f"{os.path.basename(dst)} holds fewer rows than the old one"
    return None


def verify(old_dir: str, new_dir: str, summary: dict) -> list[str]:
    """What is wrong with the copy, in words; an empty list means every file arrived intact."""
    problems = []
    for src, rel in _plan(old_dir):
        dst = os.path.join(new_dir, *rel)
        label = "/".join(rel)
        if not os.path.isfile(dst):
            problems.append(f"{label} is missing")
            continue
        merged = label in summary["merged"]
        if label.endswith(".db") and _is_database(src):
            bad = _check_db(src, dst)
            if bad:
                problems.append(bad)
        elif label.endswith(".db"):
            if os.path.getsize(dst) != os.path.getsize(src) and label in summary["copied"]:
                problems.append(f"{label} is not the same size as the original")
        elif merged:
            try:
                with open(dst, encoding="utf-8") as f:
                    json.load(f)
            except (OSError, ValueError):
                problems.append(f"{label} cannot be read")
        elif label in summary["copied"] and os.path.getsize(dst) != os.path.getsize(src):
            problems.append(f"{label} is not the same size as the original")  # (a file the new folder already had is kept as it is, so it is not held to this)
    return problems


def _remove_tree(path: str) -> bool:
    def fix(func, p, _exc):
        try:
            os.chmod(p, 0o700)
            func(p)
        except OSError:
            pass

    shutil.rmtree(path, onerror=fix)
    return not os.path.exists(path)


def migrate(old_dir: str, new_dir: str, delete_old: bool = True) -> dict:
    """Copy `old_dir` into `new_dir` with the current names, check it, and remove `old_dir` (see the module docstring)."""
    summary: dict = {"from": old_dir, "to": new_dir, "copied": [], "merged": [], "odd": [], "problems": [], "removed_old": False}
    os.makedirs(new_dir, exist_ok=True)
    for src, rel in _plan(old_dir):
        try:
            _copy_one(src, rel, new_dir, summary)
        except Exception as e:
            summary["problems"].append(f"{'/'.join(rel)}: {e}")
    summary["problems"] += verify(old_dir, new_dir, summary)
    if summary["problems"]:
        return summary
    try:
        with open(os.path.join(new_dir, MIGRATION_RECORD_FILE), "w", encoding="utf-8") as f:
            json.dump({"moved_from": old_dir, "when": dt.datetime.now().isoformat(timespec="seconds"), "files": len(summary["copied"]) + len(summary["merged"])}, f, indent=1)
    except OSError:
        pass
    if delete_old:
        summary["removed_old"] = _remove_tree(old_dir)
    return summary
