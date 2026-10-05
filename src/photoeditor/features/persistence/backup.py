"""Database backups - sqlite3 only, no Qt imports."""

import datetime as dt
import os
import re
import sqlite3

_NAME = re.compile(r"^photoeditor-\d{4}-\d{2}-\d{2}\.db$")


def backup_database(conn: sqlite3.Connection, backup_dir: str, keep: int = 14, force: bool = False, today: dt.date | None = None) -> str | None:
    """Copy the live database to backup_dir/photoeditor-YYYY-MM-DD.db with SQLite's own backup API (safe while the
    app is writing) and keep only the newest `keep` copies. One per day: None when today's already exists, unless
    force replaces it. Written to a temp name first, so a crash never leaves a truncated backup under the real one."""
    day = (today or dt.date.today()).isoformat()
    path = os.path.join(backup_dir, f"photoeditor-{day}.db")
    if os.path.exists(path) and not force:
        return None
    os.makedirs(backup_dir, exist_ok=True)
    tmp = path + ".part"
    dest = sqlite3.connect(tmp)
    try:
        conn.commit()
        conn.backup(dest)
    finally:
        dest.close()
    os.replace(tmp, path)
    old = sorted(n for n in os.listdir(backup_dir) if _NAME.match(n))
    for name in old[: max(0, len(old) - keep)]:
        try:
            os.remove(os.path.join(backup_dir, name))
        except OSError:
            pass
    return path
