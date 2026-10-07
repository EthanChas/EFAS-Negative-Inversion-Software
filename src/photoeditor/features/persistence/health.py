"""Noticing that the database lost its contents - sqlite3 / os only, no Qt imports.

A database that comes up nearly empty while a backup holds far more is almost never what the user wanted (the data folder moved, a file was
replaced, a restore went wrong). startup_check() compares the live database with the daily backups and the "best" copy kept beside them, so the
editor can say so and offer the backup instead of silently carrying on with an empty one."""

import os
import sqlite3

BEST_NAME = "photoeditor-best.db"  # the most-filled database ever seen; never rotated out with the daily copies
_COUNTED = ("edits", "ratings", "flags", "folder_roll", "folder_base", "tags", "snapshots")
_MIN_BACKUP_ROWS = 10      # a backup this small proves nothing
_LOSS_RATIO = 0.6          # the live database holding under this share of a backup's rows is a loss


def count_rows(db_path: str) -> int:
    """How much the user has put in a database: the rows of the tables that hold edits, marks and roll details. 0 when it cannot be read."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return 0
    try:
        total = 0
        for table in _COUNTED:
            try:
                total += conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:
                pass
        return total
    finally:
        conn.close()


def best_copy(backup_dir: str) -> tuple[str, int] | None:
    """(path, rows) of the fullest database in the backup folder (daily copies and the best copy), or None when there is none."""
    best = None
    try:
        names = [n for n in os.listdir(backup_dir) if n.endswith(".db")]
    except OSError:
        return None
    for name in names:
        path = os.path.join(backup_dir, name)
        rows = count_rows(path)
        if best is None or rows > best[1]:
            best = (path, rows)
    return best


def startup_check(db_path: str, backup_dir: str) -> dict | None:
    """None when all is well. Otherwise {"backup": path, "backup_rows": n, "live_rows": m}: the live database holds far less than a backup does."""
    best = best_copy(backup_dir)
    if best is None or best[1] < _MIN_BACKUP_ROWS:
        return None
    live = count_rows(db_path)
    if live >= best[1] * _LOSS_RATIO:
        return None
    return {"backup": best[0], "backup_rows": best[1], "live_rows": live}


def update_best(conn: sqlite3.Connection, backup_dir: str) -> bool:
    """Keep a copy of the fullest database seen: after a backup, if the live one holds more than the best copy does, it becomes the best copy."""
    best_path = os.path.join(backup_dir, BEST_NAME)
    live_rows = 0
    for table in _COUNTED:
        try:
            live_rows += conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.Error:
            pass
    best_rows = count_rows(best_path) if os.path.isfile(best_path) else 0
    if live_rows < _MIN_BACKUP_ROWS or live_rows <= best_rows:
        return False
    os.makedirs(backup_dir, exist_ok=True)
    tmp = best_path + ".part"
    dest = sqlite3.connect(tmp)
    try:
        conn.commit()
        conn.backup(dest)
    finally:
        dest.close()
    os.replace(tmp, best_path)
    return True
